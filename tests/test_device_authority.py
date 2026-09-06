import io
import json
import os
from types import SimpleNamespace

import pytest

posix_storage = pytest.mark.skipif(os.name != "posix", reason="device storage requires POSIX permission proof")


def request(server, path, headers=(), method='GET', body=b''):
    class Connection:
        def __init__(self):
            self.output = io.BytesIO()
        def makefile(self, mode, *args):
            return io.BytesIO(raw) if mode == 'rb' else self.output
        def sendall(self, data):
            self.output.write(data)
        def settimeout(self, value):
            pass
    fields = [('Host', 'localhost'), *headers]
    if body:
        fields.append(('Content-Length', str(len(body))))
    raw = (f'{method} {path} HTTP/1.0\r\n' + ''.join(f'{k}: {v}\r\n' for k,v in fields) + '\r\n').encode() + body
    conn = Connection()
    server.Handler(conn, ('127.0.0.1', 1), SimpleNamespace())
    head, data = conn.output.getvalue().split(b'\r\n\r\n', 1)
    return int(head.split()[1]), json.loads(data) if data else {}, head


@pytest.fixture
def env(tmp_path, monkeypatch):
    from harness import server
    from harness.device_grants import DeviceGrantStore
    from harness.endpoint_identity import EndpointIdentity
    identity = EndpointIdentity(tmp_path / 'endpoint.json', 'boot')
    store = DeviceGrantStore(tmp_path / 'devices', identity.endpoint_id)
    sessions = tmp_path / 'sessions.json'
    sessions.write_text(json.dumps({'sessions': [
        {'id': 'a', 'created': 1, 'workspace_root': '/workspace/a', 'title': 'A'},
        {'id': 'b', 'created': 2, 'workspace_root': '/workspace/b', 'title': 'B'}], 'active': 'b'}))
    monkeypatch.setattr(server, '_device_grants', lambda: store)
    monkeypatch.setattr(server, '_endpoint_identity', lambda: identity)
    monkeypatch.setattr(server, '_sessions', SimpleNamespace(path=str(sessions)))
    monkeypatch.setattr(server, '_TOKEN', 'owner')
    monkeypatch.setattr(server, '_device_original_log', server.Handler.log_message, raising=False)
    monkeypatch.setattr(server.Handler, 'log_message', lambda *a: None)
    return server, store, sessions


def enroll(env, grants=None):
    server, _, _ = env
    status, data, head = request(server, '/api/devices/enroll', [('X-Harness-Token','owner')], 'POST', json.dumps({
        'label': 'test', 'grants': grants or [
            {'operation':'endpoint.read','resource_id':server._endpoint_identity().endpoint_id},
            {'operation':'session.read','resource_id':'a'},
            {'operation':'session.events.read','resource_id':'a'}]}).encode())
    assert status == 201, data
    assert b'Cache-Control: no-store' in head
    return data


def device_headers(env, token):
    identity = env[0]._endpoint_identity()
    return [('X-Harness-Device-Token', token), ('X-Harness-Protocol','1'),
            ('X-Harness-Endpoint',identity.endpoint_id), ('X-Harness-Boot',identity.boot_id)]


@posix_storage
def test_exact_authority_and_revoke(env):
    data = enroll(env)
    headers = device_headers(env, data['credential'])
    assert request(env[0], '/api/device/session?session_id=a', headers)[1]['session']['id'] == 'a'
    assert request(env[0], '/api/device/session?session_id=b', headers)[0] == 403
    assert request(env[0], '/api/device/endpoint', headers)[0] == 200
    listed = request(env[0], '/api/devices', [('X-Harness-Token','owner')])[1]
    assert data['credential'] not in json.dumps(listed)
    assert 'digest' not in json.dumps(listed)
    path = '/api/devices/' + data['device_id'] + '/revoke'
    assert request(env[0], path, [('X-Harness-Token','owner')], 'POST', b'{}')[0] == 200
    assert request(env[0], '/api/device/endpoint', headers + [('X-Harness-Token','owner')])[0] == 403


