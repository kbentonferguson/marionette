"""Exact draft and frozen terminal expansion at native/API boundaries."""
import copy
import json
from types import SimpleNamespace

import pytest

from harness.api.session_control import post_session_queue, post_session_steer, post_chat_stash
from harness.api.sessions import stash_put, stash_pop
from harness.api.streams import _admit_stream_input
from harness.input_receipts import InputReceiptStore, InputReceiptError, session_input_store
from tests.test_input_receipts_integration import session, services

RAW = '  inspect @terminal:"zsh:1"\n\t'
DELIVERY = '  inspect ```terminal\nfrozen output\n```\n\t'

@pytest.mark.parametrize('endpoint', [post_session_queue, post_session_steer])
def test_api_preserves_literal_and_delivery(session, endpoint):
    status, _ = endpoint({'text': DELIVERY, 'original_text': RAW}, services(session))
    assert status == 200
    row = session.input_receipts()[0]
    assert row['original_text'] == RAW
    assert row['delivery_text'] == DELIVERY
    if endpoint is post_session_queue:
        assert session.list_prompts()[0]['text'] == DELIVERY.strip()
    else:
        assert list(session._session_actions)[0].text == DELIVERY

@pytest.mark.parametrize('handoff', [False, True])
def test_stream_identity_ignores_replacement(session, handoff):
    store = session_input_store(session)
    item = session.enqueue_prompt(DELIVERY, original_text=RAW)
    token = session.handoff_prompt(item['id'])['handoff_token'] if handoff else None
    row, _, text, images = _admit_stream_input(session, 'client replacement', [], session.state_dir,
        input_id=item['id'], handoff_token=token, original_text='also ignored')
    assert text == DELIVERY
    assert row['original_text'] == RAW
    assert images == []


def test_retry_hash_and_cold_restore(tmp_path):
    store = InputReceiptStore(str(tmp_path / 'source'), 'A')
    row = store.admit(DELIVERY, original_text=RAW, retry_key='key')
    assert store.admit(DELIVERY, original_text=RAW, retry_key='key')['id'] == row['id']
    for text, original in [(DELIVERY + 'changed', RAW), (DELIVERY, RAW + 'changed')]:
        with pytest.raises(InputReceiptError, match='different payload'):
            store.admit(text, original_text=original, retry_key='key')
    bundle = store.snapshot()
    cold = InputReceiptStore(str(tmp_path / 'cold'), 'A')
    cold.restore(bundle)
    restored = cold.list()[0]
    assert restored['original_text'] == RAW and restored['delivery_text'] == DELIVERY
    assert restored['payload_digest'] == row['payload_digest'] and restored['held']
    for key in ('original_text', 'delivery_text'):
        corrupt = copy.deepcopy(bundle)
        corrupt['inputs'][0][key] += 'corrupt'
        with pytest.raises(InputReceiptError):
            cold.restore(corrupt)

@pytest.mark.parametrize('invalid', [None, 0, False, [], {}])
@pytest.mark.parametrize('endpoint', [post_session_queue, post_session_steer])
def test_invalid_original_is_rejected(session, invalid, endpoint):
    status, payload = endpoint({'text': DELIVERY, 'original_text': invalid}, services(session))
    assert status >= 400 and payload['code'] == 'input_invalid'
    assert session.input_receipts() == []


def test_long_stash_preserves_both():
    body = {'message': DELIVERY * 1000, 'original_text': RAW * 1000,
            'documents': [{'ref': 'input:A:doc', 'name': 'notes'}], 'session_id': 'A'}
    status, result = post_chat_stash(body, SimpleNamespace(stash_put=stash_put))
    assert status == 200
    assert stash_pop(result['id']) == dict(body, images=[])

