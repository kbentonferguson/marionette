from dataclasses import replace
from threading import Lock
from types import SimpleNamespace

from harness.goal_mode import (
    GoalAssessment, GoalVerdict, assess_swarm_goal, assess_turn_swarm_goals,
    maybe_enqueue_session_goal_continuation,
    assess_session_goal_continuation, maybe_inject_goal_continue,
    reset_turn_goal_state, stash_turn_swarm_facts,
)
from harness.swarm_run_facts import CriterionFact, evaluate_acceptance_criteria, NOT_VERIFIED, VERIFIED
from harness.conversation import ConversationalSession
from harness.prompt_queue import PromptQueueMixin
from harness.session_goal import SessionGoal
from harness.send_loop_phases import drain_idle_turn
from pmharness.drivers.anthropic import AnthropicDriver
from test_goal_mode import _facts
from test_post_swarm_synthesis import (
    _SequencePilot, _pilot_envelope, _run_post_swarm_turn,
    _fake_execute_turn_actions,
)


def evaluated(status=None, evidence='tests/test_goal_mode.py:40', job='job_test'):
    rows = [] if status is None else [{
        'type': 'verification', 'execution_ref': {'job_id': job},
        'acceptance_criteria': [{'criterion': 'tests pass', 'status': status, 'evidence': evidence}],
    }]
    return _facts(*evaluate_acceptance_criteria(['tests pass'], rows, 'job_test'))


def test_missing_evidence_blocks_without_claiming_complete():
    facts = evaluated()
    assert facts.criteria[0].status == NOT_VERIFIED
    assert assess_swarm_goal(facts).verdict == GoalVerdict.BLOCKED


def test_same_job_refresh_replaces_stale_snapshot():
    session = SimpleNamespace()
    stash_turn_swarm_facts(session, evaluated())
    stash_turn_swarm_facts(session, evaluated('passed'))
    assert len(session._turn_swarm_facts) == 1
    assert assess_turn_swarm_goals(session._turn_swarm_facts).verdict == GoalVerdict.COMPLETE
    assert assess_turn_swarm_goals([evaluated(), evaluated('passed')]).verdict == GoalVerdict.COMPLETE


def test_other_job_pass_cannot_erase_gap():
    assert assess_turn_swarm_goals([
        evaluated(), replace(evaluated('passed'), job_id='other'),
    ]).verdict == GoalVerdict.BLOCKED
    assert evaluated('passed', job='other').criteria[0].status == NOT_VERIFIED


def test_repeated_failure_ignores_new_job_and_metadata_resets_on_user():
    session = SimpleNamespace(_history=[])
    reset_turn_goal_state(session)
    stash_turn_swarm_facts(session, evaluated('failed'))
    assert maybe_inject_goal_continue(session, iters=0, cap=20)
    stash_turn_swarm_facts(session, replace(evaluated('failed'), job_id='new', artifact_total=99))
    assert not maybe_inject_goal_continue(session, iters=1, cap=20)
    reset_turn_goal_state(session)
    stash_turn_swarm_facts(session, evaluated('failed'))
    assert maybe_inject_goal_continue(session, iters=0, cap=20)


def test_blocked_sticky_goal_does_not_fall_through():
    result = assess_session_goal_continuation(
        goal_active=True, budget_exceeded=False, gate_blocks_idle=False,
        swarm_assessment=GoalAssessment(GoalVerdict.BLOCKED, 'missing evidence'),
    )
    assert result.verdict == GoalVerdict.BLOCKED


def test_goal_control_is_not_human_authored():
    session = SimpleNamespace(_history=[], _turn_swarm_facts=[evaluated('failed')])
    assert maybe_inject_goal_continue(session, iters=0, cap=2)
    assert session._history[-1]['role'] == 'system'


def test_completed_audit_missing_citation_does_not_dispatch_again(monkeypatch):
    calls = []
    def execute(session, **kwargs):
        calls.append(1)
        result = yield from _fake_execute_turn_actions(session, **kwargs)
        stash_turn_swarm_facts(session, evaluated())
        return result
    pilot = _SequencePilot([
        _pilot_envelope(actions=[{'kind': 'run_swarm', 'goal': 'audit'}]),
        _pilot_envelope(say='The audit found a stale assessment in harness/goal_mode.py. The compound criterion remains unverified because the validator has no matching citation.'),
        _pilot_envelope(say='Unnecessary extra verification.'),
        _pilot_envelope(say='Still no matching citation.'),
    ])
    session, events = _run_post_swarm_turn(monkeypatch, pilot, execute_actions=execute)
    assert len(pilot.calls) == 2
    assert len(calls) == 1
    assert events[-1].kind == 'assistant_done'
    assert assess_turn_swarm_goals(session._turn_swarm_facts).verdict == GoalVerdict.BLOCKED


def test_real_failure_control_reaches_provider_system(monkeypatch):
    def execute(session, **kwargs):
        result = yield from _fake_execute_turn_actions(session, **kwargs)
        stash_turn_swarm_facts(session, evaluated('failed'))
        return result
    pilot = _SequencePilot([
        _pilot_envelope(actions=[{'kind': 'run_swarm', 'goal': 'check tests'}]),
        _pilot_envelope(say='A test failed.'),
        _pilot_envelope(say='The failed test still needs correction.'),
        _pilot_envelope(say='Unnecessary retry.'),
    ])
    session, events = _run_post_swarm_turn(monkeypatch, pilot, execute_actions=execute)
    assert len(pilot.calls) == 3
    assert '[goal-mode]' in pilot.calls[2]['kwargs']['system']
    assert all(m['role'] != 'user' for m in session._history if '[goal-mode]' in str(m.get('content', '')))
    assert events[-1].kind == 'assistant_done'


