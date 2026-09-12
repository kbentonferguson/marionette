from __future__ import annotations

"""Shared CodeGraph auto-inject wrap for the chat turn.

Keyed off working context (user ask plus files already touched this turn),
not the raw user message alone. Softens Puppetmaster's "authoritative
starting points" line so a thin or stale slice cannot be treated as
verbatim on-disk text.
"""

from typing import Any

_PM_AUTHORITATIVE = (
    "Use these symbols and files as authoritative starting points. "
    "Confirm with the live repo before relying on them, but do not "
    "re-scan the whole codebase if CodeGraph already located the "
    "relevant area."
)

_WRAP = (
    "CODEGRAPH HAS ALREADY BEEN QUERIED FOR THIS TASK. "
    "These are ranked starting points from the current working context "
    "(user ask plus files already touched this turn), not a verbatim "
    "on-disk guarantee. Confirm against the live tree. Prefer "
    "search_codegraph or a ranged read_file if a snippet looks stale.\n"
)


def working_query(session: Any, user_message: str) -> str:
    parts = [str(user_message or "").strip()]
    tx = getattr(session, "_task_tx", None)
    files = list(getattr(tx, "files", None) or [])[:12]
    if files:
        parts.append("Working files: " + " ".join(str(p) for p in files if str(p).strip()))
    return "\n".join(p for p in parts if p)


def wrap_slice(cg_slice: str) -> tuple[str, int]:
    text = str(cg_slice or "")
    if not text.strip():
        return "", 0
    symbols = text.count("- **") + text.count("#### ")
    try:
        from puppetmaster.codegraph import codegraph_prompt_section

        section = codegraph_prompt_section(text)
    except Exception:
        section = text
    section = section.replace(
        _PM_AUTHORITATIVE,
        "Treat these as ranked starting points, not a verbatim on-disk guarantee.",
    )
    return _WRAP + section, symbols