@pytest.mark.parametrize('mode', ['chat', 'auto'])
@pytest.mark.parametrize('handoff', [False, True])
def test_actual_stream_dispatch_preserves_both(session, monkeypatch, mode, handoff):
    import io
    from harness.api.streams import StreamServices, stream_chat, stream_auto
    captured = []
    def send(text, *args, **kwargs):
        captured.append((text, kwargs))
        return iter(())
    monkeypatch.setattr(session, 'send', send)
    monkeypatch.setattr(session, 'run_auto', send)
    svc = StreamServices(cfg=session.config,
        sessions=SimpleNamespace(active=session.harness_session_id, set_title_if_default=lambda *_: None),
        get_pilot=lambda: session, get_session=lambda: session, ensure_pilot_matches_driver=lambda: None,
        maybe_refresh_codegraph=lambda *_: None, pilot_preflight=lambda: None,
        checkpoint_transcript=lambda *_: None, finalize_turn=lambda *_: None,
        upload_dir=services(session).upload_dir, auto_budget_from_env=lambda: None)
    class Handler:
        wfile = io.BytesIO()
        def _send(self, status, body): pytest.fail((status, body))
        def send_response(self, status): assert status == 200
        def send_header(self, *_): pass
        def _cors(self): pass
        def end_headers(self): pass
    args = {'original_text': RAW, 'session_id': session.harness_session_id}
    text = DELIVERY
    if handoff:
        item = session.enqueue_prompt(DELIVERY, original_text=RAW)
        args.update(input_id=item['id'], handoff_token=session.handoff_prompt(item['id'])['handoff_token'])
        text = 'client override'
        args['original_text'] = 'client original override'
    if mode == 'chat':
        stream_chat(Handler(), text, [], svc, **args)
    else:
        stream_auto(Handler(), text, svc, images=[], **args)
    assert captured[0][0] == DELIVERY
    row = session.input_receipts()[0]
    assert row['original_text'] == RAW and row['delivery_text'] == DELIVERY
    assert captured[0][1]['input_id'] == row['id']

@pytest.mark.parametrize('mode', ['chat', 'auto'])
@pytest.mark.parametrize('raw', ['', RAW, RAW * 1000], ids=['empty', 'short', 'stashed'])
def test_http_routes_transport_original_and_delivery(monkeypatch, mode, raw):
    from urllib.parse import urlencode, urlparse, parse_qs
    import harness.server as srv
    from harness.http_routes import build_get_routes
    from harness.api import sessions
    monkeypatch.setattr(sessions, '_CHAT_STASH', {})
    captures = []
    class Handler:
        def _stream_chat(self, text, images, **fields): captures.append((text, images, fields))
        def _stream_auto(self, text, images, **fields): captures.append((text, images, fields))
        def _send(self, status, body): pytest.fail((status, body))
    fields = {'original_text': raw, 'session_id': 'A'}
    if len(raw) > 4000:
        query = {'mid': sessions.stash_put(DELIVERY, [], **fields)}
    else:
        query = {('message' if mode == 'chat' else 'objective'): DELIVERY, **fields}
    url = urlparse('/api/' + mode + '?' + urlencode(query))
    build_get_routes(srv._route_services())[url.path](Handler(), url, parse_qs(url.query))
    expected = dict(fields, plan=False, resume=False) if mode == 'chat' else fields
    assert captures == [(DELIVERY, [], expected)]

@pytest.mark.parametrize('version', [1, 2])
def test_legacy_hashes_unchanged_and_optional_field_cannot_be_smuggled(tmp_path, version):
    from harness.compaction_archive import json_digest
    store = InputReceiptStore(str(tmp_path / str(version)), 'A')
    row = store.admit(RAW, retry_key='old')
    expected_payload = json_digest({'text': RAW, 'attachments': [], 'model': ''})
    expected_metadata = json_digest({key: row[key] for key in ('original_text', 'attachments', 'model', 'payload_digest')})
    assert row['payload_digest'] == expected_payload
    assert row['metadata_digest'] == expected_metadata
    doc = store.snapshot()
    doc['version'] = version
    if version == 1:
        doc['inputs'][0].pop('metadata_digest')
    restored = InputReceiptStore(str(tmp_path / ('restored' + str(version))), 'A')
    restored.restore(doc)
    after = restored.get(row['id'])
    assert 'delivery_text' not in after
    assert after['payload_digest'] == expected_payload and after['metadata_digest'] == expected_metadata
    for value in (None, 42, DELIVERY):
        corrupt = copy.deepcopy(doc)
        corrupt['inputs'][0]['delivery_text'] = value
        with pytest.raises(InputReceiptError):
            restored.restore(corrupt)


