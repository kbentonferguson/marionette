"""Same-session prompt persistence; unscoped legacy files remain read-only."""
import json
import os
import tempfile
from pathlib import Path

from harness.config import HarnessConfig
from harness.conversation import ConversationalSession


def _session(state_dir):
    session = ConversationalSession(HarnessConfig(state_dir=state_dir))
    session.harness_session_id = "persistence-test"
    return session


def test_enqueue_survives_restart_in_order():
    d = tempfile.mkdtemp()
    s = _session(d)
    s.enqueue_prompt("first")
    images = [str(Path(d) / name) for name in ('a.png', 'b.png')]
    for path in images:
        Path(path).write_bytes(b'original test image')
    s.enqueue_prompt("second", images=images, model="glm-5.2", upload_root=d)

    s2 = _session(d)
    assert s2.list_prompts() == []
    items = s2.held_prompts()
    assert [i["text"] for i in items] == ["first", "second"]
    assert items[0]["images"] == []
    assert items[0].get("model", "") == ""
    assert all(ref.startswith("input:persistence-test:") for ref in items[1]["images"])
    assert len(s2.input_receipts()[1]["attachments"]) == 2
    assert items[1]["model"] == "glm-5.2"


def test_pop_reflected_after_reload():
    d = tempfile.mkdtemp()
    s = _session(d)
    s.enqueue_prompt("one")
    s.enqueue_prompt("two")
    popped = s._pop_next_prompt()
    assert popped["text"] == "one"

    s2 = _session(d)
    assert [i["text"] for i in s2.held_prompts()] == ["two"]


def test_remove_reflected_after_reload():
    d = tempfile.mkdtemp()
    s = _session(d)
    a = s.enqueue_prompt("keep")
    b = s.enqueue_prompt("drop")
    assert s.remove_prompt(b["id"]) is True

    s2 = _session(d)
    texts = [i["text"] for i in s2.held_prompts()]
    assert texts == ["keep"]
    assert a["text"] == "keep"


def test_clear_reflected_after_reload():
    d = tempfile.mkdtemp()
    s = _session(d)
    s.enqueue_prompt("a")
    s.enqueue_prompt("b")
    assert s.clear_prompts() == 2

    s2 = _session(d)
    assert s2.list_prompts() == []


def test_corrupt_legacy_file_remains_available_for_review():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "prompt_queue.json"), "w", encoding="utf-8") as f:
        f.write("{ this is not valid json ]]")

    s = _session(d)
    assert s.list_prompts() == []
    assert s.prompt_queue_recovery()[0]["content"] == "{ this is not valid json ]]"
    # The separate session-owned queue is usable without overwriting legacy data.
    s.enqueue_prompt("fresh")
    assert [i["text"] for i in s.list_prompts()] == ["fresh"]


def test_legacy_items_are_not_automatically_imported():
    d = tempfile.mkdtemp()
    payload = {"queue": [{"id": "x", "text": "good", "images": []},
                         "not-a-dict",
                         {"id": "y"}]}  # missing text key
    with open(os.path.join(d, "prompt_queue.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)

    s = _session(d)
    assert s.list_prompts() == []
    assert json.loads(s.prompt_queue_recovery()[0]["content"]) == payload


def test_empty_legacy_queue_does_not_raise_recovery_notice(tmp_path):
    legacy = tmp_path / "prompt_queue.json"
    original = b'{ "queue": [] }\n'
    legacy.write_bytes(original)
    s = _session(str(tmp_path))
    assert s.prompt_queue_recovery() == []
    assert legacy.read_bytes() == original


def test_unknown_legacy_fields_remain_recoverable(tmp_path):
    legacy = tmp_path / "prompt_queue.json"
    original = '{"queue": [], "draft": "keep this original"}'
    legacy.write_text(original)
    s = _session(str(tmp_path))
    assert s.prompt_queue_recovery()[0]["content"] == original
    assert legacy.read_text() == original
