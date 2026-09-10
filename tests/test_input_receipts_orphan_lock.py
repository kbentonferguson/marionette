"""Orphan .inputs.json.lock heal: bootstrap empty locks; reset R-marker when unrestorable."""

import json

import pytest

from harness.input_receipts import InputReceiptError, InputReceiptStore


def test_empty_orphan_lock_bootstraps_when_inputs_json_missing(tmp_path):
    store = InputReceiptStore(str(tmp_path), 'session')
    lock = store.path.with_suffix(store.path.suffix + '.lock')
    # Simulate a crashed first write: lock exists empty, no inputs.json.
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b'')
    assert not store.path.exists()
    assert store.list() == []
    receipt = store.admit('fresh after heal')
    assert receipt['original_text'] == 'fresh after heal'
    assert store.path.exists()
    assert lock.read_bytes().startswith(b'R')


def test_zero_byte_marker_bootstraps_like_empty_lock(tmp_path):
    store = InputReceiptStore(str(tmp_path), 'session')
    lock = store.path.with_suffix(store.path.suffix + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b'0')
    assert store.list() == []
    store.admit('ok')
    assert json.loads(store.path.read_text())['inputs'][0]['original_text'] == 'ok'


def test_r_marker_without_archive_resets_lock_and_raises_document_missing(tmp_path, monkeypatch):
    store = InputReceiptStore(str(tmp_path), 'session')
    lock = store.path.with_suffix(store.path.suffix + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    # Non-empty R-marker claims a prior commit, but inputs.json and archive are gone.
    lock.write_bytes(b'R' + b'a' * 64)

    def no_archive(root, key):
        return None

    monkeypatch.setattr('harness.chat_archive._verified_raw', no_archive)

    with pytest.raises(InputReceiptError) as excinfo:
        store.list()
    assert excinfo.value.code == 'input_document_missing'
    # Lock healed to bootstrap-ready marker so a later admit is not stuck.
    assert lock.read_bytes() in (b'0', b'')
    assert not store.path.exists()
    # After heal, a fresh admit can proceed.
    receipt = store.admit('recovered path')
    assert receipt['original_text'] == 'recovered path'
