"""Exact native image retention with real journal, archive and cold restore."""
import base64
import copy
import hashlib
import json

import pytest

from harness.compaction_archive import load_compaction_archive_page
from harness.context_budget import serialized_history_bytes
from harness.sessions import load_transcript
from test_turn_compaction_ownership import fat_session

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def image_row(label):
    return {'role': 'user', 'content': [
        {'type': 'text', 'text': label},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(PNG).decode()}}],
        'opaque': {'signature': label}}


def setup_session(tmp_path, monkeypatch):
    s = fat_session(tmp_path, monkeypatch)
    monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'catalog')
    s._history.insert(3, image_row('old'))
    s._history.append(image_row('latest'))
    return s


def originals(s):
    rows, _ = load_compaction_archive_page(s.state_dir, 'default', limit=400)
    found = list(rows)
    for row in rows:
        found.extend(row.get('_image_aging_projection', {}).get('rows', []))
    return found


@pytest.mark.parametrize('emergency', [False, True])
def test_success_retains_exact_images(tmp_path, monkeypatch, emergency):
    s = setup_session(tmp_path, monkeypatch)
    before = copy.deepcopy(s._history)
    events = list(s._maybe_compact_history(force=True, emergency=emergency))
    assert not events[-1].data.get('aborted'), events[-1].data
    assert image_row('old') in originals(s)
    assert image_row('latest') in s._history
    assert serialized_history_bytes(s._history) < serialized_history_bytes(before)
    assert load_transcript(s.state_dir, 'default')['history'] == s._history[1:]


@pytest.mark.parametrize('gate', ['off', 'no_split', 'threshold', 'rejected'])
def test_emergency_early_returns_preserve_and_save_bytes(tmp_path, monkeypatch, gate):
    s = setup_session(tmp_path, monkeypatch)
    if gate == 'off': monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'off')
    if gate == 'no_split': monkeypatch.setattr(s, '_choose_compaction_split', lambda **kw: None)
    if gate == 'threshold': monkeypatch.setattr(s, '_estimate_context_tokens', lambda: 0)
    if gate == 'rejected':
        monkeypatch.setattr(s, '_make_catalog_residual', lambda *a, **kw: '')
        monkeypatch.setattr(s, '_make_fallback_summary', lambda *a, **kw: '')
    before = copy.deepcopy(s._history)
    list(s._maybe_compact_history(force=gate != 'threshold', emergency=True))
    assert image_row('old') in originals(s)
    assert image_row('latest') in s._history
    assert serialized_history_bytes(s._history) < serialized_history_bytes(before)
    assert load_transcript(s.state_dir, 'default')['history'] == s._history[1:]
    rows = originals(s)
    list(s._maybe_compact_history(force=gate != 'threshold', emergency=True))
    assert originals(s) == rows


@pytest.mark.parametrize('emergency', [False, True])
@pytest.mark.parametrize('boundary', ['archive_before', 'archive_after', 'transcript_before', 'transcript_after'])
def test_failure_boundaries_never_lose_only_originals(tmp_path, monkeypatch, emergency, boundary):
    from harness import compaction_archive as ca, sessions
    s = setup_session(tmp_path, monkeypatch)
    before = copy.deepcopy(s._history)
    if boundary.startswith('archive'):
        real = ca.append_compaction_archive
        def fail(*args, **kwargs):
            if boundary.endswith('after'): real(*args, **kwargs)
            raise OSError('injected archive failure')
        monkeypatch.setattr(ca, 'append_compaction_archive', fail)
    else:
        real = sessions._write_transcript
        count = 0
        def fail(*args, **kwargs):
            nonlocal count
            count += 1
            if count > 1: return real(*args, **kwargs)
            if boundary.endswith('after'): real(*args, **kwargs)
            raise OSError('injected transcript failure')
        monkeypatch.setattr(sessions, '_write_transcript', fail)
    list(s._maybe_compact_history(force=True, emergency=emergency))
    cold = load_transcript(s.state_dir, 'default')
    assert image_row('old') in originals(s) + s._history
    assert image_row('old') in originals(s) + cold['history']
    if boundary != 'transcript_after': assert s._history == before


