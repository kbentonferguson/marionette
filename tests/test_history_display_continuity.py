"""History-only cold attach must survive its first display event and reload."""
import copy
import threading
from types import SimpleNamespace

import pytest

from harness.api.attach import AttachServices, attach_view
from harness.config import HarnessConfig
from harness.conversation import ConversationalSession
from harness.session_runners import SessionRunnerRegistry
from harness.sessions import SessionStore, save_transcript
from test_display_transcript import MockPilot


def cold_attach(tmp_path, store, sid):
    config = HarnessConfig(driver="stub-oracle-v2", repo=str(tmp_path), state_dir=str(tmp_path))
    state = SimpleNamespace(pilot=None)
    svc = AttachServices(
        get_pilot=lambda: state.pilot,
        set_pilot=lambda pilot: setattr(state, "pilot", pilot),
        get_session=lambda: state,
        set_session=lambda session: None,
        cfg=config, runners=SessionRunnerRegistry(), sessions=store,
        pilot_swap_lock=threading.RLock(), bind_pilot_services=lambda pilot: None,
        build_conversational_pilot=lambda **kwargs: ConversationalSession(kwargs["config"]),
        sync_pilot_session_id=lambda: setattr(state.pilot, "harness_session_id", sid),
        sessions_state_dir=lambda: str(tmp_path), diag=lambda *args: None,
        apply_model_context_window=lambda: None,
        freeze_pilot_meters_into_boot_carry=lambda pilot: None,
        runner_config_snapshot=lambda: config,
    )
    return attach_view(sid, svc)


@pytest.mark.parametrize("fork", [False, True])
@pytest.mark.parametrize("legacy_list", [False, True])
def test_first_approval_preserves_history_prefix_after_cold_attach(tmp_path, fork, legacy_list):
    store = SessionStore(str(tmp_path / "sessions.json"))
    parent = store.create(title="Parent", repo=str(tmp_path))
    history = [
        {"role": "system", "content": "private system instructions"},
        {"role": "user", "content": "Review the patch"},
        {"role": "assistant", "content": "The patch is ready.", "phase": "final_answer"},
    ]
    save_transcript(str(tmp_path), parent["id"], history if legacy_list else {"history": history})
    sid = store.fork_at(parent["id"], 2, str(tmp_path))["id"] if fork else parent["id"]
    session = cold_attach(tmp_path, store, sid)
    session.register_pending_command_approval(command="echo approval", command_hash="a" * 64, action_id="approval")
    save_transcript(str(tmp_path), sid, session.export_transcript_data())
    reloaded = cold_attach(tmp_path, store, sid)
    display = reloaded.export_transcript_data()["display"]
    assert [(r["role"], r["text"]) for r in display if r.get("type") == "message"] == [
        ("user", "Review the patch"), ("assistant", "The patch is ready."),
    ]
    assert len(display) == 3
    assert display[-1]["type"] == "command_approval"
    assert reloaded.export_history() == history[1:]
    reloaded.load_history(reloaded.export_transcript_data())
    assert reloaded.export_display_transcript() == display


def test_projection_preserves_native_history_and_hides_internal_messages(tmp_path):
    history = [
        {"role": "system", "content": "private"},
        {"role": "user", "content": [
            {"type": "text", "text": "Review\nthis image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]},
        {"role": "assistant", "content": "Checking it.", "phase": "commentary", "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call-1", "content": "private tool result"},
        {"role": "user", "content": "(internal action result)"},
        {"role": "assistant", "content": "Ready.", "phase": "final_answer"},
    ]
    original = copy.deepcopy(history)
    session = ConversationalSession(HarnessConfig(driver="stub-oracle-v2", state_dir=str(tmp_path)))
    session.load_history(history)
    payload = session.export_transcript_data()
    assert payload["history"] == original[1:]
    assert history == original
    assert [r["text"] for r in payload["display"]] == ["Review\nthis image", "Checking it.", "Ready."]
    assert [r.get("phase") for r in payload["display"]] == [None, "commentary", "final_answer"]


def test_existing_activity_display_is_authoritative(tmp_path):
    session = ConversationalSession(HarnessConfig(driver="stub-oracle-v2", state_dir=str(tmp_path)))
    display = [{"type": "card", "id": "existing", "kind": "read_file", "result": {"ok": True}}]
    session.load_history({"history": [{"role": "user", "content": "Hidden raw context"}], "display": display})
    assert session.export_display_transcript() == display


def test_first_new_turn_preserves_fork_prefix(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.json"))
    parent = store.create(title="Parent", repo=str(tmp_path))
    save_transcript(str(tmp_path), parent["id"], {"history": [
        {"role": "user", "content": "Review the patch"},
        {"role": "assistant", "content": "The patch is ready."},
    ]})
    child = store.fork_at(parent["id"], 2, str(tmp_path))
    session = cold_attach(tmp_path, store, child["id"])
    session.pilot = MockPilot()
    events = list(session.send("Continue"))
    assert any(event.kind == "message" for event in events)
    save_transcript(str(tmp_path), child["id"], session.export_transcript_data())
    reloaded = cold_attach(tmp_path, store, child["id"])
    assert [row["text"] for row in reloaded.export_display_transcript()] == [
        "Review the patch", "The patch is ready.", "Continue", "Sure, I can help you with that.",
    ]
