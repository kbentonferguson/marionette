"""Production hash-edit byte, mode and concurrent-write regressions."""
from concurrent.futures import ThreadPoolExecutor
import os
import stat
import threading
from types import SimpleNamespace

import pytest

from harness import hash_edit
from harness.pilot import PilotAction
from harness.tool_dispatch import ToolDispatchMixin


@pytest.fixture
def dispatcher(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HASH_EDIT", "1")
    dispatch = ToolDispatchMixin()
    dispatch.config = SimpleNamespace(repo=str(tmp_path))
    return dispatch


def action(data, text="AFTER", line=1):
    anchor = hash_edit.compute_range_hash(
        hash_edit.split_lines(data.decode("utf-8", errors="replace")), line, line
    )
    return PilotAction(kind="hash_edit", path="sample", arguments={"ops": [
        {"op": "replace", "start_line": line, "anchor": anchor, "text": text}
    ]})


@pytest.mark.parametrize("write", [True, False])
def test_dispatch_refuses_invalid_utf8(dispatcher, tmp_path, write):
    path = tmp_path / "sample"
    data = b"before\ninvalid\xff\n"
    path.write_bytes(data)
    result = dispatcher._do_hash_edit(action(data), write=write)
    assert not result[0], result
    assert "UTF-8" in result[2]
    assert path.read_bytes() == data


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable permissions")
def test_dispatch_preserves_executable_mode(dispatcher, tmp_path):
    path = tmp_path / "sample"
    path.write_bytes(b"before\n")
    path.chmod(0o755)
    assert dispatcher._do_hash_edit(action(b"before\n"))[0]
    assert path.read_bytes() == b"AFTER\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o755


@pytest.mark.parametrize("data,expected", [
    (b"before\nother\n", b"AFTER\nother\n"),
    (b"before\r\nother\r\n", b"AFTER\r\nother\r\n"),
    (b"before\rother\r", b"AFTER\rother\r"),
    (b"before\r\nother\nlast", b"AFTER\r\nother\nlast"),
    (b"\xef\xbb\xbfbefore\r\nother", b"\xef\xbb\xbfAFTER\r\nother"),
])
def test_dispatch_preserves_text_format(dispatcher, tmp_path, data, expected):
    path = tmp_path / "sample"
    path.write_bytes(data)
    assert dispatcher._do_hash_edit(action(data))[0]
    assert path.read_bytes() == expected


def test_dispatch_stale_anchor_does_not_write(dispatcher, tmp_path):
    path = tmp_path / "sample"
    path.write_bytes(b"new\n")
    result = dispatcher._do_hash_edit(action(b"old\n"))
    assert result[1] == "stale_anchor"
    assert path.read_bytes() == b"new\n"


def test_dispatch_refuses_change_after_read(dispatcher, tmp_path, monkeypatch):
    path = tmp_path / "sample"
    data = b"before\nother\n"
    path.write_bytes(data)
    reached = threading.Event()
    resume = threading.Event()
    apply = hash_edit.apply_hash_edits

    def paused(*args):
        reached.set()
        assert resume.wait(5)
        return apply(*args)

    monkeypatch.setattr(hash_edit, "apply_hash_edits", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(dispatcher._do_hash_edit, action(data))
        try:
            assert reached.wait(5)
            path.write_bytes(b"before\nEXTERNAL\n")
        finally:
            resume.set()
        result = future.result(timeout=5)
    assert not result[0], result
    assert path.read_bytes() == b"before\nEXTERNAL\n"


def test_two_dispatch_writers_cannot_overwrite_same_snapshot(dispatcher, tmp_path, monkeypatch):
    path = tmp_path / "sample"
    data = b"before\n"
    path.write_bytes(data)
    barrier = threading.Barrier(2)
    apply = hash_edit.apply_hash_edits

    def paused(*args):
        result = apply(*args)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(hash_edit, "apply_hash_edits", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(dispatcher._do_hash_edit, action(data, text))
                   for text in ("FIRST", "SECOND")]
        results = [future.result(timeout=5) for future in futures]
    assert sum(result[0] for result in results) == 1, results
    assert path.read_bytes() in (b"FIRST\n", b"SECOND\n")


@pytest.mark.parametrize("change", ["bytes", "identity", "mode", "missing"])
def test_dispatch_refuses_change_during_temp_preparation(
    dispatcher, tmp_path, monkeypatch, change
):
    path = tmp_path / "sample"
    data = b"before\n"
    path.write_bytes(data)
    reached = threading.Event()
    resume = threading.Event()
    mkstemp = hash_edit.tempfile.mkstemp

    def paused(*args, **kwargs):
        result = mkstemp(*args, **kwargs)
        reached.set()
        assert resume.wait(5)
        return result

    monkeypatch.setattr(hash_edit.tempfile, "mkstemp", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(dispatcher._do_hash_edit, action(data))
        try:
            assert reached.wait(5)
            if change == "bytes":
                previous = path.stat()
                path.write_bytes(b"EXTERN\n")  # same size; restored mtime is insufficient
                os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            elif change == "identity":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(data)
                os.replace(replacement, path)
            elif change == "mode":
                path.chmod(0o400)
            else:
                path.unlink()
        finally:
            resume.set()
        result = future.result(timeout=5)
    assert result[1] == "stale_content", result
    if change == "missing":
        assert not path.exists()
    else:
        assert path.read_bytes() == (b"EXTERN\n" if change == "bytes" else data)
    assert not list(tmp_path.glob(".tmp-hash-edit-*"))


def test_standalone_helper_preserves_snapshot_format_and_mode(tmp_path):
    path = tmp_path / "sample"
    data = b"\xef\xbb\xbfbefore\r\nother\n"
    path.write_bytes(data)
    mode = stat.S_IMODE(path.stat().st_mode)
    ops = [hash_edit.HashEditOp.from_dict(action(data).arguments["ops"][0])]
    result = hash_edit.apply_hash_edits_to_file(str(path), ops)
    assert result.ok, result.message
    assert path.read_bytes() == b"\xef\xbb\xbfAFTER\r\nother\n"
    assert stat.S_IMODE(path.stat().st_mode) == mode


def test_dispatch_dry_run_preserves_valid_bytes(dispatcher, tmp_path):
    path = tmp_path / "sample"
    data = b"before\r\n"
    path.write_bytes(data)
    assert dispatcher._do_hash_edit(action(data), write=False)[0]
    assert path.read_bytes() == data


@pytest.mark.parametrize("guard", ["role", "stop", "workspace", "disabled"])
def test_dispatch_preserves_refusal_guards(dispatcher, tmp_path, monkeypatch, guard):
    path = tmp_path / "sample"
    data = b"before\n"
    path.write_bytes(data)
    if guard == "role":
        dispatcher.job_role = "analysis"
    elif guard == "stop":
        calls = []

        def stopped_before_write():
            calls.append(1)
            return (False, "stopped", "stopped") if len(calls) == 2 else None

        dispatcher._refuse_quarantined_disk_mutation = stopped_before_write
    elif guard == "workspace":
        dispatcher.config.repo = str(tmp_path / "elsewhere")
    else:
        monkeypatch.delenv("HARNESS_HASH_EDIT")
    act = action(data)
    act.path = str(path)
    assert not dispatcher._do_hash_edit(act)[0]
    assert path.read_bytes() == data


@pytest.mark.parametrize("data,op,expected", [
    (b"before\r\nlast", {"op": "insert", "after_line": 2, "text": "new"},
     b"before\r\nlast\r\nnew"),
    (b"\xef\xbb\xbfbefore\n", {"op": "insert", "after_line": 0, "text": "new"},
     b"\xef\xbb\xbfnew\nbefore\n"),
    (b"before\n", {"op": "delete", "start_line": 1}, b""),
])
def test_dispatch_insert_delete_format(dispatcher, tmp_path, data, op, expected):
    path = tmp_path / "sample"
    path.write_bytes(data)
    act = action(data)
    op["anchor"] = act.arguments["ops"][0]["anchor"]
    if op["op"] == "insert" and op["after_line"] == 2:
        op.pop("anchor")
    act.arguments["ops"] = [op]
    assert dispatcher._do_hash_edit(act)[0]
    assert path.read_bytes() == expected


def test_dispatch_preserves_mixed_final_blank_line(dispatcher, tmp_path):
    path = tmp_path / "sample"
    path.write_bytes(b"before\r\n\n")
    assert dispatcher._do_hash_edit(action(path.read_bytes()))[0]
    assert path.read_bytes() == b"AFTER\r\n\n"


def test_dispatch_replace_failure_preserves_original(dispatcher, tmp_path, monkeypatch):
    path = tmp_path / "sample"
    data = b"before\n"
    path.write_bytes(data)

    def failed_replace(*args):
        raise PermissionError("replacement refused")

    monkeypatch.setattr(hash_edit.os, "replace", failed_replace)
    assert not dispatcher._do_hash_edit(action(data))[0]
    assert path.read_bytes() == data
    assert not list(tmp_path.glob(".tmp-hash-edit-*"))
