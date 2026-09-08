import sqlite3

import pytest

from harness.job_expert_compaction import read_selected_compaction
from harness.tool_output_savings import _SCHEMA, DB_FILENAME


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def ledger(root, rows=(), schema=_SCHEMA):
    with sqlite3.connect(root / DB_FILENAME) as db:
        db.executescript(schema)
        if rows:
            db.executemany('INSERT INTO tool_output_savings (ts,session_id,job_id,tool_call_id,original_chars,compact_chars,tokens_saved) VALUES (?,?,?,?,?,?,?)', rows)


def read(root, **kwargs):
    return read_selected_compaction(root, session_id='s', job_id='j', created_at=100.5, **kwargs)


def test_missing_and_jsonl_no_write(tmp_path):
    for root in (tmp_path, tmp_path / 'missing'):
        before = snapshot(tmp_path)
        assert read(root)['coverage'] == 'unavailable'
        assert snapshot(tmp_path) == before
    (tmp_path / 'tool_output_savings.jsonl').write_text('{}\n')
    before = snapshot(tmp_path)
    assert read(tmp_path)['reason'] == 'jsonl_unsupported'
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('schema', [
    'CREATE TABLE tool_output_savings (ts REAL)',
    _SCHEMA.replace('    job_id TEXT,', ''),
    _SCHEMA.split('CREATE INDEX')[0],
])
def test_legacy_no_write(tmp_path, schema):
    ledger(tmp_path, schema=schema)
    before = snapshot(tmp_path)
    assert read(tmp_path)['coverage'] == 'unavailable'
    assert snapshot(tmp_path) == before


def test_exact_incarnation_allowlist(tmp_path):
    ledger(tmp_path, [(101, 'foreign', 'j', 'a', 400, 4, 99),
                      (101, 's', 'foreign', 'b', 400, 4, 99),
                      (100.4, 's', 'j', 'old', 400, 4, 99),
                      (100.5, 's', 'j', 'new', 400, 40, 90)])
    before = snapshot(tmp_path)
    selected = read(tmp_path)
    assert selected['coverage'] == 'complete'
    assert selected['records'] == [dict(ts=100.5, session_id='s', job_id='j', tool_call_id='new', original_chars=400, compact_chars=40)]
    assert snapshot(tmp_path) == before


def test_complete_zero_and_positive(tmp_path):
    ledger(tmp_path)
    assert read(tmp_path) == dict(coverage='complete', reason='exact_sqlite_selection', records=[])
    with sqlite3.connect(tmp_path / DB_FILENAME) as db:
        db.execute("INSERT INTO tool_output_savings (ts,session_id,job_id,tool_call_id,original_chars,compact_chars,tokens_saved) VALUES (101,'s','j','zero',4,4,0)")
    assert read(tmp_path)['records'][0]['original_chars'] == 4


def test_row_cap_and_instruction_timeout_no_write(tmp_path):
    ledger(tmp_path, [(101, 's', 'j', str(i), 400, 40, 90) for i in range(60)])
    before = snapshot(tmp_path)
    selected = read(tmp_path)
    assert selected['coverage'] == 'partial'
    assert selected['reason'] == 'row_cap'
    assert len(selected['records']) == 50
    assert read(tmp_path, max_steps=1)['coverage'] == 'partial'
    assert read(tmp_path, timeout=1e-12)['coverage'] == 'partial'
    assert snapshot(tmp_path) == before


def test_foreign_job_scan_is_bounded(tmp_path):
    ledger(tmp_path, [(101, 's', 'other', str(i), 400, 40, 90) for i in range(2000)])
    assert read(tmp_path, max_steps=100)['coverage'] == 'partial'


def test_active_wal_no_write(tmp_path):
    db = sqlite3.connect(tmp_path / DB_FILENAME)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(_SCHEMA)
        before = snapshot(tmp_path)
        assert read(tmp_path)['reason'] == 'active_sqlite_sidecar_unsupported'
        assert snapshot(tmp_path) == before
    finally:
        db.close()


@pytest.mark.parametrize('kwargs', [dict(limit=51), dict(max_steps=0), dict(timeout=float('nan'))])
def test_invalid_budgets(tmp_path, kwargs):
    with pytest.raises(ValueError):
        read(tmp_path, **kwargs)