@pytest.mark.parametrize('path', ['/api/wiki/connect?nonce=x', '/api/upload', '/api/files', '/api/terminal', '/api/jobs/a/events', '/api/session/events?session=a', '/unknown'])
@pytest.mark.parametrize('method', ['GET', 'POST', 'DELETE', 'PUT', 'PATCH', 'OPTIONS', 'HEAD'])
def test_unknown_routes_never_dispatch(env, monkeypatch, path, method):
    def forbidden(*args):
        pytest.fail('owner handler reached')
    monkeypatch.setattr(env[0], '_get_routes', forbidden)
    monkeypatch.setattr(env[0], '_post_json_routes', forbidden)
    assert request(env[0], path, [('X-Harness-Device-Token', 'bad'), ('X-Harness-Token', 'owner')], method)[0] == 403


@pytest.mark.parametrize('query', ['session_id=a&session_id=b', 'session_id=a&session=b', 'session_id=a&workspace=b', 'session_id=a&token=owner', 'session_id=', 'session_id=%20a', 'session_id=a&watch=1'])
def test_aliases_and_extra_query_rejected(env, query):
    assert request(env[0], '/api/device/session?' + query, device_headers(env, 'bad'))[0] == 400


@pytest.mark.parametrize('name', ['X-Harness-Token', 'X-Harness-Device-Token', 'X-Harness-Protocol', 'X-Harness-Endpoint', 'X-Harness-Boot', 'Host', 'Origin', 'Content-Length'])
def test_duplicate_headers(env, name):
    headers = device_headers(env, 'bad')
    headers += [(name, 'x'), (name.lower(), 'y')]
    assert request(env[0], '/api/device/session?session_id=a', headers)[0] == 400


@pytest.mark.parametrize('body', [b'{"label":"a","label":"b","grants":[]}', b'{"label":"x","grants":[],"session":"a"}', b'[]', b'{"label":false,"grants":[]}'])
def test_bad_enrollment(env, body):
    assert request(env[0], '/api/devices/enroll', [('X-Harness-Token','owner')], 'POST', body)[0] == 400


@posix_storage
def test_workspace_move_and_deleted_record_denied(env):
    data = enroll(env)
    headers = device_headers(env, data['credential'])
    records = json.loads(env[2].read_text())
    records['sessions'][0]['workspace_root'] = '/workspace/b'
    env[2].write_text(json.dumps(records))
    assert request(env[0], '/api/device/session?session_id=a', headers)[0] == 403
    records['sessions'] = records['sessions'][1:]
    env[2].write_text(json.dumps(records))
    assert request(env[0], '/api/device/session?session_id=a', headers)[0] == 403


@posix_storage
def test_events_exact_ring_and_view_switch_barrier(env, monkeypatch):
    from harness.api.sse import SseEventRing
    data = enroll(env)
    headers = device_headers(env, data['credential'])
    ring = SseEventRing('a', 1)
    ring.append('text', {'text': 'only A'})
    def lookup(sid, generation):
        assert sid == 'a'
        records = json.loads(env[2].read_text())
        records['active'] = 'b'
        env[2].write_text(json.dumps(records))
        return ring
    monkeypatch.setattr(env[0], '_sse_ring_lookup', lookup)
    status, payload, _ = request(env[0], '/api/device/session/events?session_id=a', headers)
    assert status == 200
    assert payload['events'][0]['data']['text'] == 'only A'
    assert request(env[0], '/api/device/session/events?session_id=b', headers)[0] == 403
    assert request(env[0], '/api/device/session/events?session_id=a&since=2&generation=1', headers)[1]['code'] == 'future_cursor'


@posix_storage
def test_db_failure_and_permissions_fail_closed(env):
    data = enroll(env)
    headers = device_headers(env, data['credential'])
    env[1].path.chmod(0o644)
    assert request(env[0], '/api/device/endpoint', headers)[0] == 503
    env[1].path.chmod(0o600)
    env[1].path.write_bytes(b'not sqlite')
    assert request(env[0], '/api/device/endpoint', headers)[0] == 503


