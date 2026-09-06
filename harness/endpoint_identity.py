"""Non-secret installation identity and versioned local endpoint fencing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import uuid

_IDENTITY_LOCK = threading.Lock()
PROTOCOL_VERSION = 1


class EndpointIdentity:
    def __init__(self, path: Path, boot_id: str):
        if not boot_id:
            raise ValueError('Puppetmaster host boot identity unavailable')
        self.boot_id = boot_id
        with _IDENTITY_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    json.dump({'endpoint_id': str(uuid.uuid4())}, output)
                    output.flush()
                    os.fsync(output.fileno())
            # Corrupt/partially written identity fails closed, never rotates silently.
            self.endpoint_id = str(uuid.UUID(json.loads(path.read_text())['endpoint_id']))

    def describe(self) -> dict:
        return {
            'ok': True,
            'protocol_version': PROTOCOL_VERSION,
            'supported_versions': [PROTOCOL_VERSION],
            'endpoint_id': self.endpoint_id,
            'boot_id': self.boot_id,
            'capabilities': ['endpoint_fence_v1', 'session_replay_fence_v1'],
            'device_auth': 'disabled',
        }

    def validate(self, headers, *, discovery: bool = False):
        if headers.get('X-Harness-Protocol') != str(PROTOCOL_VERSION):
            return 426, {'ok': False, 'code': 'unsupported_protocol',
                         'supported_versions': [PROTOCOL_VERSION],
                         'error': 'Use X-Harness-Protocol: 1; reconnect via GET /api/endpoint.'}
        for header, expected, code in (
            ('X-Harness-Endpoint', self.endpoint_id, 'endpoint_mismatch'),
            ('X-Harness-Boot', self.boot_id, 'boot_mismatch'),
        ):
            value = headers.get(header)
            if value != expected and not (discovery and value is None):
                return 409, {'ok': False, 'code': code,
                             'error': 'Reconnect via GET /api/endpoint and reset replay cursors.'}
        return None
