"""Hash-anchored file edits (stdlib-only, cross-platform).

Opt-in parity/benchmark path only: off by default. Set HARNESS_HASH_EDIT=1 to
expose the hash_edit tool and annotate read_file with content anchors. The
default product edit path remains edit_file (and apply_hashline for workers).

When enabled, read_file can emit stable short content tags; hash_edit applies
replace/insert/delete operations that verify anchors before writing. Stale
anchors are rejected with no partial writes. Line endings are normalized for
hashing and preserved on write.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Literal, Optional

from .context_budget import content_hash

ANCHOR_OPEN = "[@anchor"
ANCHOR_CLOSE = "[@/anchor]"

OpKind = Literal["replace", "insert", "delete"]


def hash_edit_enabled() -> bool:
    """Return whether hash-anchored edits are enabled.

    Off by default. Opt in with HARNESS_HASH_EDIT=1/true/yes for parity and
    benchmark work against hashline-style edit protocols, not the shipped
    default edit path.
    """
    return os.environ.get("HARNESS_HASH_EDIT", "").strip().lower() in ("1", "true", "yes")


def normalize_newlines(text: str) -> str:
    """Normalize CRLF/CR to LF for stable cross-platform hashing."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def detect_eol_style(text: str) -> str:
    """Return the dominant line ending style in ``text``."""
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    cr_only = text.count("\r") - crlf
    if crlf > 0 and crlf >= max(lf_only, cr_only):
        return "\r\n"
    if cr_only > lf_only:
        return "\r"
    return "\n"


def split_lines(text: str) -> list[str]:
    """Split normalized text into lines without trailing empty from final newline."""
    norm = normalize_newlines(text)
    if not norm:
        return []
    parts = norm.split("\n")
    if norm.endswith("\n"):
        parts.pop()
    return parts


def join_lines(lines: list[str], eol: str) -> str:
    """Join lines with ``eol``, matching read_file/write conventions."""
    if not lines:
        return ""
    body = "\n".join(lines)
    return body.replace("\n", eol)


def range_text(lines: list[str], start_line: int, end_line: int) -> str:
    """Extract inclusive 1-based line range as LF-normalized text for hashing."""
    if start_line < 1 or end_line < start_line:
        raise ValueError(f"invalid line range {start_line}-{end_line}")
    if start_line > len(lines):
        return ""
    end_line = min(end_line, len(lines))
    return "\n".join(lines[start_line - 1 : end_line])


def file_text(lines: list[str]) -> str:
    """Full file body as LF-normalized text for hashing."""
    return "\n".join(lines)


def compute_range_hash(lines: list[str], start_line: int, end_line: int) -> str:
    return content_hash(range_text(lines, start_line, end_line))


def compute_file_hash(lines: list[str]) -> str:
    return content_hash(file_text(lines))


def format_anchor_tag(
    *,
    kind: str,
    hash_value: str,
    start_line: int,
    end_line: int,
) -> str:
    return f"{ANCHOR_OPEN} {kind} hash={hash_value} lines={start_line}-{end_line}]"


def wrap_with_anchor(content: str, tag_line: str) -> str:
    """Wrap ``content`` with open/close anchor markers for read_file output."""
    if not content:
        return f"{tag_line}\n{ANCHOR_CLOSE}\n"
    if content.endswith("\n"):
        return f"{tag_line}\n{content}{ANCHOR_CLOSE}\n"
    return f"{tag_line}\n{content}\n{ANCHOR_CLOSE}\n"


