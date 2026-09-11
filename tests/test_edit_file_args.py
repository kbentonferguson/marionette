"""Tests for the edit_file-loses-arguments fix: the native Anthropic driver must
get a generous output-token ceiling (not the 1024 default that truncated large
tool calls mid-arguments), and truncated streamed tool JSON must surface as
invalid (retryable) rather than silently empty."""
import os
import json


def test_native_anthropic_gets_max_tokens(monkeypatch):
    monkeypatch.delenv("HARNESS_MAX_TOKENS", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    import importlib
    import harness.providers as prov
    importlib.reload(prov)
    d = prov.build_pilot("anthropic:claude-opus-4-8")
    # Anthropic requires a ceiling, so the unlimited product default uses 32K.
    assert getattr(d, "max_tokens", 0) == 32000


def test_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_TOKENS", "16000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    import importlib
    import harness.providers as prov
    importlib.reload(prov)
    d = prov.build_pilot("anthropic:claude-opus-4-8")
    assert getattr(d, "max_tokens", 0) == 16000


def test_truncated_tool_json_surfaces_as_invalid():
    """A streamed tool call whose JSON args are truncated must be flagged invalid
    by parse_tool_calls (so the model retries) -- NOT silently dropped to {}."""
    from harness.pilot import parse_tool_calls
    # Simulate a truncated edit_file: arguments cut off mid-JSON.
    truncated = [{
        "id": "toolu_x",
        "type": "function",
        "function": {"name": "edit_file", "arguments": '{"path": "f.py", "old_str": "abc", "new_str": "def gh'},
    }]
    actions = parse_tool_calls(truncated)
    assert len(actions) == 1
    assert actions[0].kind == "__invalid__"
    assert "truncated" in actions[0].content.lower() or "invalid" in actions[0].content.lower()


def test_valid_edit_file_parses():
    from harness.pilot import parse_tool_calls
    valid = [{
        "id": "toolu_y",
        "type": "function",
        "function": {"name": "edit_file", "arguments": json.dumps({
            "path": "f.py", "old_str": "abc", "new_str": "xyz"})},
    }]
    actions = parse_tool_calls(valid)
    assert len(actions) == 1
    assert actions[0].kind == "edit_file"
    assert actions[0].path == "f.py"
    assert actions[0].old_str == "abc"
    assert actions[0].new_str == "xyz"