def test_unknown_blocked_and_uncited_failure_are_not_actionable():
    for status, evidence in [('blocked', 'tests/a.py:1'), ('failed', ''), ('passed', '')]:
        assert assess_swarm_goal(evaluated(status, evidence)).verdict == GoalVerdict.BLOCKED


def test_contradictory_records_stay_unverified_and_do_not_dispatch():
    records = [{'criterion': 'tests pass', 'status': status, 'evidence': 'tests/a.py:1'}
               for status in ('passed', 'failed')]
    artifacts = [{'type': 'verification', 'execution_ref': {'job_id': 'job_test'},
                  'acceptance_criteria': records}]
    facts = _facts(*evaluate_acceptance_criteria(['tests pass'], artifacts, 'job_test'))
    assert facts.criteria[0].status == NOT_VERIFIED
    assert assess_swarm_goal(facts).verdict == GoalVerdict.BLOCKED


def test_sticky_goal_cannot_repeat_inner_correction():
    enqueued = []
    session = SimpleNamespace(
        _history=[], _turn_swarm_facts=[evaluated('failed')],
        config=SimpleNamespace(goal_auto_continue=True),
        _session_goal=SessionGoal().set('Fix tests'),
        enqueue_goal_continuation=lambda: enqueued.append(1),
    )
    assert maybe_inject_goal_continue(session, iters=0, cap=2)
    assessment = maybe_enqueue_session_goal_continuation(session, gate_blocks_idle=False)
    assert assessment.verdict == GoalVerdict.BLOCKED
    assert not enqueued


def test_queued_goal_control_keeps_system_authorship(tmp_path):
    class Session(PromptQueueMixin):
        pass
    session = Session()
    session._prompt_queue = []
    session._prompt_queue_lock = Lock()
    session._prompt_queue_path = str(tmp_path / 'queue.json')
    session._session_goal = SessionGoal().set('Fix tests')
    session._persist_session_goal = lambda: None
    session._history = [{'role': 'assistant', 'content': 'Checking.'}]
    session.drain_steer = lambda: []
    session.config = SimpleNamespace(driver='stub')
    session._goal_mode_corrected = {'tests pass'}
    ConversationalSession.enqueue_goal_continuation(session)
    assert session.list_prompts()[0].get('source') == 'goal_mode'
    session._load_prompt_queue()
    events = list(drain_idle_turn(session, user_message='Fix tests', step=0, swarms=0,
                                  turn_prose=[], turn_findings=[]))
    assert not any(event.kind == 'queued_prompt' for event in events)
    assert session._history[-1]['role'] == 'system'
    assert session._goal_mode_corrected == {'tests pass'}


def test_mixed_gap_and_failure_nudge_targets_only_failure():
    session = SimpleNamespace(_history=[], _turn_swarm_facts=[replace(
        evaluated('failed'), criteria=evaluated('failed').criteria + (
            CriterionFact('qualitative audit summary', NOT_VERIFIED, 'no matching citation'),
        ),
    )])
    assert maybe_inject_goal_continue(session, iters=0, cap=2)
    assert 'tests pass' in session._history[-1]['content']
    assert 'qualitative audit summary' not in session._history[-1]['content']


def test_resume_keeps_correction_ledger(monkeypatch):
    def execute(session, **kwargs):
        result = yield from _fake_execute_turn_actions(session, **kwargs)
        stash_turn_swarm_facts(session, evaluated('failed'))
        return result
    pilot = _SequencePilot([
        _pilot_envelope(actions=[{'kind': 'run_swarm', 'goal': 'check'}]),
        _pilot_envelope(say='A test failed.'),
        _pilot_envelope(say='The test remains failed.'),
        _pilot_envelope(say='Refreshed results still show the same failed test.'),
    ])
    session, _ = _run_post_swarm_turn(monkeypatch, pilot, execute_actions=execute)
    session._history.append({'role': 'user', 'content': '(background result available)'})
    facts = list(session._turn_swarm_facts)
    events = list(session._send_locked_inner('', resume=True))
    assert session._turn_swarm_facts == facts
    assert session._goal_mode_corrected == {'tests pass'}
    assert len(pilot.calls) == 4
    assert events[-1].kind == 'assistant_done'
    exported = session.export_transcript_data()
    controls = [m for m in exported['history'] if m.get('source') == 'goal_mode']
    assert controls and all(m['role'] == 'system' for m in controls)
    session.load_history(exported)
    assert [m for m in session.export_history() if m.get('source') == 'goal_mode'] == controls


def test_goal_control_wire_has_user_trigger_without_changing_history(monkeypatch):
    def execute(session, **kwargs):
        result = yield from _fake_execute_turn_actions(session, **kwargs)
        stash_turn_swarm_facts(session, evaluated('failed'))
        return result
    pilot = _SequencePilot([
        _pilot_envelope(actions=[{'kind': 'run_swarm', 'goal': 'check'}]),
        _pilot_envelope(say='A test failed.'),
        _pilot_envelope(say='The test needs correction.'),
    ])
    session, _ = _run_post_swarm_turn(monkeypatch, pilot, execute_actions=execute)
    request = pilot.calls[-1]
    # Request construction only: no network call or API key.
    driver = AnthropicDriver('test', 'claude-test', enable_prompt_cache=False)
    body = driver._build_body(request['messages'], None, request['kwargs']['system'])
    assert body['messages'][-1]['role'] == 'user'
    assert '[goal-mode]' in body['system']
    assert all(m['role'] == 'system' for m in session.export_history()
               if m.get('source') == 'goal_mode')
