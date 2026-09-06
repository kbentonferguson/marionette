"""Bounded device JSON reads and owner-only enrollment management."""
import json
import re

from harness import device_grants
from harness.device_grants import DeviceDenied, DeviceUnavailable
from harness.device_policy import enrollment_grants, resolve_request, session_record

MANAGEMENT = re.compile(r'/api/devices/([0-9a-f-]{36})/revoke\Z')
IDENTITY_HEADERS = ('Host', 'Origin', 'X-Harness-Token', 'X-Harness-Device-Token',
                    'X-Harness-Protocol', 'X-Harness-Endpoint', 'X-Harness-Boot',
                    'Content-Length', 'Transfer-Encoding', 'Authorization')


def ambiguous_headers(headers):
    return any(len(headers.get_all(name, [])) > 1 for name in IDENTITY_HEADERS)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _body(handler):
    if 'Transfer-Encoding' in handler.headers:
        raise ValueError()
    size = handler.headers.get('Content-Length', '0')
    if not size.isascii() or not size.isdecimal() or len(size) > 6 or not 0 < int(size) <= 16384:
        raise ValueError()
    raw = handler.rfile.read(int(size))
    if len(raw) != int(size):
        raise ValueError()
    body = json.loads(raw, object_pairs_hook=_object)
    if not isinstance(body, dict):
        raise ValueError()
    return body


def handle(handler, store_factory, identity_factory, sessions_path, ring_lookup):
    """Return True after handling; device mode can never reach owner dispatch."""
    device = 'X-Harness-Device-Token' in handler.headers
    management = handler.path == '/api/devices' or handler.path.startswith('/api/devices/')
    if not device and not management:
        return False
    handler.close_connection = True
    handler._device_no_store = True
    try:
        if device:
            # Unknown routes fail before initialization, authentication or resource access.
            op, rid, since, generation = resolve_request(handler.command, handler.path, '')
            if 'Transfer-Encoding' in handler.headers or handler.headers.get('Content-Length', '0') != '0':
                raise ValueError()
        elif not handler._token_ok():
            raise DeviceDenied()
        handler.connection.settimeout(2)
        try:
            identity = identity_factory()
        except Exception as exc:
            raise DeviceUnavailable() from exc
        failure = None
        if not device:
            from .endpoint import validate_request
            failure = validate_request(handler.headers, handler.path, lambda: identity)
        if failure:
            handler._send(failure[0], json.dumps(failure[1]))
            return True
        try:
            store = store_factory()
            if store.endpoint_id != identity.endpoint_id:
                raise DeviceUnavailable()
        except Exception as exc:
            raise DeviceUnavailable() from exc
        if device:
            if op == 'endpoint.read':
                rid = identity.endpoint_id
            with store.transaction() as db:
                principal = store.authenticate(db, handler.headers['X-Harness-Device-Token'])
                failure = identity.validate(handler.headers, discovery=op == 'endpoint.read')
                if failure:
                    handler._send(failure[0], json.dumps(failure[1]))
                    return True
                matches = [g for g in principal.grants if g.operation == op and g.resource_id == rid]
                if len(matches) != 1:
                    raise DeviceDenied()
                if op == 'endpoint.read':
                    payload = describe(identity)
                else:
                    metadata, binding = session_record(sessions_path(), rid)
                    if binding != matches[0].binding:
                        raise DeviceDenied()
                    if op == 'session.read':
                        payload = {'ok': True, 'session': metadata}
                    else:
                        ring = ring_lookup(rid, generation)
                        if ring is None:
                            payload = {'ok': False, 'code': 'ring_miss', 'session_id': rid, 'events': []}
                        else:
                            if ring.session_id != rid:
                                raise DeviceDenied()
                            payload = ring.since(since)
                            if since > payload['cursor']:
                                payload.update(ok=False, code='future_cursor', events=[])
                            else:
                                payload['ok'] = not payload['gap']
                                if payload['gap']:
                                    payload['code'] = 'cursor_gap'
                        # Do not emit data if the persistent binding changed during lookup.
                        if session_record(sessions_path(), rid)[1] != binding:
                            raise DeviceDenied()
                encoded = json.dumps(payload)
                if len(encoded.encode()) > 1048576:
                    handler._send(413, json.dumps({'ok': False, 'code': 'device_response_too_large'}))
                else:
                    handler._send(200, encoded)
        else:
            match = MANAGEMENT.fullmatch(handler.path)
            if handler.command == 'GET' and handler.path == '/api/devices':
                if 'Transfer-Encoding' in handler.headers or handler.headers.get('Content-Length', '0') != '0':
                    raise ValueError()
                with store.transaction() as db:
                    payload = {'ok': True, 'devices': store.list(db)}
                status = 200
            elif handler.command == 'POST' and handler.path == '/api/devices/enroll':
                body = _body(handler)
                if set(body) != {'label', 'grants'} or not isinstance(body['label'], str) or not 1 <= len(body['label']) <= 100:
                    raise ValueError()
                grants = enrollment_grants(body['grants'], identity.endpoint_id, sessions_path())
                with store.transaction() as db:
                    payload = store.enroll(db, body['label'], grants)
                status = 201
            elif handler.command == 'POST' and match:
                if _body(handler):
                    raise ValueError()
                with store.transaction() as db:
                    found = store.revoke(db, match[1])
                status, payload = (200, {'ok': True}) if found else (404, {'ok': False})
            else:
                raise DeviceDenied()
            handler._send(status, json.dumps(payload))
    except DeviceDenied:
        handler._send(403, json.dumps({'ok': False, 'code': 'device_denied'}))
    except (ValueError, UnicodeError):
        handler._send(400, json.dumps({'ok': False, 'code': 'invalid_device_request'}))
    except DeviceUnavailable:
        handler._send(503, json.dumps({'ok': False, 'code': 'device_unavailable'}))
    return True


def describe(identity):
    if not device_grants.storage_supported():
        return identity.describe()
    return {**identity.describe(), 'device_auth': 'bounded_read_v1',
            'device_operations': ['endpoint.read', 'session.read', 'session.events.read'],
            'device_events': 'retained_chat_ring_json', 'device_live_sse': False}
