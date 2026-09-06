"""Steering with an attached image must reach the model without dropping pixels.

Mid-turn steers inject as TEXT, so text-only pilots get sidecar transcription.
Vision-capable pilots must NEVER use a weaker sidecar VLM — they queue a
follow-up turn with native multimodal images instead.

Hermetic: monkeypatches vision helpers; no real model/vision call.
"""
import base64
import hashlib
from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.conversation import ConversationalSession
from harness.input_receipts import session_input_store


class _FakeResult:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGNocDgARAwQCgApDgYBH5bqCgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def image_session(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    image = uploads / "shot.png"
    image.write_bytes(PNG)
    session = ConversationalSession(HarnessConfig(
        driver="stub-oracle-v2", state_dir=str(tmp_path / "state"),
    ))
    session._input_upload_root = str(uploads)
    return session, image


def _retained(session, original):
    rows = session.input_receipts()
    assert len(rows) == 1
    row = rows[0]
    assert row["original_text"] == original
    attachment, = row["attachments"]
    assert attachment["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert session_input_store(session).attachment(attachment["ref"]) == PNG
    return row


def _assert_materialized(paths, image):
    assert len(paths) == 1
    assert paths[0] != str(image)
    assert Path(paths[0]).read_bytes() == PNG


def test_steer_with_image_transcribes_into_text(monkeypatch, image_session):
    s, image = image_session
    monkeypatch.setattr("harness.vision.session_supports_native_images", lambda _s: False)
    def transcribe(paths, sidecar=None):
        _assert_materialized(paths, image)
        return [_FakeResult(text="a red login button")]
    monkeypatch.setattr("harness.vision.transcribe_images", transcribe)
    assert s.steer_with_images("look at this", [str(image)]) == "enqueue_steer"
    receipt = _retained(s, "look at this")
    assert list(s._session_actions)[0].id == receipt["id"]
    drained = s.drain_steer()
    assert len(drained) == 1
    assert "look at this" in drained[0]
    assert "a red login button" in drained[0]  # the transcription, not a bare id


def test_steer_image_error_is_surfaced_not_dropped(monkeypatch, image_session):
    s, image = image_session
    monkeypatch.setattr("harness.vision.session_supports_native_images", lambda _s: False)
    def transcribe(paths, sidecar=None):
        _assert_materialized(paths, image)
        return [_FakeResult(error="unreadable")]
    monkeypatch.setattr("harness.vision.transcribe_images", transcribe)
    assert s.steer_with_images("check", [str(image)]) == "enqueue_steer"
    receipt = _retained(s, "check")
    assert list(s._session_actions)[0].id == receipt["id"]
    drained = s.drain_steer()
    assert drained and "could not be read" in drained[0]


def test_text_only_steer_still_works(image_session):
    s, _ = image_session
    assert s.steer_with_images("just text", []) == "enqueue_steer"
    assert s.drain_steer() == ["just text"]
    literal = "  keep me\n\t "
    assert s.steer_with_images(literal, []) == "enqueue_steer"
    action, = list(s._session_actions)
    assert action.text == literal
    events = list(s._check_and_inject_steer())
    assert any(e.kind == "steer" and e.data["text"] == literal for e in events)
    receipt = s.input_receipts()[-1]
    assert receipt["original_text"] == literal
    assert receipt["id"] == action.id
    assert receipt["status"] == "injected"
    assert s._history[-1]["content"] == literal
    assert s._history[-1]["input_id"] == receipt["id"]


def test_steer_native_vision_queues_prompt_skips_sidecar(monkeypatch, image_session):
    """gpt-5.6-luna-class pilots must not get a weaker sidecar paraphrase."""
    s, image = image_session
    called = {"transcribe": 0, "steer": 0}

    def _boom(*_a, **_k):
        called["transcribe"] += 1
        raise AssertionError("sidecar must not run for native vision steer")

    def _steer(text):
        called["steer"] += 1
        raise AssertionError("vision busy Enter must not enqueue_steer a notice")

    monkeypatch.setattr("harness.vision.session_supports_native_images", lambda _s: True)
    monkeypatch.setattr("harness.vision.transcribe_images", _boom)
    s.enqueue_steer = _steer
    action = s.steer_with_images("look at this", [str(image)])
    assert action == "enqueue_prompt"
    assert called["transcribe"] == 0
    assert called["steer"] == 0
    receipt = _retained(s, "look at this")
    queued, = s.list_prompts()
    assert queued["id"] == receipt["id"]
    assert queued["text"] == "look at this"
    assert queued["images"] == [receipt["attachments"][0]["ref"]]
    assert s.drain_steer() == []


def test_steer_native_vision_images_only_is_queue_only(monkeypatch, image_session):
    """Images-only on a vision pilot queues the placeholder; no steer chrome."""
    s, image = image_session

    monkeypatch.setattr("harness.vision.session_supports_native_images", lambda _s: True)
    action = s.steer_with_images("", [str(image)])
    assert action == "enqueue_prompt"
    receipt = _retained(s, "")
    queued, = s.list_prompts()
    assert queued["id"] == receipt["id"]
    assert queued["text"] == "(see attached image)"
    assert queued["images"] == [receipt["attachments"][0]["ref"]]
    text, paths = session_input_store(s).delivery_content(receipt["id"])
    assert text == ""
    _assert_materialized(paths, image)
    assert s.drain_steer() == []