def annotate_read_content(
    content: str,
    *,
    total_lines: int,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """Add hash anchor tags to read_file output when hash_edit is enabled."""
    if not hash_edit_enabled():
        return content

    norm = normalize_newlines(content)
    range_header = ""
    payload = norm
    parsed_start = start_line
    parsed_end = end_line

    if payload.startswith("[lines "):
        nl = payload.find("\n")
        if nl >= 0:
            range_header = payload[: nl + 1]
            payload = payload[nl + 1 :]
            # Parse "[lines 3-6 of 10]", tolerating a trailing continuation
            # note such as "; next start_line=7".
            m = re.match(r"\[lines (\d+)-(\d+) of \d+", range_header.strip())
            if m:
                parsed_start = int(m.group(1))
                parsed_end = int(m.group(2))

    lines = split_lines(payload)
    s = parsed_start if parsed_start is not None else 1
    e = parsed_end if parsed_end is not None else total_lines
    kind = "range" if (parsed_start is not None or parsed_end is not None) else "file"
    if kind == "file":
        h = compute_file_hash(lines) if lines else content_hash("")
    else:
        h = compute_range_hash(lines, 1, max(1, len(lines))) if lines else content_hash("")

    tag = format_anchor_tag(kind=kind, hash_value=h, start_line=s, end_line=e)
    wrapped = wrap_with_anchor(payload if payload else "", tag)
    return range_header + wrapped


@dataclass
class HashEditOp:
    op: OpKind
    anchor: str = ""
    start_line: int = 0
    end_line: int = 0
    after_line: int = -1
    text: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HashEditOp":
        op = (raw.get("op") or raw.get("kind") or "").strip().lower()
        if op not in ("replace", "insert", "delete"):
            raise ValueError(f"unknown hash_edit op: {op!r}")
        anchor = (raw.get("anchor") or raw.get("hash") or "").strip()
        start_line = int(raw.get("start_line") or raw.get("line") or 0)
        end_line = int(raw.get("end_line") or raw.get("start_line") or raw.get("line") or 0)
        after_line = int(raw.get("after_line") if raw.get("after_line") is not None else -1)
        text = raw.get("text")
        if text is None:
            text = raw.get("new_text") or raw.get("content") or ""
        return cls(
            op=op,  # type: ignore[arg-type]
            anchor=anchor,
            start_line=start_line,
            end_line=end_line,
            after_line=after_line,
            text=str(text),
        )


@dataclass
class ApplyResult:
    ok: bool
    message: str
    stale_anchors: list[str]
    applied_ops: int = 0


def _validate_op(op: HashEditOp, lines: list[str]) -> Optional[str]:
    """Return an error string if the op fails anchor validation."""
    if op.op in ("replace", "delete"):
        if op.start_line < 1:
            return f"{op.op}: start_line must be >= 1"
        if op.end_line < op.start_line:
            op.end_line = op.start_line
        if not op.anchor:
            return f"{op.op}: anchor hash is required"
        if op.start_line > len(lines):
            return f"{op.op}: start_line {op.start_line} beyond file ({len(lines)} lines)"
        actual = compute_range_hash(lines, op.start_line, op.end_line)
        if actual != op.anchor:
            return (
                f"stale anchor for {op.op} lines {op.start_line}-{op.end_line}: "
                f"expected {op.anchor}, found {actual}"
            )
        return None

    # insert
    if op.after_line < 0:
        return "insert: after_line is required (0 = before first line)"
    if op.after_line > len(lines):
        return f"insert: after_line {op.after_line} beyond file ({len(lines)} lines)"
    if op.anchor:
        if op.after_line == 0:
            expected = content_hash("") if not lines else compute_range_hash(lines, 1, 1)
        else:
            expected = compute_range_hash(lines, op.after_line, op.after_line)
        if op.anchor != expected:
            return (
                f"stale anchor for insert after line {op.after_line}: "
                f"expected {op.anchor}, found {expected}"
            )
    return None


def _overlap_errors(ops: list[HashEditOp]) -> list[str]:
    """Detect overlapping replace/delete ranges and insert positions.

    Deterministic: reports every pairwise conflict using original op indices.
    Adjacent non-overlapping ranges (e.g. 1-2 and 3-4) are allowed.
    """
    errors: list[str] = []
    ranges: list[tuple[int, int, int]] = []  # start, end, op_index
    inserts: list[tuple[int, int]] = []  # after_line, op_index

    for i, op in enumerate(ops):
        if op.op in ("replace", "delete"):
            start = int(op.start_line or 0)
            end = int(op.end_line or start)
            if end < start:
                end = start
            ranges.append((start, end, i))
        elif op.op == "insert":
            inserts.append((int(op.after_line), i))

    for a in range(len(ranges)):
        s1, e1, i1 = ranges[a]
        for b in range(a + 1, len(ranges)):
            s2, e2, i2 = ranges[b]
            if s1 <= e2 and s2 <= e1:
                errors.append(
                    f"op[{i1}] and op[{i2}]: overlapping {ops[i1].op}/{ops[i2].op} "
                    f"ranges {s1}-{e1} and {s2}-{e2}"
                )

    seen_inserts: dict[int, int] = {}
    for after, i in inserts:
        prev = seen_inserts.get(after)
        if prev is not None:
            errors.append(
                f"op[{prev}] and op[{i}]: overlapping insert positions "
                f"after_line={after}"
            )
        else:
            seen_inserts[after] = i

    for after, i in inserts:
        for start, end, j in ranges:
            # Insert after line L anchors on line L; conflicts if that line is
            # inside a replace/delete range.
            if after >= start and after <= end:
                errors.append(
                    f"op[{i}] and op[{j}]: insert after_line={after} overlaps "
                    f"{ops[j].op} range {start}-{end}"
                )

    return errors


def apply_hash_edits(
    original_text: str,
    ops: list[HashEditOp],
) -> tuple[str, ApplyResult]:
    """Validate all ops against ``original_text``, then apply in memory.

    Returns (new_text, result). On failure ``new_text`` is the unchanged
    original and nothing should be written. Overlapping replace/delete ranges
    and insert positions are rejected before any mutation.
    """
    eol = detect_eol_style(original_text)
    lines = split_lines(normalize_newlines(original_text))
    stale: list[str] = []
    errors: list[str] = []

    for i, op in enumerate(ops):
        err = _validate_op(op, lines)
        if err:
            errors.append(f"op[{i}]: {err}")
            if "stale anchor" in err and op.anchor:
                stale.append(op.anchor)

    if not errors:
        errors.extend(_overlap_errors(ops))

    if errors:
        return original_text, ApplyResult(
            ok=False,
            message="; ".join(errors),
            stale_anchors=stale,
        )

    # Apply in reverse line order so earlier line numbers stay valid during mutation.
    indexed = list(enumerate(ops))

    def sort_key(item: tuple[int, HashEditOp]) -> tuple[int, int]:
        _, op = item
        if op.op == "insert":
            return (op.after_line, 0)
        return (op.start_line, 1)

    # Keep physical terminators on untouched lines. The BOM participates in
    # existing anchor hashes, but belongs to the file rather than its first line.
    bom = "\ufeff" if original_text.startswith("\ufeff") else ""
    body = original_text[len(bom):]
    physical = re.findall(r"([^\r\n]*)(\r\n|\r|\n|$)", body)[:-1]
    for _, op in sorted(indexed, key=sort_key, reverse=True):
        start = op.after_line if op.op == "insert" else op.start_line - 1
        end = start if op.op == "insert" else min(op.end_line, len(physical))
        local_eol = physical[start][1] if start < len(physical) else eol
        replacement = [] if op.op == "delete" else [
            (line, local_eol or eol) for line in split_lines(op.text)
        ]
        physical[start:end] = replacement

    if physical:
        # Insertions after an unterminated line need a separator. Preserve the
        # original final terminator (or its absence), including mixed EOL files.
        final_eol = re.search(r"(\r\n|\r|\n)\Z", original_text)
        physical[-1] = (physical[-1][0], final_eol.group() if final_eol else "")
    new_text = bom + "".join(
        line + ((ending or eol) if i < len(physical) - 1 else ending)
        for i, (line, ending) in enumerate(physical)
    )

    return new_text, ApplyResult(
        ok=True,
        message=f"applied {len(ops)} op(s)",
        stale_anchors=[],
        applied_ops=len(ops),
    )


class FileChangedError(OSError):
    """The file no longer matches the version used to compute an edit."""


@dataclass(frozen=True)
class FileSnapshot:
    data: bytes
    version: tuple[int, ...]
    mode: int

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="strict")