def test_payload_verification_covers_delivery_even_if_metadata_rehashed(tmp_path):
    store = InputReceiptStore(str(tmp_path), 'A')
    store.admit(DELIVERY, original_text=RAW)
    document = store.snapshot()
    row = document['inputs'][0]
    row['delivery_text'] = 'changed frozen delivery'
    row['metadata_digest'] = store._metadata_digest(row)
    with pytest.raises(InputReceiptError):
        store.restore(document)


def test_bundle_restores_both_texts_and_retained_attachments_without_replay(session):
    import base64
    from pathlib import Path
    from harness import chat_archive
    from tests.test_input_receipts_integration import seed_history
    svc = services(session)
    document = Path(svc.upload_dir) / 'notes.txt'
    image = Path(svc.upload_dir) / 'image.png'
    document.write_bytes(b'retained document bytes\x00\n')
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6nAAAAABJRU5ErkJggg=='))
    code, _ = post_session_queue({'text': DELIVERY, 'original_text': RAW,
        'images': [str(image)], 'documents': [str(document)]}, svc)
    assert code == 200
    seed_history(session)
    store = session_input_store(session)
    row = store.list()[0]
    expected = {a['ref']: store.attachment(a['ref']) for a in row['attachments']}
    catalog = [{'id': session.harness_session_id, 'archived': True}]
    assert chat_archive.ingest_all(session.state_dir, sessions=catalog)['ingested'] == 1
    assert chat_archive.prune_ingested_transcripts(session.state_dir, catalog)['pruned'] == 1
    # These paths belong only to this test's temporary directory.
    document.unlink(); image.unlink(); store.path.unlink()
    assert chat_archive.restore_pruned_transcript(session.state_dir, session.harness_session_id)
    cold = InputReceiptStore(session.state_dir, session.harness_session_id)
    restored = cold.list()[0]
    assert restored['original_text'] == RAW and restored['delivery_text'] == DELIVERY
    assert restored['held'] and restored['status'] == 'accepted'
    assert restored['payload_digest'] == row['payload_digest']
    assert {ref: cold.attachment(ref) for ref in expected} == expected
    text, paths = cold.delivery_content(row['id'])
    assert text.endswith(DELIVERY) and len(paths) == 1
    with pytest.raises(InputReceiptError):
        cold.prepare_delivery(row['id'])

@pytest.mark.parametrize('mode', ['chat', 'auto'])
@pytest.mark.parametrize('handoff', [False, True])
def test_provider_and_history_keep_delivery_context_and_literal_receipt(session, monkeypatch, mode, handoff):
    import io
    from pathlib import Path
    from harness.api.streams import StreamServices, stream_chat, stream_auto
    from harness.sessions import load_transcript
    control = services(session)
    document = Path(control.upload_dir) / 'annotated.txt'
    document.write_text('retained document annotation')
    repo = Path(session.state_dir) / 'repo'
    repo.mkdir()
    (repo / 'note.txt').write_text('workspace mention contents')
    session.config.repo = str(repo)
    raw = RAW + ' @note.txt'
    delivery = DELIVERY + ' @note.txt'
    calls = []
    class Pilot:
        name = 'synthetic'
        def chat(self, messages, tools=None, system=None):
            row = session.input_receipts()[0]
            assert row['status'] == 'injected'
            assert row['original_text'] == raw and row['delivery_text'] == delivery
            encoded = json.dumps(messages)
            assert 'frozen output' in encoded
            assert '@terminal:' not in encoded and 'client replacement' not in encoded
            assert 'retained document annotation' in encoded
            if mode == 'chat':
                assert 'workspace mention contents' in encoded
            else:
                assert 'AUTONOMOUS MODE' in encoded
            history = load_transcript(session.state_dir, session.harness_session_id)['history']
            assert row['id'] in history[-1]['input_ids']
            assert 'frozen output' in json.dumps(history)
            calls.append(True)
            return SimpleNamespace(text='{"say":"done","actions":[]}', error=None,
                                   tokens_in=0, tokens_out=0, meta={})
    session.pilot = Pilot()
    class Handler:
        wfile = io.BytesIO()
        def send_response(self, status): assert status == 200
        def send_header(self, *_): pass
        def _cors(self): pass
        def end_headers(self): pass
        def _send(self, status, body): pytest.fail((status, body))
    svc = StreamServices(cfg=session.config,
        sessions=SimpleNamespace(active=session.harness_session_id, set_title_if_default=lambda *_: None),
        get_pilot=lambda: session, get_session=lambda: session, ensure_pilot_matches_driver=lambda: None,
        maybe_refresh_codegraph=lambda *_: None, pilot_preflight=lambda: None,
        checkpoint_transcript=lambda *_: None, finalize_turn=lambda *_: None,
        upload_dir=control.upload_dir, auto_budget_from_env=lambda: None)
    args = {'original_text': raw, 'documents': [{'path': str(document)}], 'session_id': session.harness_session_id}
    text = delivery
    if handoff:
        item = session.enqueue_prompt(delivery, original_text=raw, documents=args['documents'], upload_root=control.upload_dir)
        args.update(input_id=item['id'], handoff_token=session.handoff_prompt(item['id'])['handoff_token'])
        text = 'client replacement'
        args['original_text'] = 'client original replacement'
        args['documents'] = []
    if mode == 'chat':
        stream_chat(Handler(), text, [], svc, **args)
    else:
        stream_auto(Handler(), text, svc, images=[], **args)
    assert calls
    assert session.input_receipts()[0]['status'] == 'injected'

