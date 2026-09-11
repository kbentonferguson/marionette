from __future__ import annotations

import pytest

from harness.swarm_model_pin import resolve_swarm_model_pin
from harness.swarm_worker_allowlist import (
    allowed_model_ids_from_specs,
    resolve_swarm_worker_allowlist,
)


@pytest.fixture(autouse=True)
def _isolated_routing(monkeypatch):
    monkeypatch.setattr("harness.auto_registry.ensure_keyed_provider_registry_health", lambda: {"ready": True})
    monkeypatch.setattr("harness.swarm_model_pin._settings_enabled_specs", lambda: None)


def _rows():
    return [
        {
            "id": "agentic/openai-codex/gpt-5.6-luna",
            "adapter": "agentic",
            "adapter_model_name": "gpt-5.6-luna",
            "payload_defaults": {"provider": "openai-codex"},
        },
        {
            "id": "agentic/gpt-5.6-luna",
            "adapter": "agentic",
            "adapter_model_name": "gpt-5.6-luna",
            "payload_defaults": {"provider": "opencode-go"},
        },
    ]


def test_allowlist_emits_only_exact_provider_model_registry_id(monkeypatch):
    monkeypatch.setattr("harness.swarm_model_pin._registry_rows", lambda **_: _rows())
    monkeypatch.setattr(
        "harness.auto_registry.keyed_agentic_providers",
        lambda: {"openai-codex", "opencode-go"},
    )

    assert allowed_model_ids_from_specs(
        ["openai-codex:gpt-5.6-luna"]
    ) == ["agentic/openai-codex/gpt-5.6-luna"]


def test_allowlist_empty_ids_and_adapters_fail_closed(monkeypatch):
    monkeypatch.setattr("harness.swarm_model_pin._registry_rows", lambda **_: _rows())
    monkeypatch.setattr(
        "harness.swarm_worker_allowlist._agentic_eligible", lambda: True
    )
    monkeypatch.setattr(
        "harness.swarm_worker_allowlist._platform_locked_adapters", lambda: None
    )

    out = resolve_swarm_worker_allowlist(specs=["openrouter:not-live"])
    assert out["allowed_adapters"] == ["agentic"]
    assert out["allowed_model_ids"] == []


def test_explicit_pin_cannot_cross_provider_or_synthesize_id(monkeypatch):
    monkeypatch.setattr("harness.swarm_model_pin._registry_rows", lambda **_: _rows())
    monkeypatch.setattr(
        "harness.auto_registry.ensure_keyed_provider_registry_health",
        lambda: {"ready": True},
    )
    monkeypatch.setattr(
        "harness.auto_registry.keyed_agentic_providers",
        lambda: {"openai-codex", "opencode-go"},
    )

    out = resolve_swarm_model_pin(
        "openai-codex:gpt-5.6-luna", allowed_adapters=["agentic"]
    )
    assert out["resolved"] == "agentic/openai-codex/gpt-5.6-luna"
    assert out["pin_fields"]["provider"] == "openai-codex"

    missing = resolve_swarm_model_pin(
        "openrouter:gpt-5.6-luna", allowed_adapters=["agentic"]
    )
    assert missing["demoted"] is True
    assert "not in keyed worker registry" in missing["reason"]


def test_disabled_and_unkeyed_rows_are_not_pin_eligible(monkeypatch):
    rows = [
        {
            **_rows()[0],
            "enabled": False,
        },
        {
            "id": "agentic/openrouter/google/gemini-3.8-flash",
            "adapter": "agentic",
            "adapter_model_name": "google/gemini-3.8-flash",
            "payload_defaults": {"provider": "openrouter"},
        },
    ]
    monkeypatch.setattr("harness.swarm_model_pin._registry_rows", lambda **_: rows)
    monkeypatch.setattr(
        "harness.swarm_model_pin._settings_enabled_specs",
        lambda: [
            "openai-codex:gpt-5.6-luna",
            "openrouter:google/gemini-3.8-flash",
        ],
    )
    monkeypatch.setattr(
        "harness.auto_registry.keyed_agentic_providers",
        lambda: {"openai-codex"},
    )

    disabled = resolve_swarm_model_pin(
        "openai-codex:gpt-5.6-luna", allowed_adapters=["agentic"]
    )
    unkeyed = resolve_swarm_model_pin(
        "agentic/openrouter/google/gemini-3.8-flash", allowed_adapters=["agentic"]
    )
    assert disabled["demoted"] is True
    assert unkeyed["demoted"] is True


def test_canonical_id_uses_registry_provider_and_defaults(monkeypatch):
    row = {
        "id": "agentic/openrouter/google/gemini-3.8-flash",
        "adapter": "agentic",
        "adapter_model_name": "google/gemini-3.8-flash",
        "billing": "api",
        "payload_defaults": {
            "provider": "openrouter",
            "params": ["temperature", "max_tokens"],
        },
    }
    monkeypatch.setattr("harness.swarm_model_pin._registry_rows", lambda **_: [row])
    monkeypatch.setattr(
        "harness.swarm_model_pin._settings_enabled_specs",
        lambda: ["openrouter:google/gemini-3.8-flash"],
    )
    monkeypatch.setattr(
        "harness.auto_registry.keyed_agentic_providers",
        lambda: {"openrouter"},
    )

    out = resolve_swarm_model_pin(
        "agentic/openrouter/google/gemini-3.8-flash", allowed_adapters=["agentic"]
    )
    assert out["resolved"] == row["id"]
    assert out["pin_fields"]["provider"] == "openrouter"
    assert out["pin_fields"]["params"] == ["temperature", "max_tokens"]