@pytest.mark.parametrize('emergency', [False, True])
def test_stale_source_replacement_does_not_publish(tmp_path, monkeypatch, emergency):
    s = setup_session(tmp_path, monkeypatch)
    run = s._maybe_compact_history(force=True, emergency=emergency)
    assert next(run).kind == 'compacting'
    s._history[4]['content'] = 'replacement same length history'
    changed = copy.deepcopy(s._history)
    events = list(run)
    assert s._history == changed
    assert events[-1].data['reason'] == 'source_revision_changed'
    assert image_row('old') in originals(s) + s._history


def test_repeated_images_survive_native_bundle_prune_restore(tmp_path, monkeypatch):
    from harness import chat_archive as archive
    s = setup_session(tmp_path, monkeypatch)
    monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'off')
    for i in range(3):
        s._history.append(image_row(str(i)))
        list(s._maybe_compact_history(emergency=True))
    expected = [image_row(x) for x in ('old', 'latest', '0', '1')]
    for row in expected: assert row in originals(s)
    sessions = [{'id': 'default', 'archived': True}]
    archive.ingest_all(s.state_dir, sessions=sessions)
    bundle = archive._verified_raw(s.state_dir, 'marionette:default')
    assert bundle
    assert archive.prune_ingested_transcripts(s.state_dir, sessions)['pruned'] == 1
    # Only this disposable test's sidecars are removed.
    for p in (tmp_path/'transcripts').glob('default.archive.json.segments/*.json'): p.unlink()
    (tmp_path/'transcripts/default.archive.json').unlink()
    assert archive.restore_pruned_transcript(s.state_dir, 'default')
    assert archive._bundle(s.state_dir, 'default', load_transcript(s.state_dir, 'default')) == bundle
    for row in expected:
        assert row in originals(s)
        data = base64.b64decode(row['content'][1]['image_url']['url'].split(',', 1)[1])
        assert hashlib.sha256(data).digest() == hashlib.sha256(PNG).digest()


@pytest.mark.parametrize('change', ['history', 'generation'])
def test_emergency_fences_aging_before_publication(tmp_path, monkeypatch, change):
    from harness import compaction_mixin as cm
    s = setup_session(tmp_path, monkeypatch)
    real = cm.age_history_images
    changed = []
    def replace_during_aging(*args, **kwargs):
        aged = real(*args, **kwargs)
        if change == 'history': s._history[3] = image_row('new owner')
        else: s._busy_gen += 1
        changed.extend(copy.deepcopy(s._history))
        return aged
    monkeypatch.setattr(cm, 'age_history_images', replace_during_aging)
    list(s._maybe_compact_history(force=True, emergency=True))
    assert s._history == changed
    assert s._last_compaction_attempt['reason'] == 'source_revision_changed'
    assert originals(s) == []


def test_normal_floor_leaves_originals_in_active_history(tmp_path, monkeypatch):
    s = setup_session(tmp_path, monkeypatch)
    monkeypatch.setattr('harness.compaction_mixin.MIN_COMPACTABLE_TOKENS', 100000)
    before = copy.deepcopy(s._history)
    list(s._maybe_compact_history(force=True))
    assert s._history == before
    assert originals(s) == []


def test_emergency_summarizer_failure_keeps_durable_originals(tmp_path, monkeypatch):
    s = setup_session(tmp_path, monkeypatch)
    monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'summary')
    class OfflineFailure:
        model = 'offline'
        def chat(self, *a, **kw): raise RuntimeError('synthetic summarizer failure')
    s.pilot = OfflineFailure()
    list(s._maybe_compact_history(force=True, emergency=True))
    assert image_row('old') in originals(s)
    assert image_row('latest') in s._history
    assert load_transcript(s.state_dir, 'default')['history'] == s._history[1:]