@posix_storage
def test_store_restart_digest_only_and_idempotent_revoke(env):
    from harness.device_grants import DeviceDenied, DeviceGrantStore
    data = enroll(env)
    store = DeviceGrantStore(env[1].directory, env[1].endpoint_id)
    with store.transaction() as db:
        assert store.authenticate(db, data['credential']).grants_revision == 1
        assert data['credential'].split('.')[-1] not in str(db.execute('SELECT * FROM devices').fetchall())
        assert store.revoke(db, data['device_id'])
    with store.transaction() as db:
        assert store.revoke(db, data['device_id'])
        assert store.list(db)[0]['grants_revision'] == 2
        with pytest.raises(DeviceDenied):
            store.authenticate(db, data['credential'])


@posix_storage
def test_revoke_waits_for_json_write(env, monkeypatch):
    import threading
    from harness.device_grants import DeviceGrantStore
    data = enroll(env)
    headers = device_headers(env, data['credential'])
    writing, release, revoked = threading.Event(), threading.Event(), threading.Event()
    original = env[0].Handler._send
    def send(handler, code, body, *args):
        if code == 200 and 'X-Harness-Device-Token' in handler.headers:
            writing.set()
            assert release.wait(2)
        return original(handler, code, body, *args)
    monkeypatch.setattr(env[0].Handler, '_send', send)
    def revoke():
        store = DeviceGrantStore(env[1].directory, env[1].endpoint_id)
        with store.transaction() as db:
            store.revoke(db, data['device_id'])
        revoked.set()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:
        read = pool.submit(request, env[0], '/api/device/endpoint', headers)
        assert writing.wait(2)
        revocation = pool.submit(revoke)
        assert not revoked.wait(.1)
        release.set()
        assert read.result()[0] == 200
        revocation.result()
    assert request(env[0], '/api/device/endpoint', headers)[0] == 403


@posix_storage
def test_process_restart_and_rollback(env):
    import subprocess
    import sys
    data = enroll(env)
    code = '''import sys
sys.path.insert(0, '.')
from harness.device_grants import DeviceGrantStore
store = DeviceGrantStore(sys.argv[1], sys.argv[2])
with store.transaction() as db:
    assert store.list(db)[0]['grants_revision'] == 1
    store.revoke(db, sys.argv[3])
'''
    result = subprocess.run([sys.executable, '-I', '-c', code, str(env[1].directory), env[1].endpoint_id, data['device_id']], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert request(env[0], '/api/device/endpoint', device_headers(env, data['credential']))[0] == 403
    with pytest.raises(RuntimeError):
        with env[1].transaction() as db:
            env[1].enroll(db, 'rolled back', ())
            raise RuntimeError()
    with env[1].transaction() as db:
        assert len(env[1].list(db)) == 1


@posix_storage
def test_real_loopback(env):
    import socket
    import threading
    from http.server import ThreadingHTTPServer
    data = enroll(env)
    try:
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), env[0].Handler)
    except PermissionError:
        pytest.skip('sandbox prohibits loopback bind')
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.socket() as client:
            client.settimeout(3)
            client.connect(httpd.server_address)
            fields = [('Host','localhost'), *device_headers(env, data['credential'])]
            raw = ('GET /api/device/session?session_id=a HTTP/1.0\r\n' + ''.join(f'{k}: {v}\r\n' for k,v in fields) + '\r\n').encode()
            client.sendall(raw)
            chunks = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        head, body = b''.join(chunks).split(b'\r\n\r\n', 1)
        assert head.split()[1] == b'200'
        assert json.loads(body)['session']['id'] == 'a'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


