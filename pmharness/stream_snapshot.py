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
        return inc
    if inc == acc:
        return ""
    if acc.startswith(inc):
        return ""
    if inc.startswith(acc):
        rest = inc[len(acc):]
        if rest.strip() == acc.strip():
            return ""
        return rest
    if len(inc) >= min_chunk and acc.endswith(inc):
        return ""
    return inc
