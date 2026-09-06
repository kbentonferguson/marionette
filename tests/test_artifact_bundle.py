import hashlib
import json
from pathlib import Path

import pytest

from puppetmaster.models import JobRef

from harness.artifact_bundle import BundleError, export_bundle, import_bundle


REF = JobRef(job_id='job-1', state_id='state-1')


def test_roundtrip_independent_digest(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'hello\x00world' * 100000)
    bundle = tmp_path / 'bundle'
    manifest = export_bundle(REF, {'nested/file.bin': source}, {'art-1': {'id': 'art-1'}}, bundle, session_id='session-1')
    assert manifest['snapshot']['status'] == 'partial'
    assert manifest['schema_version'] == 2
    for entry in manifest['entries']:
        data = (bundle / 'objects' / entry['sha256']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        assert len(data) == entry['size']
    output = tmp_path / 'output'
    import_bundle(bundle, output, REF, session_id='session-1')
    assert (output / 'files/nested/file.bin').read_bytes() == source.read_bytes()
    assert json.loads((output / 'artifacts/art-1.json').read_text()) == {'id': 'art-1'}


def test_corruption_never_publishes(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'original')
    bundle = tmp_path / 'bundle'
    manifest = export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    (bundle / 'objects' / manifest['entries'][0]['sha256']).write_bytes(b'corrupt!')
    with pytest.raises(BundleError):
        import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    assert not (tmp_path / 'out').exists()


def test_export_interruption_resumes_verified_objects(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    source = tmp_path / 'source'
    source.write_bytes(b'first')
    bundle = tmp_path / 'bundle'
    original = module._publish_manifest
    monkeypatch.setattr(module, '_publish_manifest', lambda *a: (_ for _ in ()).throw(InterruptedError()))
    with pytest.raises(InterruptedError):
        export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    objects = list((bundle / 'objects').iterdir())
    before = objects[0].stat().st_mtime_ns
    monkeypatch.setattr(module, '_publish_manifest', original)
    export_bundle(REF, {'f': source}, {}, bundle, resume=True, session_id='session-1')
    assert objects[0].stat().st_mtime_ns == before
    import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')


def test_source_mutation_prevents_commit(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'before')
    def mutate():
        source.write_bytes(b'after!')
    with pytest.raises(BundleError, match='source changed'):
        export_bundle(REF, {'f': source}, {}, tmp_path / 'bundle', validate_source=mutate, session_id='session-1')
    assert not (tmp_path / 'bundle/manifest.json').exists()


@pytest.mark.parametrize('attack', ['../escape', '/absolute', 'a/../../escape', 'a\\b', 'C:/evil', 'a//b', 'CON', 'a.'])
def test_reject_source_paths(tmp_path, attack):
    source = tmp_path / 'source'
    source.write_text('safe')
    with pytest.raises(BundleError):
        export_bundle(REF, {attack: source}, {}, tmp_path / 'bundle', session_id='session-1')


def test_reject_manifest_traversal_symlink_and_existing_destination(tmp_path):
    source = tmp_path / 'source'
    source.write_text('safe')
    bundle = tmp_path / 'bundle'
    manifest = export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'unrelated').write_text('retain')
    with pytest.raises((BundleError, FileExistsError)):
        import_bundle(bundle, output, REF, session_id='session-1')
    assert (output / 'unrelated').read_text() == 'retain'
    manifest['entries'][0]['path'] = '../escape'
    (bundle / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    assert not (tmp_path / 'escape').exists()
    link = tmp_path / 'link'
    link.symlink_to(source)
    with pytest.raises(BundleError):
        export_bundle(REF, {'f': link}, {}, tmp_path / 'other', session_id='session-1')


def test_resume_rejects_corrupt_object_and_changed_source(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    source = tmp_path / 'source'
    source.write_bytes(b'original')
    bundle = tmp_path / 'bundle'
    monkeypatch.setattr(module, '_publish_manifest', lambda *a: (_ for _ in ()).throw(InterruptedError()))
    with pytest.raises(InterruptedError):
        export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    obj = next((bundle / 'objects').iterdir())
    obj.write_bytes(b'changed!')
    with pytest.raises(BundleError, match='corrupt resumed'):
        export_bundle(REF, {'f': source}, {}, bundle, resume=True, session_id='session-1')
    source.write_bytes(b'new source')
    with pytest.raises(BundleError, match='source changed'):
        export_bundle(REF, {'f': source}, {}, bundle, resume=True, session_id='session-1')


def test_symlink_object_and_destination_ancestor(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'hello')
    bundle = tmp_path / 'bundle'
    manifest = export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    obj = bundle / 'objects' / manifest['entries'][0]['sha256']
    obj.unlink()
    obj.symlink_to(source)
    with pytest.raises(BundleError, match='symlink'):
        import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    directory = tmp_path / 'directory'
    directory.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(BundleError, match='symlink'):
        export_bundle(REF, {'f': source}, {}, link / 'export', session_id='session-1')
    assert not (directory / 'export').exists()


def test_limits_duplicates_and_foreign_job(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    source = tmp_path / 'source'
    source.write_bytes(b'hello')
    with pytest.raises(BundleError, match='overlapping'):
        export_bundle(REF, {'X': source, 'x': source}, {}, tmp_path / 'bad', session_id='session-1')
    bundle = tmp_path / 'bundle'
    export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    with pytest.raises(BundleError, match='JobRef'):
        import_bundle(bundle, tmp_path / 'out', JobRef(job_id='other', state_id='state-1'), session_id='session-1')
    monkeypatch.setattr(module, 'MAX_FILE', 4)
    with pytest.raises(BundleError, match='byte limit'):
        export_bundle(REF, {'f': source}, {}, tmp_path / 'large', session_id='session-1')


def test_import_interruption_before_publication_restarts(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    source = tmp_path / 'source'
    source.write_bytes(b'hello' * 500000)
    bundle = tmp_path / 'bundle'
    export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    original = module._stream
    def interrupt(path, output=None, **kwargs):
        if output is not None:
            output.write(b'interrupted')
            raise InterruptedError()
        return original(path, output, **kwargs)
    monkeypatch.setattr(module, '_stream', interrupt)
    with pytest.raises(InterruptedError):
        import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    assert not (tmp_path / 'out').exists()
    monkeypatch.setattr(module, '_stream', original)
    import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    assert (tmp_path / 'out/files/f').read_bytes() == source.read_bytes()


def test_mutation_during_stream_detected(tmp_path):
    from harness.artifact_bundle import _stream
    source = tmp_path / 'source'
    source.write_bytes(b'a' * 2000000)
    class MutatingOutput:
        def write(self, block):
            source.write_bytes(b'b' * 2000000)
    with pytest.raises(BundleError, match='source changed'):
        _stream(source, MutatingOutput())


def test_interrupted_second_object_resumes_first(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.write_bytes(b'first complete')
    second.write_bytes(b'second unfinished' * 200000)
    original = module._stream
    def interrupt(path, output=None, **kwargs):
        if path == second and output is not None:
            output.write(b'partial')
            raise InterruptedError()
        return original(path, output, **kwargs)
    monkeypatch.setattr(module, '_stream', interrupt)
    bundle = tmp_path / 'bundle'
    with pytest.raises(InterruptedError):
        export_bundle(REF, {'first': first, 'second': second}, {}, bundle, session_id='session-1')
    objects = list((bundle / 'objects').iterdir())
    assert len(objects) == 1
    prior = objects[0].stat().st_mtime_ns
    monkeypatch.setattr(module, '_stream', original)
    export_bundle(REF, {'first': first, 'second': second}, {}, bundle, resume=True, session_id='session-1')
    assert objects[0].stat().st_mtime_ns == prior
    import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    assert (tmp_path / 'out/files/second').read_bytes() == second.read_bytes()


def test_manifest_size_and_declared_size_bounds(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    source = tmp_path / 'source'
    source.write_bytes(b'hello world')
    bundle = tmp_path / 'bundle'
    manifest = export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    manifest['entries'][0]['size'] = 1
    (bundle / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(BundleError, match='declared byte limit'):
        import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')
    assert not (tmp_path / 'out').exists()
    monkeypatch.setattr(module, 'MAX_MANIFEST', 10)
    with pytest.raises(BundleError, match='manifest exceeds'):
        import_bundle(bundle, tmp_path / 'out', REF, session_id='session-1')


def test_no_disk_space_fails_before_payload_write(tmp_path, monkeypatch):
    import harness.artifact_bundle as module
    from collections import namedtuple
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: usage(1, 1, 0))
    source = tmp_path / 'source'
    source.write_bytes(b'hello')
    with pytest.raises(BundleError, match='disk space'):
        export_bundle(REF, {'f': source}, {}, tmp_path / 'bundle', session_id='session-1')
    assert not list((tmp_path / 'bundle/objects').iterdir())


@pytest.mark.parametrize('change, message', [
    ({'schema_version': 1}, 'unsupported manifest schema'),
    ({'schema_version': True}, 'unsupported manifest schema'),
    ({'job_ref': {'job_id': REF.job_id, 'session_id': 'session-1'}}, 'JobRef mismatch'),
    ({'job_ref': {'job_id': REF.job_id, 'state_id': 'other-state'}}, 'JobRef mismatch'),
    ({'session_id': 'other-session'}, 'session scope mismatch'),
])
def test_manifest_requires_origin_identity_and_separate_scope(tmp_path, change, message):
    source = tmp_path / 'source'
    source.write_bytes(b'bytes')
    bundle = tmp_path / 'bundle'
    manifest = export_bundle(REF, {'f': source}, {}, bundle, session_id='session-1')
    manifest.update(change)
    (bundle / 'manifest.json').write_text(json.dumps(manifest))
    output = tmp_path / 'out'
    with pytest.raises(BundleError, match=message):
        import_bundle(bundle, output, REF, session_id='session-1')
    assert not output.exists()