def test_projection_indexes_and_digests_describe_exact_source(tmp_path, monkeypatch):
    from harness.compaction_archive import json_digest
    s = setup_session(tmp_path, monkeypatch)
    monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'off')
    before = copy.deepcopy(s._history[1:])
    list(s._maybe_compact_history(emergency=True))
    rows, _ = load_compaction_archive_page(s.state_dir, 'default', limit=400)
    projection = rows[0]['_image_aging_projection']
    assert projection['rows'] == [before[i] for i in projection['indexes']]
    assert projection['source_history_digest'] == json_digest(before)
    assert projection['target_history_digest'] == json_digest(s._history[1:])
    assert projection['source_length'] == len(before)
    import sqlite3
    with sqlite3.connect(str(tmp_path/'history_compaction.sqlite')) as con:
        assert con.execute('SELECT source_json FROM compaction_commit').fetchone() == (None,)


def test_emergency_does_not_age_unpersisted_system_prefix(tmp_path, monkeypatch):
    s = setup_session(tmp_path, monkeypatch)
    monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'off')
    system = dict(image_row('system'), role='system')
    s._history[0] = copy.deepcopy(system)
    list(s._maybe_compact_history(emergency=True))
    assert s._history[0] == system


def test_emergency_reduces_native_request_bytes(tmp_path, monkeypatch):
    from pmharness.drivers.codex_responses import _messages_to_responses_input
    s = setup_session(tmp_path, monkeypatch)
    monkeypatch.setenv('HARNESS_COMPACTION_RESIDUAL', 'off')
    before = _messages_to_responses_input(s._history[1:])
    list(s._maybe_compact_history(emergency=True))
    after = _messages_to_responses_input(s._history[1:])
    assert serialized_history_bytes(after) < serialized_history_bytes(before)
    images = [part for row in after for part in row.get('content', [])
              if isinstance(part, dict) and part.get('type') == 'input_image']
    assert images == [{'type': 'input_image', 'image_url': image_row('latest')['content'][1]['image_url']['url']}]


@pytest.mark.parametrize('boundary', ['segment', 'manifest', 'transcript', 'success'])
def test_image_aging_abrupt_exit_and_cold_recovery(tmp_path, boundary):
    from pathlib import Path
    import subprocess
    import sys
    script = '''
import os, sys
from harness.context_budget import age_history_images
from harness.history_compaction_journal import commit_image_aged_transcript
from harness import compaction_archive as ca, sessions
state, boundary, source_json = sys.argv[1:]
import json
source = json.loads(source_json)
target = dict(source, history=age_history_images(source['history']))
real = os.replace
def replace(src, dst):
    real(src, dst)
    if ((boundary == 'segment' and '.segments/' in str(dst)) or
        (boundary == 'manifest' and str(dst).endswith('.archive.json')) or
        (boundary == 'transcript' and str(dst).endswith('/default.json'))):
        os._exit(71)
os.replace = replace
commit_image_aged_transcript(state, 'default', source, target)
os._exit(71)
'''
    source = {'history': [image_row('old'), image_row('latest')], 'display': [], 'job_ids': []}
    bootstrap = 'import sys;sys.path.insert(0,' + repr(str(Path(__file__).resolve().parents[1])) + ');'
    child = subprocess.run([sys.executable, '-I', '-c', bootstrap + script,
                            str(tmp_path), boundary, json.dumps(source)], timeout=15)
    assert child.returncode == 71
    cold = load_transcript(str(tmp_path), 'default')
    rows, _ = load_compaction_archive_page(str(tmp_path), 'default', limit=400)
    retained = [row for item in rows for row in item.get('_image_aging_projection', {}).get('rows', [])]
    assert image_row('old') in cold['history'] + retained
    assert image_row('latest') in cold['history']
    assert load_transcript(str(tmp_path), 'default') == cold
    if boundary in ('segment', 'manifest'): assert cold == source
    else: assert image_row('old') in retained
