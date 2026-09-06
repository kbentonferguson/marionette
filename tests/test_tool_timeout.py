from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from harness.tool_timeout import (
    TOOL_TIMEOUT,
    declared_timeout_ms,
    invoke_do,
    run_with_tool_deadline,
)


def _session():
    return SimpleNamespace(_cancel=threading.Event(), _interrupt_requested=False)


def test_inner_timeout_kinds_declare_nothing():
    for kind in (
        "run_command",
        "run_command_batch",
        "run_ipython",
        "run_swarm",
        "run_implement",
        "run_parallel",
        "route_task",
    ):
        assert declared_timeout_ms(kind) is None


def test_network_tools_declare_a_budget():
    for kind in (
        "web_fetch",
        "web_search",
        "read_pdf",
        "search_codegraph",
        "search_files",
        "call_mcp",
        "query_wiki",
    ):
        budget = declared_timeout_ms(kind)
        assert budget is not None
        assert budget > 0


def test_invoke_do_maps_only_this_wrapper_expiry(monkeypatch):
    monkeypatch.setenv("HARNESS_TOOL_TIMEOUT_WEB_SEARCH_MS", "40")
    session = _session()
    act = SimpleNamespace(kind="web_search")

    def _slow():
        session._cancel.wait(2.0)
        return (True, "ok", "late")

    triple = invoke_do(session, act, _slow)
    assert triple[0] is False
    assert triple[1] == TOOL_TIMEOUT
    assert "40ms" in triple[2]
    assert not session._cancel.is_set()


def test_user_stop_is_not_remapped_to_tool_timeout():
    session = _session()
    session._interrupt_requested = True
    session._cancel.set()

    def _already_cancelled():
        return (False, "cancelled", "user stop")

    result, timed_out = run_with_tool_deadline(
        session, "web_search", _already_cancelled, timeout_ms=20,
    )
    assert timed_out is None
    assert result[1] == "cancelled"


def test_inner_command_timeout_status_stays_honest():
    session = _session()

    def _command():
        return (False, "timeout", "command timed out")

    result, timed_out = run_with_tool_deadline(session, "run_command", _command)
    assert timed_out is None
    assert result == (False, "timeout", "command timed out")


def test_no_budget_does_not_arm_a_timer():
    session = _session()
    called = []

    def _fn():
        called.append(True)
        return (True, "ok", "x")

    result, timed_out = run_with_tool_deadline(session, "read_file", _fn)
    assert timed_out is None
    assert result[0] is True
    assert called == [True]


class _ControlledTimer:
    def __init__(self, interval, callback):
        self.callback = callback

    def start(self):
        pass

    def cancel(self):
        pass


def _controlled_timer(monkeypatch):
    timers = []

    def create(interval, callback):
        timer = _ControlledTimer(interval, callback)
        timers.append(timer)
        return timer

    monkeypatch.setattr("harness.tool_timeout.threading.Timer", create)
    return timers


def _generation_session():
    return SimpleNamespace(
        _cancel=threading.Event(), _interrupt_requested=False,
        _busy_meta=threading.Lock(), _busy_gen=1,
    )


