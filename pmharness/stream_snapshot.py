"""Absorb chat Completions snapshot replays into incremental text.

OpenRouter/Gemini often resend the whole message (or message+message) after
true token deltas. Cursor CLI already skips that; Completions did not.

Only a cumulative snapshot is absorbed: ``incoming`` starts with the whole
``accumulated`` text. Prefix / suffix / crumb heuristics are deliberately
absent -- a later ``###`` chunk is not a replay of the opening ``###``, and a
lone ``**`` delta is half of a bold marker. Anything dropped here diverges the
streamed bubble from the final message and paints the answer twice.
"""

from __future__ import annotations

# Snapshot floor: a "snapshot" of fewer chars than this is just a short delta.
STREAM_SNAPSHOT_MIN_CHUNK = 12


def absorb_stream_snapshot(accumulated, incoming, min_chunk=STREAM_SNAPSHOT_MIN_CHUNK):
    """Return the new suffix to append, or empty when ``incoming`` is a replay."""
    acc = accumulated or ""
    inc = incoming or ""
    if not inc:
        return ""
    if not acc:
        return inc
    if inc.startswith(acc):
        rest = inc[len(acc):]
        if not rest.strip():
            # Exact replay. Short acc is a repeated character ("#" + "#"),
            # not a Completions snapshot.
            return "" if len(acc) >= min_chunk else inc
        if len(acc) >= min_chunk and rest.strip() == acc.strip():
            return ""
        return rest
    if len(acc) >= min_chunk and inc.strip() == acc.strip():
        return ""
    return inc
