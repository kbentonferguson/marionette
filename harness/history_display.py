"""Seed the visible prefix when a saved transcript predates display rows."""
from typing import Any


def display_from_history(history: list) -> list:
    """Project prose only; native calls, results and images stay in history.

    A nonempty saved display remains authoritative at the caller. This is a
    one-time hydrate migration, not a merge of two overlapping timelines.
    """
    rows = []
    for message in history:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                block if isinstance(block, str) else block["text"]
                for block in content
                if isinstance(block, str) or (
                    isinstance(block, dict) and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                )
            )
        else:
            continue
        # Match the legacy UI's suppression of synthetic user activity turns.
        if not text or (role == "user" and text.startswith("(")):
            continue
        row: dict[str, Any] = {"type": "message", "role": role, "text": text}
        if role == "assistant" and message.get("phase"):
            row["phase"] = message["phase"]
        rows.append(row)
    return rows
