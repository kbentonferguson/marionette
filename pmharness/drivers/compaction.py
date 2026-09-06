"""Request-local drivers for an independently timed-out summarizer."""
from __future__ import annotations

from contextlib import ExitStack
from copy import copy, deepcopy


def compaction_driver(driver, model: str, resources: ExitStack):
    """Snapshot configuration, separating mutable sessions and request observers.

    The caller owns resources until the request exits, including after timeout.
    Model is a provider-local identifier, not a provider routing specification.
    Custom drivers must explicitly implement fork_for_compaction(model=...),
    returning independent request state and owning any request cleanup.
    """
    from .anthropic import AnthropicDriver
    from .bedrock import BedrockDriver
    from .cassette import CassetteDriver
    from .codex_responses import CodexResponsesDriver
    from .cursor_acp import CursorAcpDriver, WarmAcpSession
    from .cursor_cli import CursorCliDriver
    from .gemini import GeminiDriver
    from .moa import MoADriver
    from .openai_compat import OpenAICompatDriver
    from .stub import StubDriver
    from .stub_multiturn import StubMultiTurnDriver
    from .stub_v2 import StubV2Driver

    kind = type(driver)
    if kind is CassetteDriver:
        local = copy(driver)
        local._inner = compaction_driver(driver._inner, model, resources)
        with driver._record_lock:
            local._data = deepcopy(driver._data)
        # The record lock is intentionally shared: both writers own one file.
        return local
    if kind is MoADriver:
        if model:
            raise ValueError("MoA compaction has no single model to override")
        local = copy(driver)
        local.proposer_names = list(driver.proposer_names)
        local.proposer_drivers = [
            compaction_driver(child, "", resources) for child in driver.proposer_drivers
        ]
        local.aggregator_driver = compaction_driver(driver.aggregator_driver, "", resources)
        return local
    supported = (
        OpenAICompatDriver, AnthropicDriver, CodexResponsesDriver, GeminiDriver,
        BedrockDriver, CursorCliDriver, CursorAcpDriver,
        StubDriver, StubMultiTurnDriver, StubV2Driver,
    )
    if kind not in supported:
        factory = getattr(driver, "fork_for_compaction", None)
        if not callable(factory):
            raise TypeError(f"{kind.__name__} has no request-local compaction contract")
        return factory(model=model)

    local = copy(driver)
    if model:
        if not hasattr(local, "model"):
            raise ValueError(f"{kind.__name__} does not support a model override")
        local.model = model
    # FrozenRequest binds these closures to a different request's body/receipt.
    for attr in ("_request_body_observer", "_build_body", "_build_chat_body"):
        local.__dict__.pop(attr, None)
    if kind is OpenAICompatDriver:
        local.extra_headers = deepcopy(driver.extra_headers)
        local.extra_body = deepcopy(driver.extra_body)
    if kind in (OpenAICompatDriver, AnthropicDriver, CodexResponsesDriver):
        local._pool_provider = None
        local._pool_entry_id = None
    if kind is CursorCliDriver:
        local._harness_session_id = None
        local._native_chat_id = None
        local._bound_workspace = None
        local._bound_model = None
    if kind is CursorAcpDriver:
        old = driver._session
        local._session = WarmAcpSession(
            model=local.model, cwd=old.cwd, timeout=old.timeout,
            transport_factory=old._transport_factory, mode=old._mode_override,
        )
        local._session.mode = old.mode
        resources.callback(local._session.close)
        local._fallback = compaction_driver(driver._fallback, local.model, resources)
        local._interrupted = False
    return local
