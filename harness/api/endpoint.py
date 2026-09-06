"""Authenticated endpoint discovery and owner protocol fencing."""
from __future__ import annotations

from harness.endpoint_identity import PROTOCOL_VERSION


def validate_request(headers, path, identity_factory):
    if 'X-Harness-Device-Token' in headers:
        return 403, {'ok': False, 'code': 'device_auth_disabled',
                     'error': 'Device enrollment and scoped access are not supported.'}
    if 'X-Harness-Protocol' not in headers:
        return None
    if headers.get('X-Harness-Protocol') != str(PROTOCOL_VERSION):
        return 426, {'ok': False, 'code': 'unsupported_protocol',
                     'supported_versions': [PROTOCOL_VERSION],
                     'error': 'Use X-Harness-Protocol: 1; reconnect via GET /api/endpoint.'}
    try:
        identity = identity_factory()
    except Exception:
        return 503, {'ok': False, 'code': 'endpoint_unavailable',
                     'error': 'Endpoint identity unavailable; restart the local backend.'}
    return identity.validate(headers, discovery=path == '/api/endpoint')


def get_endpoint(identity_factory):
    try:
        from .devices import describe
        return 200, describe(identity_factory())
    except Exception:
        return 503, {'ok': False, 'code': 'endpoint_unavailable',
                     'error': 'Endpoint identity unavailable; restart the local backend.'}
