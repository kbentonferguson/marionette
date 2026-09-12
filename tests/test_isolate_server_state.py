from __future__ import annotations

import json


def test_isolate_server_state_survives_empty_eval_catalog(monkeypatch, tmp_path):
    """xdist gw3: harness.server already imported, catalog.json unreadable.

    Isolate used to construct Session(qwen3-coder-30b), which raised
    ProviderError after load_catalog hit JSONDecodeError. PTY tests then
    failed at fixture setup.
    """
    import harness.server as server
    from tests.conftest import _isolate_server_session_state

    def boom():
        raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr("pmharness.registry.load_catalog", boom)
    for key in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CURSOR_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    _isolate_server_session_state(server, tmp_path, monkeypatch)
    assert server._session.driver.__class__.__name__ == "StubV2Driver"