@pytest.mark.parametrize('header,value', [('X-Harness-Boot','old'), ('X-Harness-Endpoint','other'), ('X-Harness-Protocol','2')])
@posix_storage
def test_device_fences(env, header, value):
    data = enroll(env)
    headers = [(k, value if k == header else v) for k,v in device_headers(env, data['credential'])]
    assert request(env[0], '/api/device/session?session_id=a', headers)[0] in (409, 426)


def test_device_body_and_owner_management_denied(env):
    headers = device_headers(env, 'bad') + [('X-Harness-Token','owner')]
    assert request(env[0], '/api/device/session?session_id=a', headers, body=b'{}')[0] == 400
    assert request(env[0], '/api/devices', headers)[0] == 403
    assert request(env[0], '/api/devices/enroll', headers, 'POST', b'{}')[0] == 403


@posix_storage
def test_session_store_errors_and_symlink_credentials(env, tmp_path):
    data = enroll(env)
    headers = device_headers(env, data['credential'])
    env[2].write_text('broken')
    assert request(env[0], '/api/device/session?session_id=a', headers)[0] == 503
    original = env[1].path
    target = tmp_path / 'copy.sqlite'
    original.rename(target)
    original.symlink_to(target)
    assert request(env[0], '/api/device/endpoint', headers)[0] == 503


@pytest.mark.parametrize('token', ['', 'wrong', 'dev1.bad.bad'])
@posix_storage
def test_invalid_device_never_owner_fallback_without_protocol(env, token):
    assert request(env[0], '/api/device/endpoint', [('X-Harness-Token','owner'), ('X-Harness-Device-Token',token)])[0] == 403


def test_identity_runtime_error_is_explicit(env, monkeypatch):
    def broken():
        raise RuntimeError('must not expose internal details')
    monkeypatch.setattr(env[0], '_endpoint_identity', broken)
    status, payload, _ = request(env[0], '/api/devices', [('X-Harness-Token','owner')])
    assert status == 503
    assert 'internal' not in json.dumps(payload)


@posix_storage
def test_resource_rebind_during_ring_read_denied(env, monkeypatch):
    from harness.api.sse import SseEventRing
    data = enroll(env)
    def lookup(*args):
        records = json.loads(env[2].read_text())
        records['sessions'][0]['workspace_root'] = '/workspace/b'
        env[2].write_text(json.dumps(records))
        ring = SseEventRing('a', 1)
        ring.append('text', 'should not escape')
        return ring
    monkeypatch.setattr(env[0], '_sse_ring_lookup', lookup)
    status, payload, _ = request(env[0], '/api/device/session/events?session_id=a', device_headers(env, data['credential']))
    assert status == 403
    assert 'escape' not in json.dumps(payload)


def test_enrollment_and_device_logs_omit_secrets(env, monkeypatch):
    from harness import diag
    from email.message import Message
    captured = []
    monkeypatch.setattr(diag, 'note', lambda *args, **kwargs: captured.append(kwargs))
    fields = Message()
    fields['X-Harness-Device-Token'] = 'credential-not-for-logs'
    handler = SimpleNamespace(path='/api/device/endpoint?token=credential-not-for-logs', headers=fields)
    env[0]._device_original_log(handler, 'GET %s', handler.path)
    handler.path = '/api/devices/enroll'
    env[0]._device_original_log(handler, 'POST %s', handler.path)
    assert captured
    assert 'credential-not-for-logs' not in json.dumps(captured)


@pytest.mark.parametrize('error', [OSError, RuntimeError])
@pytest.mark.parametrize('path', ['/api/devices', '/api/device/endpoint'])
def test_store_factory_failure_is_unavailable(env, monkeypatch, error, path):
    def broken():
        raise error('private-runtime-detail')
    monkeypatch.setattr(env[0], '_device_grants', broken)
    headers = [('X-Harness-Token', 'owner')]
    if path == '/api/device/endpoint':
        headers += [('X-Harness-Device-Token', 'bad')]
    status, payload, head = request(env[0], path, headers)
    assert (status, payload) == (503, {'ok': False, 'code': 'device_unavailable'})
    assert b'Cache-Control: no-store' in head


