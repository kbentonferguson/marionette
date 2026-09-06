"""Native input originals: scale, integrity, publication and cold restoration."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.input_receipts import InputReceiptError, InputReceiptStore

# Rerun the size/poll regression against the captured dirty baseline.
if os.environ.get('INPUT_STORAGE_BASELINE'):
    spec = importlib.util.spec_from_file_location('harness._input_baseline', os.environ['INPUT_STORAGE_BASELINE'])
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    InputReceiptStore = baseline.InputReceiptStore


def upload(tmp_path, raw=b'original\x00bytes\n'):
    directory = tmp_path / 'uploads'; directory.mkdir(exist_ok=True)
    path = directory / 'original.bin'; path.write_bytes(raw)
    return path


def admit(store, path, text=' exact text\n', **kwargs):
    return store.admit(text, documents=[str(path)], upload_root=str(path.parent), **kwargs)


@pytest.mark.parametrize('distinct', [False, True])
def test_scale_metadata_polling(tmp_path, monkeypatch, distinct):
    store = InputReceiptStore(str(tmp_path), 'scale')
    for i in range(40):
        path = upload(tmp_path, bytes([i if distinct else 0]) * 524288)
        admit(store, path, str(i))
    native_bytes = sum(p.stat().st_size for p in store.path.parent.rglob('*') if p.is_file())
    unique_bytes = 524288 * (40 if distinct else 1)
    assert native_bytes < unique_bytes + 100000
    def no_bytes(*args, **kwargs):
        pytest.fail('metadata polling touched attachment bytes')
    monkeypatch.setattr(store, '_blob_bytes', no_bytes)
    monkeypatch.setattr(base64, 'b64decode', no_bytes)
    rows = store.list()
    assert len(rows) == 40
    assert store.get(rows[0]['id'])['original_text'] == '0'


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_blob_damage_is_local_and_reuse_fails(tmp_path, damage):
    store = InputReceiptStore(str(tmp_path), 'scale'); path = upload(tmp_path)
    row = admit(store, path, retry_key='retry')
    item = row['attachments'][0]; blob = store.blob_dir / item['sha256']
    if damage == 'missing':
        blob.unlink()
    else:
        blob.write_bytes(b'changed')
    before = store.path.read_bytes()
    assert store.list()[0]['original_text'] == row['original_text']
    for action in [lambda: store.attachment(item['ref']), lambda: store.materialize(item['ref']),
                   store.snapshot, lambda: admit(store, path, retry_key='retry'),
                   lambda: store.admit('reuse', documents=[item['ref']])]:
        with pytest.raises(InputReceiptError):
            action()
    assert store.path.read_bytes() == before


def test_identity_legacy_import_and_renaming(tmp_path):
    from harness.compaction_archive import _atomic_write_json
    store = InputReceiptStore(str(tmp_path), 'scale'); path = upload(tmp_path)
    row = admit(store, path, retry_key='retry')
    snapshot = store.snapshot()
    legacy = {'version': 1, 'session_id': 'scale', 'inputs': snapshot['inputs']}
    for r in legacy['inputs']:
        r.pop('metadata_digest')
        for item in r['attachments']:
            item['base64'] = snapshot['blobs'][item['sha256']]
    _atomic_write_json(str(store.path), legacy)
    assert store.get(row['id'])['payload_digest'] == row['payload_digest']
    assert json.loads(store.path.read_text())['version'] == 2
    assert admit(store, path, retry_key='retry')['id'] == row['id']
    assert admit(store, path)['id'] != row['id']
    renamed = store.admit(row['original_text'], documents=[{'ref': row['attachments'][0]['ref'], 'name': 'new.bin'}])
    assert renamed['payload_digest'] != row['payload_digest']
    assert len(list(store.blob_dir.iterdir())) == 1
    with pytest.raises(InputReceiptError):
        store.admit(row['original_text'], documents=[{'ref': row['attachments'][0]['ref'], 'name': 'new.bin'}], retry_key='retry')


@pytest.mark.parametrize('fault', ['blob_before', 'blob_after', 'manifest_before', 'manifest_after'])
def test_publication_faults_preserve_prior_receipts(tmp_path, monkeypatch, fault):
    store = InputReceiptStore(str(tmp_path), 'scale'); old = store.admit('old')
    path = upload(tmp_path)
    original = os.replace
    def replace(source, target):
        target = Path(target)
        selected = target == store.path if fault.startswith('manifest') else target.parent == store.blob_dir
        if selected:
            if fault.endswith('after'):
                original(source, target)
            raise OSError('injected publication fault')
        return original(source, target)
    monkeypatch.setattr(os, 'replace', replace)
    with pytest.raises(InputReceiptError):
        admit(store, path)
    rows = store.list()
    assert rows[0]['id'] == old['id']
    assert all(r['status'] == 'accepted' for r in rows)
    assert not any('.queue' in p.name for p in store.path.parent.iterdir())
    if fault != 'manifest_after':
        assert len(rows) == 1
    else:
        assert len(rows) == 2
        assert InputReceiptStore(str(tmp_path), 'scale').list()[1]['held']


def test_limits_and_outside_refs_preserve_state(tmp_path, monkeypatch):
    import harness.input_receipts as module
    store = InputReceiptStore(str(tmp_path), 'scale'); store.admit('old')
    before = store.path.read_bytes(); path = upload(tmp_path)
    outside = tmp_path / 'secret'; outside.write_bytes(b'secret')
    link = path.parent / 'link'; link.symlink_to(outside)
    for args in [dict(images=[str(path)]*9), dict(documents=[str(path)]*33),
                 dict(documents=[str(outside)]), dict(documents=[str(link)]),
                 dict(documents=['input:other:'+'a'*64])]:
        with pytest.raises(InputReceiptError):
            store.admit('draft', upload_root=str(path.parent), **args)
    monkeypatch.setattr(module, '_MAX_INPUT_BYTES', 3)
    with pytest.raises(InputReceiptError):
        admit(store, path)
    monkeypatch.setattr(module, '_MAX_FILE_BYTES', 3)
    with pytest.raises(InputReceiptError):
        admit(store, path)
    assert store.path.read_bytes() == before


def test_archive_bundle_restores_unique_originals_and_never_replays(tmp_path):
    from harness import chat_archive
    from harness.sessions import save_transcript, load_transcript
    store = InputReceiptStore(str(tmp_path), 'scale'); path = upload(tmp_path)
    for i in range(5):
        admit(store, path, str(i))
    raw = {'history': [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'x', 'thought_signature': 'opaque', 'function': {'name': 'x', 'arguments': '{}'}}]}, {'role': 'tool', 'tool_call_id': 'x', 'content': 'exact'}]}
    save_transcript(str(tmp_path), 'scale', raw)
    catalog = [{'id': 'scale', 'archived': True}]
    assert chat_archive.ingest_all(str(tmp_path), sessions=catalog)['ingested'] == 1
    bundle = chat_archive._verified_raw(str(tmp_path), 'marionette:scale')
    assert len(bundle['inputs']['blobs']) == 1
    assert all('base64' not in a for r in bundle['inputs']['inputs'] for a in r['attachments'])
    assert chat_archive.prune_ingested_transcripts(str(tmp_path), catalog)['pruned'] == 1
    path.unlink(); store.path.unlink(); shutil.rmtree(store.blob_dir)
    assert chat_archive.restore_pruned_transcript(str(tmp_path), 'scale')
    cold = InputReceiptStore(str(tmp_path), 'scale')
    assert load_transcript(str(tmp_path), 'scale') == raw
    assert all(r['held'] for r in cold.list())
    for row in cold.list():
        assert cold.attachment(row['attachments'][0]['ref']) == b'original\x00bytes\n'
        with pytest.raises(InputReceiptError):
            cold.prepare_delivery(row['id'])


def test_restore_conflict_and_interruption(tmp_path, monkeypatch):
    source = InputReceiptStore(str(tmp_path/'source'), 'scale'); path = upload(tmp_path)
    row = admit(source, path); snapshot = source.snapshot()
    target = InputReceiptStore(str(tmp_path/'target'), 'scale')
    original = target._write
    def fail(document):
        raise OSError('manifest interrupted')
    monkeypatch.setattr(target, '_write', fail)
    with pytest.raises(InputReceiptError):
        target.restore(snapshot)
    assert not target.path.exists()
    monkeypatch.setattr(target, '_write', original)
    target.restore(snapshot)
    blob = target.blob_dir / row['attachments'][0]['sha256']; blob.write_bytes(b'conflict')
    before = target.path.read_bytes()
    with pytest.raises(InputReceiptError):
        target.restore(snapshot)
    assert blob.read_bytes() == b'conflict'
    assert target.path.read_bytes() == before


def test_two_independent_process_writers(tmp_path):
    path = upload(tmp_path)
    script = """import sys; sys.path.insert(0, sys.argv[1]); from harness.input_receipts import InputReceiptStore