def test_expired_previous_tool_cannot_cancel_new_generation(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()
    entered = threading.Event()
    release = threading.Event()
    results = []

    def blocked():
        entered.set()
        assert release.wait(2)
        return "old result"

    worker = threading.Thread(target=lambda: results.append(
        run_with_tool_deadline(session, "web_search", blocked, timeout_ms=10)
    ))
    worker.start()
    try:
        assert entered.wait(2)
        with session._busy_meta:
            session._busy_gen += 1
            session._cancel.clear()
        timers[0].callback()
        assert not session._cancel.is_set()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert results == [("old result", None)]


def test_previous_tool_cleanup_cannot_clear_new_generation(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()
    expired = threading.Event()
    release = threading.Event()
    results = []

    def blocked():
        timers[0].callback()
        expired.set()
        assert release.wait(2)
        return "old result"

    worker = threading.Thread(target=lambda: results.append(
        run_with_tool_deadline(session, "web_search", blocked, timeout_ms=10)
    ))
    worker.start()
    try:
        assert expired.wait(2)
        with session._busy_meta:
            session._busy_gen += 1
            session._cancel.clear()
            session._cancel.set()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert session._cancel.is_set()
    assert results == [("old result", 10)]


def test_callback_already_dispatched_cannot_cancel_after_cleanup(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()
    assert run_with_tool_deadline(
        session, "web_search", lambda: "done", timeout_ms=10,
    ) == ("done", None)
    # Timer.cancel cannot retract a callback that was already dispatched.
    timers[0].callback()
    assert not session._cancel.is_set()


@pytest.mark.parametrize("expire_first", [False, True])
def test_replaced_event_is_not_mutated_by_old_timer(monkeypatch, expire_first):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()
    old_cancel = session._cancel

    def replace():
        if expire_first:
            timers[0].callback()
        with session._busy_meta:
            session._cancel = threading.Event()
            session._cancel.set()
        if not expire_first:
            timers[0].callback()
        return "done"

    result = run_with_tool_deadline(session, "web_search", replace, timeout_ms=10)
    assert result == ("done", 10 if expire_first else None)
    assert session._cancel.is_set()
    assert old_cancel.is_set() == expire_first


def test_stop_after_expiry_survives_cleanup(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()

    def stop():
        timers[0].callback()
        with session._busy_meta:
            session._interrupt_requested = True
            session._cancel.set()
        return "stopped"

    assert run_with_tool_deadline(
        session, "web_search", stop, timeout_ms=10,
    ) == ("stopped", 10)
    assert session._cancel.is_set()


def test_exception_preserved_and_expiry_cleaned_up(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()

    def fail():
        timers[0].callback()
        raise ValueError("callback failure")

    with pytest.raises(ValueError, match="callback failure"):
        run_with_tool_deadline(session, "web_search", fail, timeout_ms=10)
    assert not session._cancel.is_set()
    timers[0].callback()
    assert not session._cancel.is_set()


def test_deadline_waits_for_noncooperative_callback(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()
    effects = []
    caller = threading.get_ident()

    def noncooperative():
        timers[0].callback()
        assert session._cancel.is_set()
        assert threading.get_ident() == caller
        effects.append("effect after expiry")
        return "late result"

    assert run_with_tool_deadline(
        session, "web_search", noncooperative, timeout_ms=10,
    ) == ("late result", 10)
    assert effects == ["effect after expiry"]


def test_generation_event_mutations_share_lifecycle_lock(monkeypatch):
    timers = _controlled_timer(monkeypatch)
    session = _generation_session()

    class CheckedEvent(threading.Event):
        def set(self):
            assert session._busy_meta.locked()
            super().set()

        def clear(self):
            assert session._busy_meta.locked()
            super().clear()

    session._cancel = CheckedEvent()

    def expire():
        timers[0].callback()
        assert session._cancel.is_set()
        return "done"

    assert run_with_tool_deadline(
        session, "web_search", expire, timeout_ms=10,
    ) == ("done", 10)
    assert not session._cancel.is_set()


@pytest.mark.parametrize("expire_first", [False, True])
def test_interrupt_publication_survives_concurrent_deadline_cleanup(monkeypatch, expire_first):
    from harness.conversation import ConversationalSession

    timers = _controlled_timer(monkeypatch)
    session = ConversationalSession.__new__(ConversationalSession)
    session._busy_meta = threading.Lock()
    session._busy = threading.Lock()
    session._busy.acquire()
    session._busy_gen = 1
    session._cancel = threading.Event()
    session._interrupt_requested = False
    session._session_job_ids = []
    session._local_jobs_lock = threading.Lock()
    session._local_jobs = {"child": {"status": "running"}}
    cancelled = threading.Event()
    resume_stop = threading.Event()
    stop_errors = []
    unlocked_hooks = []

    def assert_unlocked(name):
        acquired = session._busy_meta.acquire(timeout=1)
        assert acquired, name + " ran under _busy_meta"
        session._busy_meta.release()
        unlocked_hooks.append(name)

    def paused_cancel():
        assert_unlocked("cancel")
        ConversationalSession.cancel(session)
        cancelled.set()
        assert resume_stop.wait(2)

    def kill():
        assert_unlocked("process teardown")

    monkeypatch.setattr(session, "cancel", paused_cancel)
    monkeypatch.setattr(session, "cancel_local_job", lambda jid: assert_unlocked("child cancel"))
    monkeypatch.setattr(session, "_kill_owned_command_procs_on_interrupt", kill)
    monkeypatch.setattr(session, "_drain_session_jobs_dual_store", lambda ids: None)
    monkeypatch.setattr(session, "release_warm_acp", lambda **kw: assert_unlocked("ACP release"))
    monkeypatch.setattr(session, "_emit_stop_assistant_done", lambda: None)

    def stop():
        try:
            session.interrupt()
        except BaseException as exc:
            stop_errors.append(exc)

    stopper = threading.Thread(target=stop)

    def expire_then_stop():
        if expire_first:
            timers[0].callback()
        stopper.start()
        assert cancelled.wait(2)
        if not expire_first:
            timers[0].callback()
        return "done"

    try:
        assert run_with_tool_deadline(
            session, "web_search", expire_then_stop, timeout_ms=10,
        ) == ("done", 10 if expire_first else None)
        # Stop is paused immediately after real cancel(); cleanup has finished.
        assert session._cancel.is_set()
        assert session._interrupt_requested
    finally:
        resume_stop.set()
        stopper.join(2)
    assert not stopper.is_alive()
    assert not stop_errors
    assert unlocked_hooks == ["cancel", "child cancel", "process teardown", "ACP release"]