def test_store_endpoint_mismatch_blocks_before_transaction(env, monkeypatch):
    def forbidden():
        pytest.fail('mismatched store accessed')
    monkeypatch.setattr(env[1], 'endpoint_id', 'another-endpoint')
    monkeypatch.setattr(env[1], 'transaction', forbidden)
    for path, headers in [('/api/devices', [('X-Harness-Token', 'owner')]),
                          ('/api/device/endpoint', [('X-Harness-Device-Token', 'bad')])]:
        assert request(env[0], path, headers)[0] == 503


@posix_storage
def test_management_uses_captured_identity(env, monkeypatch):
    identity = env[0]._endpoint_identity()
    calls = []
    def once():
        calls.append(1)
        assert len(calls) == 1
        return identity
    headers = [('X-Harness-Token', 'owner'), ('X-Harness-Protocol', '1'),
               ('X-Harness-Endpoint', identity.endpoint_id), ('X-Harness-Boot', identity.boot_id)]
    monkeypatch.setattr(env[0], '_endpoint_identity', once)
    assert request(env[0], '/api/devices', headers)[0] == 200
    assert len(calls) == 1


@pytest.mark.parametrize('column,value', [
    ('digest', 42), ('digest', b'not-text'), ('digest', 'not-a-digest'), ('digest', '\u00e9' * 64),
    ('grants', '{'), ('grants', '{}'), ('grants', 'null'), ('grants', '[1]'),
    ('grants', '[{"operation":"endpoint.read","resource_id":[],"binding":"x"}]'),
    ('grants', '[]'), ('revision', 'broken'),
])
@posix_storage
def test_corrupt_store_metadata_is_unavailable(env, column, value):
    data = enroll(env)
    with env[1].transaction() as db:
        db.execute('UPDATE devices SET ' + column + '=?', (value,))
    for path, headers in [('/api/device/endpoint', device_headers(env, data['credential'])),
                          ('/api/devices', [('X-Harness-Token', 'owner')])]:
        status, payload, head = request(env[0], path, headers)
        assert (status, payload) == (503, {'ok': False, 'code': 'device_unavailable'})
        assert data['credential'] not in json.dumps(payload)
        assert b'Cache-Control: no-store' in head


@pytest.mark.parametrize('disable', [False, True])
def test_unsupported_storage_refuses_management_and_reads(env, monkeypatch, disable):
    from harness import device_grants
    if not disable and device_grants.storage_supported():
        pytest.skip('native unsupported-platform check')
    if disable:
        monkeypatch.setattr(device_grants, 'storage_supported', lambda: False)
    status, payload, _ = request(env[0], '/api/endpoint', [('X-Harness-Token', 'owner')])
    assert status == 200 and payload['device_auth'] == 'disabled'
    for path, method, body, headers in [
        ('/api/devices', 'GET', b'', [('X-Harness-Token', 'owner')]),
        ('/api/devices/enroll', 'POST', json.dumps({'label': 'x', 'grants': [
            {'operation': 'endpoint.read', 'resource_id': env[1].endpoint_id}]}).encode(), [('X-Harness-Token', 'owner')]),
        ('/api/devices/00000000-0000-0000-0000-000000000000/revoke', 'POST', b'{}', [('X-Harness-Token', 'owner')]),
        ('/api/device/endpoint', 'GET', b'', [('X-Harness-Device-Token', 'bad')]),
        ('/api/device/session?session_id=a', 'GET', b'', [('X-Harness-Device-Token', 'bad')]),
        ('/api/device/session/events?session_id=a', 'GET', b'', [('X-Harness-Device-Token', 'bad')]),
    ]:
        status, payload, head = request(env[0], path, headers, method, body)
        assert (status, payload) == (503, {'ok': False, 'code': 'device_unavailable'})
        assert b'Cache-Control: no-store' in head
    assert not env[1].directory.exists()