def _file_version(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid)


def read_file_snapshot(path: str) -> FileSnapshot:
    """Read bytes and version from one descriptor, refusing unstable reads."""
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("hash_edit requires a regular file, not a symlink or special file")
    with open(path, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _file_version(before) != _file_version(opened):
            raise FileChangedError("file changed while opening; re-read before editing")
        data = stream.read()
        after = os.fstat(stream.fileno())
    version = _file_version(opened)
    if (version != _file_version(after) or version != _file_version(os.lstat(path))
            or len(data) != after.st_size):
        raise FileChangedError("file changed while reading; re-read before editing")
    return FileSnapshot(data, version, stat.S_IMODE(opened.st_mode))


# Serialize only cooperating hash-edit commits in this process. This is not an
# OS-level CAS: external writers can still race the final check and os.replace.
_write_lock = threading.Lock()


def atomic_write_text(path: str, content: str, *, expected: FileSnapshot) -> None:
    """Replace a matching snapshot, preserving mode; refuse detected conflicts.

    Other processes and writers that do not use this boundary are not locked.
    Their changes after the final snapshot check cannot be detected atomically.
    """
    target_dir = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(dir=target_dir, prefix=".tmp-hash-edit-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, expected.mode)
        with _write_lock:
            try:
                current = read_file_snapshot(path)
            except OSError as exc:
                raise FileChangedError("file changed before write; re-read before editing") from exc
            if current != expected:
                raise FileChangedError("file changed before write; re-read before editing")
            os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            if os.name == "nt":
                os.chmod(temp_path, stat.S_IWRITE)
            os.remove(temp_path)


def apply_hash_edits_to_file(path: str, ops: list[HashEditOp]) -> ApplyResult:
    """Read, validate, and replace a matching file snapshot."""
    try:
        snapshot = read_file_snapshot(path)
        new_text, result = apply_hash_edits(snapshot.text, ops)
        if result.ok:
            atomic_write_text(path, new_text, expected=snapshot)
        return result
    except UnicodeDecodeError as exc:
        return ApplyResult(
            ok=False,
            message=f"file is not valid UTF-8 (hash_edit refuses to rewrite it): {path}: {exc}",
            stale_anchors=[],
        )
    except OSError as exc:
        return ApplyResult(ok=False, message=str(exc), stale_anchors=[])
