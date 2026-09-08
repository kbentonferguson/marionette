"""Bounded, no-write reads of a caller-selected Marionette savings ledger."""
from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path

DB_FILENAME = 'tool_output_savings.sqlite'
MAX_ROWS = 50
MAX_STEPS = 50000
MAX_SECONDS = 0.05


def read_selected_compaction(source_root, *, session_id, job_id, created_at,
                             limit=MAX_ROWS, max_steps=MAX_STEPS,
                             timeout=MAX_SECONDS):
    """Return coverage, reason and at most 50 allowlisted economics records.

    created_at is the selected job incarnation's Unix timestamp (seconds).
    The caller must fence the known source and selected job before/after this
    read. No source discovery, PM database access, migrations or price guessing.
    Active SQLite sidecars are unsupported: immutable reads cannot see WAL and
    ordinary read-only connections can create shared-memory files.
    """
    if not isinstance(session_id, str) or not session_id or not isinstance(job_id, str) or not job_id:
        raise ValueError('exact session and job identities required')
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)) or not math.isfinite(created_at) or created_at < 0:
        raise ValueError('finite job creation Unix timestamp required')
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError('row budget must be between 1 and 50')
    if type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS:
        raise ValueError('invalid SQL instruction budget')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= MAX_SECONDS:
        raise ValueError('invalid time budget')

    def result(coverage, reason, records=()):
        return dict(coverage=coverage, reason=reason, records=list(records))

    path = Path(source_root).absolute() / DB_FILENAME
    sidecars = [Path(str(path) + suffix) for suffix in ('-wal', '-shm', '-journal')]

    def signature():
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    connection = None
    rows = []
    start = time.monotonic()
    steps = 0
    exhausted = False

    def progress():
        nonlocal steps, exhausted
        steps += 1
        exhausted = steps >= max_steps or time.monotonic() - start >= timeout
        return int(exhausted)

    try:
        if not path.is_file():
            reason = 'jsonl_unsupported' if (path.parent / 'tool_output_savings.jsonl').is_file() else 'source_absent'
            return result('unavailable', reason)
        if any(p.exists() for p in sidecars):
            return result('unavailable', 'active_sqlite_sidecar_unsupported')
        before = signature()
        connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0)
        connection.set_progress_handler(progress, 1)
        # INDEXED BY fails closed on legacy schemas without the session index.
        # The VM budget bounds even a huge session with no matching job.
        cursor = connection.execute('''
            SELECT ts, session_id, job_id, tool_call_id, original_chars, compact_chars
            FROM tool_output_savings INDEXED BY idx_tool_output_savings_session
            WHERE session_id = ? AND job_id = ? AND ts >= ? LIMIT ?
        ''', (session_id, job_id, created_at, limit + 1))
        invalid = False
        clipped = False
        for row in cursor:
            if len(rows) >= limit:
                clipped = True
                break
            ts, sid, jid, call, original, compact = row
            if (not isinstance(ts, (int, float)) or not math.isfinite(ts)
                    or ts < created_at or sid != session_id or jid != job_id
                    or not isinstance(call, str) or not call or len(call) > 1024
                    or type(original) is not int or original < 0
                    or type(compact) is not int or compact < 0):
                invalid = True
                continue
            rows.append(dict(ts=ts, session_id=sid, job_id=jid, tool_call_id=call,
                             original_chars=original, compact_chars=compact))
        if signature() != before or any(p.exists() for p in sidecars):
            return result('unavailable', 'source_changed')
        if time.monotonic() - start >= timeout:
            return result('partial', 'time_budget', rows)
        if clipped or invalid:
            return result('partial', 'row_cap' if clipped else 'invalid_records', rows)
        return result('complete', 'exact_sqlite_selection', rows)
    except sqlite3.Error:
        return result('partial' if exhausted else 'unavailable',
                      'scan_or_time_budget' if exhausted else 'sqlite_unsupported_or_unreadable', rows)
    except OSError:
        return result('unavailable', 'source_unreadable')
    finally:
        if connection is not None:
            connection.close()
