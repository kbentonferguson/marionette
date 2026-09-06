"""Approval replay gates against real sessions and isolated on-disk state."""
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.api.command_approvals import (
    CommandApprovalServices, post_command_approval,
    post_command_rejection, post_command_approval_amendment,
)
from harness.config import HarnessConfig
from harness.conversation import ConversationalSession

ROUTES = [post_command_approval, post_command_rejection, post_command_approval_amendment]


@pytest.fixture
def session(tmp_path):
    runner = ConversationalSession(HarnessConfig(repo=str(tmp_path), state_dir=str(tmp_path / 'state')))
    runner.harness_session_id = 'identity-session'
    return runner


def register(session, action='same-action'):
    command = 'git push --force origin main'
    return session.register_pending_command_approval(
        command=command, command_hash=hashlib.sha256(command.encode()).hexdigest(), action_id=action,
    )


def body(pending):
    return {**{key: pending[key] for key in ('session_id', 'workspace_root', 'command_hash')},
            'approval_protocol': 1, 'expected_action_id': pending['action_id'],
            'expected_approval_id': pending.get('approval_id', 'baseline-missing')}


def call(session, route, request):
    return route(request, CommandApprovalServices(get_runners=lambda: {session.harness_session_id: session}))


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('same_action', [True, False])
def test_replacement_rejects_old_identity(session, route, same_action):
    old = register(session)
    current = register(session, 'same-action' if same_action else 'new-action')
    before = session.export_transcript_data()
    status, payload = call(session, route, body(old))
    assert status == 409
    assert payload['error'] == 'stale_approval'
    assert session._pending_command_approvals[current['command_hash']] == current
    assert not session._approved_commands
    assert session.export_transcript_data() == before
    assert not (Path(session.state_dir) / "command_allowlist.json").exists()


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('missing', ['approval_protocol', 'expected_action_id', 'expected_approval_id'])
def test_missing_identity_requires_refresh(session, route, missing):
    pending = register(session)
    request = body(pending)
    del request[missing]
    status, payload = call(session, route, request)
    assert status == 409
    assert payload['error'] == 'approval_refresh_required'
    assert pending['command_hash'] in session._pending_command_approvals


@pytest.mark.parametrize('route', ROUTES)
def test_valid_identity_decides_once(session, route):
    pending = register(session)
    status, receipt = call(session, route, body(pending))
    assert status == 200
    assert receipt['approval_id'] == pending['approval_id']
    assert receipt['action_id'] == pending['action_id']
    assert call(session, route, body(pending))[0] == 404


def test_disk_roundtrip_and_legacy_refresh(session, tmp_path):
    pending = register(session)
    path = tmp_path / 'transcript.json'
    path.write_text(json.dumps(session.export_transcript_data()))
    restored = ConversationalSession(session.config)
    restored.harness_session_id = session.harness_session_id
    restored.load_history(json.loads(path.read_text()))
    assert restored._pending_command_approvals[pending['command_hash']]['approval_id'] == pending['approval_id']
    assert call(restored, post_command_rejection, body(pending))[0] == 200
    row = session._display_command_approval_row(pending, status='pending')
    row.pop('approval_id', None)
    row.pop('approval_protocol', None)
    session._display_transcript = [row]
    session._restore_pending_command_approvals_from_display()
    migrated = session._pending_command_approvals[pending['command_hash']]
    assert migrated['approval_id'] != pending['approval_id']
    assert call(session, post_command_rejection, body(pending))[0] == 409
    assert session._display_transcript[0]['approval_id'] == migrated['approval_id']
    assert call(session, post_command_rejection, body(migrated))[0] == 200


@pytest.mark.parametrize("route", ROUTES)
def test_decision_and_replacement_are_linearized(session, route):
    old = register(session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        decision = pool.submit(call, session, route, body(old))
        replacement = pool.submit(register, session)
    current = replacement.result()
    assert decision.result()[0] in (200, 409)
    assert session._pending_command_approvals[current['command_hash']] == current
    if route is post_command_rejection:
        assert not session._approved_commands


@pytest.mark.parametrize('route_path', ['approve', 'reject', 'approve-amendment'])
@pytest.mark.parametrize('transport', ['memory', 'socket'])
def test_actual_handler_identity_and_auth(session, monkeypatch, route_path, transport):
    # conftest seals state before server import; the Handler and route table are real.
    import io
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from harness import server

    monkeypatch.setattr(server, '_runners', {session.harness_session_id: session})
    monkeypatch.setattr(server, '_TOKEN', 'isolated-test-token')
    path = '/api/commands/' + route_path

    class Connection:
        def __init__(self, request):
            self.input = io.BytesIO(request)
            self.output = bytearray()

        def makefile(self, *args):
            return self.input

        def sendall(self, data):
            self.output.extend(data)

    httpd = None
    if transport == 'socket':
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

    def request(payload, token='isolated-test-token', origin='http://127.0.0.1', host='127.0.0.1'):
        data = json.dumps(payload).encode()
        if httpd is not None:
            req = Request('http://127.0.0.1:%d%s' % (httpd.server_port, path), data=data,
                          headers={'X-Harness-Token': token, 'Content-Type': 'application/json',
                                   'Origin': origin, 'Host': host})
            try:
                response = urlopen(req, timeout=5)
            except HTTPError as exc:
                response = exc
            with response:
                return response.code, json.load(response)
        raw = ('POST %s HTTP/1.0\r\nHost: %s\r\nOrigin: %s\r\nX-Harness-Token: %s\r\n'
               'Content-Type: application/json\r\nContent-Length: %d\r\n\r\n' %
               (path, host, origin, token, len(data))).encode() + data
        connection = Connection(raw)
        server.Handler(connection, ('127.0.0.1', 12345), None)
        headers, content = bytes(connection.output).split(b'\r\n\r\n', 1)
        return int(headers.split()[1]), json.loads(content)

    try:
        old = register(session)
        current = register(session)
        assert request(body(current), token='wrong')[0] == 403
        assert request(body(current), origin='https://foreign.example')[0] == 403
        assert request(body(current), host='foreign.example')[0] == 403
        assert request(body(old))[0] == 409
        missing = body(current)
        missing.pop('approval_protocol')
        assert request(missing)[0] == 409
        assert session._pending_command_approvals[current['command_hash']] == current
        assert not session._approved_commands
        assert request(body(current))[0] == 200
        assert request(body(current))[0] == 404
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
            thread.join(5)


@pytest.mark.parametrize('protocol', [True, '1', 0, 2])
def test_unsupported_protocol_is_explicit(session, protocol):
    pending = register(session)
    request = body(pending)
    request['approval_protocol'] = protocol
    assert call(session, post_command_rejection, request) == (400, {'error': 'unsupported_approval_protocol'})
    assert pending['command_hash'] in session._pending_command_approvals


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('field,value,status', [
    ('expected_action_id', 'wrong-action', 409),
    ('expected_approval_id', 'wrong-approval', 409),
    ('workspace_root', '/wrong-workspace', 403),
    ('session_id', 'wrong-session', 404),
])
def test_scope_and_each_identity_component(session, route, field, value, status):
    pending = register(session)
    request = body(pending)
    request[field] = value
    assert call(session, route, request)[0] == status
    assert session._pending_command_approvals[pending['command_hash']] == pending
    assert not session._approved_commands
    assert not (Path(session.state_dir) / 'command_allowlist.json').exists()