store = InputReceiptStore(sys.argv[2], 'scale')
for i in range(10): store.admit(sys.argv[4]+str(i), documents=[sys.argv[3]], upload_root=str(__import__('pathlib').Path(sys.argv[3]).parent))
"""
    args = [sys.executable, '-I', '-c', script, str(Path(__file__).resolve().parents[1]), str(tmp_path), str(path)]
    processes = [subprocess.Popen(args+[str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
    for process in processes:
        out, err = process.communicate(timeout=60)
        assert process.returncode == 0, err.decode()
    store = InputReceiptStore(str(tmp_path), 'scale')
    assert len(store.list()) == 20
    assert len(list(store.blob_dir.iterdir())) == 1


def test_stream_reads_are_bounded_and_detect_growth():
    import io
    import harness.input_receipts as module
    class Bounded(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 65536
            return super().read(size)
    raw = b'x' * module._MAX_FILE_BYTES
    assert InputReceiptStore._bounded_read(Bounded(raw)) == raw
    with pytest.raises(InputReceiptError):
        InputReceiptStore._bounded_read(Bounded(raw+b'x'))


def test_corrupt_transport_publishes_nothing(tmp_path):
    source = InputReceiptStore(str(tmp_path/'source'), 'scale'); path = upload(tmp_path)
    row = admit(source, path); snapshot = source.snapshot()
    snapshot['blobs'][row['attachments'][0]['sha256']] = base64.b64encode(b'wrong').decode()
    target = InputReceiptStore(str(tmp_path/'target'), 'scale')
    with pytest.raises(InputReceiptError):
        target.restore(snapshot)
    assert not target.path.exists()
    assert not target.blob_dir.exists()


def test_manifest_corruption_never_rewritten(tmp_path):
    store = InputReceiptStore(str(tmp_path), 'scale'); path = upload(tmp_path)
    admit(store, path)
    document = json.loads(store.path.read_text())
    document['inputs'][0]['original_text'] = 'tampered'
    store.path.write_text(json.dumps(document))
    before = store.path.read_bytes()
    with pytest.raises(InputReceiptError):
        store.list()
    with pytest.raises(InputReceiptError):
        admit(store, path)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('fail', [False, True])
def test_retirement_generation_changes_under_owner_transaction(tmp_path, monkeypatch, fail):
    from contextlib import contextmanager
    store = InputReceiptStore(str(tmp_path), 'scale'); row = store.admit('follow up')
    old = store.instance; transaction = store.transaction
    @contextmanager
    def observed():
        with transaction():
            try:
                yield
            finally:
                assert store.instance != old, 'generation changed after releasing owner transaction'
    monkeypatch.setattr(store, 'transaction', observed)
    if fail:
        def fail_write(document):
            raise InputReceiptError('test_fault', 'write failed')
        monkeypatch.setattr(store, '_write', fail_write)
        with pytest.raises(InputReceiptError):
            store.retire_after_stop(row['id'])
    else:
        store.retire_after_stop(row['id'])


def test_poll_does_not_decode_historical_bytes(tmp_path, monkeypatch):
    store = InputReceiptStore(str(tmp_path), 'scale'); path = upload(tmp_path, b'x'*524288)
    row = admit(store, path)
    def no_decode(*args, **kwargs):
        pytest.fail('poll decoded historical attachment bytes')
    monkeypatch.setattr(base64, 'b64decode', no_decode)
    assert store.list()[0]['id'] == row['id']