@pytest.mark.parametrize('endpoint,extra', [
    (post_session_queue, {'delivery_mode': 'follow_up'}),
    (post_session_queue, {'delivery_mode': 'steer'}),
    (post_session_steer, {'turn_input_mode': 'steer'}),
    (post_session_steer, {'turn_input_mode': 'start_if_idle'}),
])
def test_delivery_modes_retain_both(session, endpoint, extra):
    status, result = endpoint({'text': DELIVERY, 'original_text': RAW, **extra}, services(session))
    assert status == 200, result
    row = session.input_receipts()[0]
    assert row['original_text'] == RAW and row['delivery_text'] == DELIVERY

@pytest.mark.parametrize('invalid', [None, False, 2, [], {}])
def test_stash_and_stream_reject_invalid_original_before_admission(session, invalid):
    code, body = post_chat_stash({'message': DELIVERY, 'original_text': invalid}, SimpleNamespace(stash_put=stash_put))
    assert code == 400 and body['code'] == 'input_invalid'
    with pytest.raises(InputReceiptError):
        _admit_stream_input(session, DELIVERY, [], services(session).upload_dir, original_text=invalid)
    assert session.input_receipts() == []


def test_empty_original_and_attachment_only_queue(session):
    from pathlib import Path
    svc = services(session)
    document = Path(svc.upload_dir) / 'only.txt'
    document.write_text('attachment-only original')
    status, result = post_session_queue({'text': '', 'original_text': '', 'documents': [str(document)]}, svc)
    assert status == 200, result
    row = session.input_receipts()[0]
    assert row['original_text'] == row['delivery_text'] == ''
    assert len(row['attachments']) == 1


def test_stash_keeps_deep_copy_with_original():
    fields = {'documents': [{'ref': 'input:A:document', 'name': 'retained'}], 'original_text': RAW}
    mid = stash_put(DELIVERY, [], **fields)
    fields['documents'][0]['name'] = 'mutated'
    saved = stash_pop(mid)
    assert saved['original_text'] == RAW and saved['message'] == DELIVERY
    assert saved['documents'][0]['name'] == 'retained'


def test_legacy_queue_projection_still_accepts_server_derived_text(session):
    store = session_input_store(session)
    row = store.admit('old original')
    item = session.enqueue_prompt('old derived annotation', input_id=row['id'])
    assert item['text'] == 'old derived annotation'
    assert 'delivery_text' not in store.get(row['id'])


def test_new_queue_projection_comes_from_frozen_delivery(session):
    store = session_input_store(session)
    row = store.admit(DELIVERY, original_text=RAW)
    item = session.enqueue_prompt('replacement', input_id=row['id'])
    assert item['text'] == DELIVERY.strip()
