"""Frozen normalized inputs and supported provider JSON request bodies."""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Callable
from uuid import uuid4


def canonical_bytes(value: Any) -> bytes:
    # No default=str: unsupported values cannot silently compare as equal.
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


@dataclass(frozen=True)
class FrozenRequest:
    request_id: str
    payload: bytes = field(repr=False)
    method: Callable[..., Any] = field(repr=False, compare=False)

    boundary: Any = field(default=None, repr=False, compare=False)

    def wire_receipt(self) -> dict:
        return self.boundary.receipt() if self.boundary else {
            "wire_status": "unsupported", "model_status": "observed_only",
            "wire_scope": "none",
        }

    @classmethod
    def capture(cls, method: Callable[..., Any], value: Any,
                kwargs: dict, model: Any = None) -> FrozenRequest:
        # Model is driver-owned state, not a dispatch argument or wire guarantee.
        observed_model = model if isinstance(model, str) else None
        payload = canonical_bytes({'input': value, 'kwargs': kwargs,
                                   'model_observed': observed_model})
        frozen = json.loads(payload)
        method, boundary = _prepare_boundary(method, frozen['input'], frozen['kwargs'])
        return cls(uuid4().hex, payload, method, boundary)

    def materialize(self) -> tuple:
        value = json.loads(self.payload)
        return value['input'], value['kwargs']

    def receipt(self, value: Any, kwargs: dict) -> dict:
        source = json.loads(self.payload)
        actual = canonical_bytes({'input': value, 'kwargs': kwargs,
                                  'model_observed': source['model_observed']})
        ok = actual == self.payload
        return {
            'ok': ok, 'status': 'verified' if ok else 'mismatch',
            'reason': '' if ok else 'normalized_inputs',
            'scope': 'normalized_driver_inputs', 'wire_status': 'unverified',
            'model_status': 'observed_only', 'request_id': self.request_id,
            **self.wire_receipt(),
            'source_sha256': hashlib.sha256(self.payload).hexdigest(),
            'dispatch_sha256': hashlib.sha256(actual).hexdigest(),
            'message_count': len(value) if isinstance(value, list) else 0,
            'tool_count': len(kwargs.get('tools') or []),
        }


class _BodyBoundary:
    def __init__(self, body):
        self.payload = canonical_bytes(body)
        self.status = 'absent'
        self.last_digest = None
        self.attempts = 0

    def observe(self, data):
        self.attempts += 1
        try:
            actual = canonical_bytes(json.loads(data))
            self.last_digest = hashlib.sha256(actual).hexdigest()
            if actual != self.payload:
                self.status = 'mismatch'
            elif self.status != 'mismatch':
                self.status = 'verified'
        except (TypeError, ValueError, UnicodeError):
            self.status = 'mismatch'

    def receipt(self):
        return {
            'wire_status': self.status,
            'wire_scope': 'urllib_request_json_body',
            'model_status': 'frozen_body',
            'wire_source_sha256': hashlib.sha256(self.payload).hexdigest(),
            'wire_dispatch_sha256': self.last_digest,
            'wire_attempts': self.attempts,
        }


def _prepare_boundary(method, value, kwargs):
    # Exact classes only: subclasses may override transport or body construction.
    from pmharness.drivers.openai_compat import OpenAICompatDriver
    from pmharness.drivers.anthropic import AnthropicDriver
    from pmharness.drivers.codex_responses import CodexResponsesDriver

    owner = getattr(method, '__self__', None)
    name = getattr(method, '__name__', '')
    if type(owner) not in (OpenAICompatDriver, AnthropicDriver, CodexResponsesDriver):
        return method, None
    if name not in ('chat', 'chat_stream'):
        return method, None
    if getattr(method, '__func__', None) is not getattr(type(owner), name):
        return method, None
    # Preserve transport/client references and resolve credentials at send time.
    # Only the generation body is serialized; no auth headers enter the snapshot.
    driver = copy(owner)
    if type(owner) is OpenAICompatDriver:
        body = driver._build_chat_body(value, **kwargs, stream=name == 'chat_stream')
        builder = '_build_chat_body'
    else:
        body = driver._build_body(value, **kwargs)
        builder = '_build_body'
        if type(owner) is AnthropicDriver and name == 'chat_stream':
            body['stream'] = True
    boundary = _BodyBoundary(body)
    setattr(driver, builder, lambda *a, **kw: json.loads(boundary.payload))
    driver._request_body_observer = boundary.observe
    return getattr(driver, name), boundary
