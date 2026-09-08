"""Absorb chat Completions snapshot replays into incremental text.

OpenRouter/Gemini often resend the whole message (or message+message) after
true token deltas. Cursor CLI already skips that; Completions did not.
"""

from __future__ import annotations

# Suffix-replay skip floor. One-letter incremental tails must still append.
STREAM_SNAPSHOT_MIN_CHUNK = 12


def absorb_stream_snapshot(accumulated, incoming, min_chunk=STREAM_SNAPSHOT_MIN_CHUNK):
    """Return the new suffix to append, or empty when ``incoming`` is a replay."""
    acc = accumulated or ""
    inc = incoming or ""
    if not inc:
        return ""
    if not acc:
        # Check if incoming itself is a self-duplicated string like "A\n\nA"
        parts = [p.strip() for p in inc.split("\n\n") if p.strip()]
        if len(parts) == 2 and parts[0] == parts[1]:
            return parts[0]
        return inc
    if inc == acc:
        return ""
    acc_s = acc.strip()
    inc_s = inc.strip()
    if not inc_s or acc_s == inc_s:
        return ""
    if acc.startswith(inc) or (acc_s and acc_s.startswith(inc_s)):
        return ""
    if inc.startswith(acc):
        rest = inc[len(acc):]
        if rest.strip() == acc_s or not rest.strip():
            return ""
        return rest
    if inc_s.startswith(acc_s):
        rest = inc_s[len(acc_s):].strip()
        if not rest or rest == acc_s:
            return ""
        return " " + rest if not rest.startswith(("\n", " ")) else rest
    if len(inc_s) >= min_chunk and acc_s.endswith(inc_s):
        return ""
    return inc
