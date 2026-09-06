import json
from dataclasses import replace

import pytest
from puppetmaster.attempts import ExecutionAttempt, UsageObservation, LedgerConflictError
from puppetmaster.models import AgentRun, TaskStatus

from types import SimpleNamespace

from puppetmaster.models import Artifact, ArtifactType, Task
from puppetmaster.store_factory import create_store

from harness.job_evidence import project_job_evidence
from harness.api.jobs import make_job_services
from harness.job_scoping import job_label_for_session, stamp_task_payload
from harness.api.job_evidence import get_job_evidence


def setup_job(tmp_path, session='session-a'):
    repo = tmp_path / 'repo'
    repo.mkdir(exist_ok=True)
    store = create_store('sqlite', tmp_path / 'state')
    job = store.create_job('SECRET PROMPT', label=job_label_for_session(session))
    task = Task(job_id=job.id, role='test', instruction='SECRET PROMPT',
                payload=stamp_task_payload({}, session_id=session, cwd=str(repo)))
    store.save_task(task)
    svc = make_job_services(cfg=SimpleNamespace(repo=str(repo)),
        sessions=SimpleNamespace(active='session-a'),
        get_pilot=lambda: SimpleNamespace(harness_session_id='session-a'),
        get_session=lambda: SimpleNamespace(state=lambda: SimpleNamespace(store=store)))
    from puppetmaster.state import state_identity
    qs = {'state_id': [state_identity(store.root)], 'job_id': [job.id], 'session_id': ['session-a'], 'repo': [str(repo)], 'source': ['harness']}
    return store, job, task, svc, qs


def test_real_store_artifacts_are_not_success_proof(tmp_path):
    store, job, task, svc, qs = setup_job(tmp_path)
    store.save_artifact(Artifact(job_id=job.id, task_id=task.id, type=ArtifactType.FINDING,
        created_by='worker', payload={'claim': 'SECRET PROMPT'}, confidence=1, evidence=['SECRET TOKEN']))
    store.save_artifact(Artifact(job_id=job.id, task_id=task.id, type=ArtifactType.GATE,
        created_by='worker', payload={'gate': 'test', 'passed': False, 'stderr': 'SECRET TOKEN'}, confidence=1, evidence=['fixture failing test']))
    code, data = get_job_evidence(qs, svc)
    assert code == 200
    assert data['job_ref']['job_id'] == job.id
    assert data['job_ref']['state_id'].startswith('state_')
    assert data['artifacts'][0]['presence'] == 'recorded'
    assert any(a['check_result'] == 'failed' for a in data['artifacts'])
    assert data['cost']['selected_usd'] is None
    assert data['links']['request'] is None
    assert data['links']['attempts'] == 'unavailable'
    assert 'SECRET' not in json.dumps(data)


def test_foreign_session_refused_before_artifacts(tmp_path):
    store, _, _, svc, qs = setup_job(tmp_path, 'session-b')
    store.list_artifacts = lambda _: (_ for _ in ()).throw(AssertionError('foreign read'))
    assert get_job_evidence(qs, svc) == (200, {
        'code': 'job_evidence_unavailable',
        'message': 'Evidence is unavailable for this job in the active workspace and session.',
    })


def test_wrong_workspace_source_and_stale_session_refused(tmp_path):
    _, _, _, svc, qs = setup_job(tmp_path)
    for key, value in [('repo', '/foreign'), ('source', 'cli'), ('session_id', 'session-b')]:
        status, data = get_job_evidence({**qs, key: [value]}, svc)
        assert status == 200
        assert data['code'] == 'job_evidence_unavailable'


def test_missing_artifacts_explicit(tmp_path):
    _, _, _, svc, qs = setup_job(tmp_path)
    code, data = get_job_evidence(qs, svc)
    assert code == 200
    assert data['artifacts'] == []
    assert 'No artifacts recorded.' in data['missing']


def test_mixed_session_tasks_are_refused_before_artifacts(tmp_path):
    store, job, _, svc, qs = setup_job(tmp_path)
    store.save_task(Task(job_id=job.id, role='test', instruction='private',
        payload=stamp_task_payload({}, session_id='session-b', cwd=qs['repo'][0])))
    store.list_artifacts = lambda _: (_ for _ in ()).throw(AssertionError('foreign read'))
    assert get_job_evidence(qs, svc) == (200, {
        'code': 'job_evidence_unavailable',
        'message': 'Evidence is unavailable for this job in the active workspace and session.',
    })


def test_read_failure_is_not_empty_evidence(tmp_path):
    store, _, _, svc, qs = setup_job(tmp_path)
    store.list_artifacts = lambda _: (_ for _ in ()).throw(OSError('SECRET'))
    status, data = get_job_evidence(qs, svc)
    assert status == 503
    assert 'SECRET' not in json.dumps(data)


def test_explicit_zero_cost_is_distinct_from_missing_cost(tmp_path):
    from dataclasses import replace
    from puppetmaster.cost import PRICING_SOURCE_TERMINAL
    from puppetmaster.models import JobStatus
    from harness.job_evidence import project_job_evidence

    store, job, task, _, _ = setup_job(tmp_path)
    receipt = {'job_id': job.id, 'pricing_source': PRICING_SOURCE_TERMINAL,
        'token_usage': {}, 'tasks': [], 'actual_cost': {
            'total_marginal_cost_usd': 0, 'priced_tasks': 1, 'unpriced_tasks': 0}}
    frozen = replace(job, status=JobStatus.COMPLETE, cost_receipt=receipt)
    data = project_job_evidence(store, frozen, [task])
    assert data['cost']['selected_usd'] == 0
    assert data['cost']['total_attempt_usd'] is None
    for value in (None, float('nan'), -1, True):
        receipt['actual_cost']['total_marginal_cost_usd'] = value
        assert project_job_evidence(store, frozen, [task])['cost']['selected_usd'] is None


def test_active_session_switch_during_read_discards_result(tmp_path):
    store, _, _, svc, qs = setup_job(tmp_path)
    original = store.list_artifacts
    def switch(job_id):
        svc.sessions.active = 'session-b'
        return original(job_id)
    store.list_artifacts = switch
    assert get_job_evidence(qs, svc) == (200, {
        'code': 'job_evidence_unavailable',
        'message': 'Evidence is unavailable for this job in the active workspace and session.',
    })


def test_evidence_read_does_not_change_store_files(tmp_path):
    import hashlib
    store, _, _, svc, qs = setup_job(tmp_path)
    def snapshot():
        return {str(p.relative_to(store.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in store.root.rglob('*') if p.is_file()}
    before = snapshot()
    assert get_job_evidence(qs, svc)[0] == 200
    assert snapshot() == before


def test_http_route_uses_scoped_projection(tmp_path):
    from harness.http_routes import build_get_routes
    _, job, _, svc, qs = setup_job(tmp_path)
    class Services:
        def __getattr__(self, name):
            return lambda *args: svc
    responses = []
    handler = SimpleNamespace(_send=lambda status, payload: responses.append((status, json.loads(payload))))
    routes = build_get_routes(Services())
    routes['/api/jobs/evidence'](handler, None, qs)
    assert responses[0][0] == 200
    assert responses[0][1]['job_ref']['job_id'] == job.id


def test_selected_state_collision_never_reads_other_store(tmp_path, monkeypatch):
    from puppetmaster import models
    from puppetmaster.state import state_identity
    monkeypatch.setattr(models, 'new_id', lambda prefix: prefix + '_collision')
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    store_a, job_a, _, svc_a, qs_a = setup_job(first)
    store_b, job_b, _, svc_b, qs_b = setup_job(second)
    assert job_a.id == job_b.id
    assert get_job_evidence(qs_a, svc_a)[1]['job_ref']['state_id'] == state_identity(store_a.root)
    assert get_job_evidence(qs_b, svc_b)[1]['job_ref']['state_id'] == state_identity(store_b.root)
    def forbidden(*_):
        raise AssertionError('wrong-state job must not be read')
    monkeypatch.setattr(store_a, 'get_job', forbidden)
    code, data = get_job_evidence({**qs_a, 'state_id': qs_b['state_id']}, svc_a)
    assert code == 200
    assert data['code'] == 'job_evidence_unavailable'


def test_missing_evidence_state_ref_is_explicitly_unavailable(tmp_path):
    _, _, _, svc, qs = setup_job(tmp_path)
    qs.pop('state_id')
    assert get_job_evidence(qs, svc)[1]['code'] == 'job_evidence_unavailable'



@pytest.mark.parametrize('backend', ['file', 'sqlite'])
def test_attempt_ledger_costs_are_not_selected_delivery_or_complete_history(tmp_path, backend):
    store = create_store(backend, tmp_path / backend)
    job = store.create_job('SECRET')
    task = Task(job_id=job.id, role='test', instruction='SECRET', attempts=3)
    store.save_task(task)
    attempts = []
    for index, status in enumerate([TaskStatus.FAILED, TaskStatus.FAILED, TaskStatus.COMPLETE]):
        run = AgentRun(job_id=job.id, task_id=task.id, role='test', worker_id='worker', status=status)
        store.save_run(run)
        attempt = ExecutionAttempt.from_run(run, adapter='local', model='model', provider='provider')
        assert store.record_attempt(attempt)
        assert not store.record_attempt(attempt)
        with pytest.raises(LedgerConflictError):
            store.record_attempt(replace(attempt, model='changed'))
        attempts.append(attempt)
        if index < 2:
            store.record_usage_observation(UsageObservation(job.id, attempt.attempt_id, 'obs', 'provider',
                '2026-09-06', cost_state='measured' if index == 0 else 'estimated',
                cost_usd=0 if index == 0 else 2, cost_basis='plan_marginal' if index == 0 else 'api'))
    before = store.list_attempts(job.id)
    data = project_job_evidence(store, job, [task])
    assert store.list_attempts(job.id) == before
    assert data['links']['attempts'] == 'recorded'
    assert {row['attempt_id'] for row in data['attempts']} == {a.attempt_id for a in attempts}
    assert all(row['outcome'] == 'unavailable' for row in data['attempts'])
    metrics = data['cost']['recorded_attempts']
    assert metrics['plan_marginal_cost_usd']['known_subtotal'] == 0
    assert metrics['api_cost_usd']['known_subtotal'] == 2
    assert metrics['api_cost_usd']['estimated_attempts'] == 1
    assert metrics['api_cost_usd']['unknown_attempts'] == 2
    assert data['cost']['total_attempt_usd'] is None
    assert data['attempt_coverage'] == 'unverified'
    assert data['totals'] == {'tasks': 1, 'artifacts': 0, 'attempts': 3}
    assert 'SECRET' not in json.dumps(data)


@pytest.mark.parametrize('backend', ['file', 'sqlite'])
def test_attempt_snapshot_overlap_and_api_equivalent_are_not_spend(tmp_path, backend):
    store = create_store(backend, tmp_path / backend)
    job = store.create_job('private')
    task = Task(job_id=job.id, role='test', instruction='private')
    store.save_task(task)
    for name in ['overlap', 'equivalent']:
        store.record_attempt(ExecutionAttempt(job.id, task.id, name, name, 'today', 'local'))
    for event, value in [('first', 2), ('later', 3)]:
        store.record_usage_observation(UsageObservation(job.id, 'overlap', event, 'provider', 'today',
            cost_state='measured', cost_usd=value, cost_basis='api'))
    store.record_usage_observation(UsageObservation(job.id, 'equivalent', 'event', 'provider', 'today',
        cost_state='estimated', cost_usd=4, cost_basis='api_equivalent'))
    data = project_job_evidence(store, job, [task])
    metrics = data['cost']['recorded_attempts']
    assert metrics['api_cost_usd']['unknown_attempts'] == 2
    assert metrics['api_cost_usd']['conflicting_attempts'] == 1
    assert metrics['api_equivalent_cost_usd']['known_subtotal'] == 4
    assert all(row['consumption']['api_cost_usd']['total'] is None for row in data['attempts'])


def test_attempt_read_failure_is_not_empty_history(tmp_path):
    store, _, _, svc, qs = setup_job(tmp_path)
    store.list_attempts = lambda _: (_ for _ in ()).throw(OSError('SECRET'))
    assert get_job_evidence(qs, svc) == (503, {'error': 'Evidence records could not be read.'})


def test_attempt_response_cap_reports_full_count(tmp_path):
    store, job, task, _, _ = setup_job(tmp_path)
    for index in range(101):
        store.record_attempt(ExecutionAttempt(job.id, task.id, str(index), str(index), 'today', 'local'))
    data = project_job_evidence(store, job, [task])
    assert len(data['attempts']) == 100
    assert data['totals']['attempts'] == 101
    assert data['cost']['recorded_attempts']['api_cost_usd']['unknown_attempts'] == 101
    assert data['truncated']
    for index in range(101):
        store.record_usage_observation(UsageObservation(job.id, str(index), 'event', 'provider', 'today',
            cost_state='measured', cost_usd=1, cost_basis='api'))
    data = project_job_evidence(store, job, [task])
    assert len(data['attempts']) == 100
    assert data['cost']['recorded_attempts']['api_cost_usd']['total'] == 101
    assert data['cost']['recorded_attempts']['api_cost_usd']['known_attempts'] == 101


@pytest.mark.parametrize('receipt', [None, [], {}, {'actual_cost': []},
    {'job_id': 'foreign', 'actual_cost': {}}])
def test_malformed_receipt_is_unknown(tmp_path, receipt):
    from puppetmaster.models import JobStatus
    store, job, task, _, _ = setup_job(tmp_path)
    data = project_job_evidence(store, replace(job, status=JobStatus.COMPLETE, cost_receipt=receipt), [task])
    assert data['cost']['selected_usd'] is None
    assert data['cost']['total_attempt_usd'] is None


def test_wheel_terminal_report_selects_one_usage_record_per_task(tmp_path):
    from puppetmaster.cost import build_current_registry_cost_report, PRICING_SOURCE_TERMINAL
    from puppetmaster.models import JobStatus
    store, job, task, _, _ = setup_job(tmp_path)
    for result, cost in [('failed', 7), ('success', 3)]:
        store.save_artifact(Artifact(job_id=job.id, task_id=task.id, type=ArtifactType.VERIFICATION,
            created_by='worker', payload={'check': 'execution', 'result': result, 'tokens_in': 10, 'tokens_out': 2,
                'tokens_estimated': False, 'real_cost_usd': cost}, confidence=1, evidence=['fixture']))
    receipt = build_current_registry_cost_report(job.id, store.list_artifacts(job.id), registry=[])
    assert receipt['actual_cost']['total_marginal_cost_usd'] == 3
    receipt['pricing_source'] = PRICING_SOURCE_TERMINAL
    data = project_job_evidence(store, replace(job, status=JobStatus.COMPLETE, cost_receipt=receipt), [task])
    assert data['cost']['selected_usd'] == 3
    assert data['cost']['total_attempt_usd'] is None
    receipt['actual_cost']['unpriced_tasks'] = False
    assert project_job_evidence(store, replace(job, status=JobStatus.COMPLETE, cost_receipt=receipt), [task])['cost']['selected_usd'] is None


def test_usage_read_failure_and_foreign_attempt_fail_closed(tmp_path):
    store, job, _, svc, qs = setup_job(tmp_path)
    store.record_attempt(ExecutionAttempt(job.id, 'foreign-task', 'run', 'attempt', 'today', 'local'))
    assert get_job_evidence(qs, svc)[0] == 503
    store.list_usage_observations = lambda _: (_ for _ in ()).throw(OSError('SECRET'))
    assert get_job_evidence(qs, svc) == (503, {'error': 'Evidence records could not be read.'})


@pytest.mark.parametrize('backend', ['file', 'sqlite'])
def test_equal_public_consumption_snapshots_reconcile(tmp_path, backend):
    from puppetmaster.consumption import build_attempt_consumption_report
    store = create_store(backend, tmp_path / backend)
    job = store.create_job('private')
    task = Task(job_id=job.id, role='test', instruction='private')
    store.save_task(task)
    store.record_attempt(ExecutionAttempt(job.id, task.id, 'run', 'attempt', 'today', 'local'))
    for event in ('first', 'second'):
        store.record_usage_observation(UsageObservation(job.id, 'attempt', event, 'provider', 'today',
            cost_state='measured', cost_usd=3, cost_basis='api'))
    public = build_attempt_consumption_report(store, job.id).totals.api_cost_usd
    assert public.total == 3 and public.known_attempts == 1 and public.conflicting_attempts == 0
    data = project_job_evidence(store, job, [task])
    assert data['cost']['recorded_attempts']['api_cost_usd'] == {
        'total': 3, 'known_subtotal': 3, 'status': 'measured', 'known_attempts': 1,
        'unknown_attempts': 0, 'estimated_attempts': 0, 'conflicting_attempts': 0,
    }


@pytest.mark.parametrize('backend', ['file', 'sqlite'])
def test_consumption_bases_tokens_and_single_ledger_reads(tmp_path, backend, monkeypatch):
    store = create_store(backend, tmp_path / backend)
    job = store.create_job('private')
    task = Task(job_id=job.id, role='test', instruction='private')
    store.save_task(task)
    store.record_attempt(ExecutionAttempt(job.id, task.id, 'run', 'attempt', 'today', 'local'))
    for event, basis, value, state in [('api1', 'api', 3, 'estimated'),
            ('api2', 'api', 3, 'measured'), ('plan', 'plan_marginal', 0, 'measured'),
            ('equiv', 'api_equivalent', 9, 'estimated')]:
        store.record_usage_observation(UsageObservation(job.id, 'attempt', event, 'provider', 'today',
            usage_state='measured', tokens_in=10, tokens_out=2, cache_read_tokens=0,
            cost_state=state, cost_usd=value, cost_basis=basis))
    calls = []
    for method in ('list_attempts', 'list_usage_observations'):
        original = getattr(store, method)
        def read(job_id, original=original, method=method):
            calls.append(method)
            return original(job_id)
        monkeypatch.setattr(store, method, read)
    data = project_job_evidence(store, job, [task])
    assert calls == ['list_attempts', 'list_usage_observations']
    metrics = data['cost']['recorded_attempts']
    assert metrics == data['attempts'][0]['consumption']
    for field, value, status in [('api_cost_usd', 3, 'measured'),
            ('plan_marginal_cost_usd', 0, 'measured'), ('api_equivalent_cost_usd', 9, 'estimated'),
            ('tokens_in', 10, 'measured'), ('tokens_out', 2, 'measured'), ('cache_read_tokens', 0, 'measured')]:
        assert metrics[field]['total'] == value
        assert metrics[field]['known_subtotal'] == value
        assert metrics[field]['status'] == status
        assert metrics[field]['known_attempts'] == 1
    assert metrics['cache_write_tokens']['total'] is None
    assert metrics['cache_write_tokens']['known_subtotal'] is None
    assert data['cost']['total_attempt_usd'] is None
    assert data['cost']['selected_usd'] is None


@pytest.mark.parametrize('backend', ['file', 'sqlite'])
def test_public_observation_validation_and_overflow(tmp_path, backend):
    store = create_store(backend, tmp_path / backend)
    job = store.create_job('private')
    task = Task(job_id=job.id, role='test', instruction='private')
    store.save_task(task)
    for invalid in (float('nan'), float('inf'), -1, True, '3'):
        with pytest.raises(ValueError):
            UsageObservation(job.id, 'attempt', 'event', 'provider', 'today',
                cost_state='measured', cost_usd=invalid, cost_basis='api')
    with pytest.raises(ValueError):
        UsageObservation(job.id, 'attempt', 'event', 'provider', 'today',
            cost_state='measured', cost_usd=3, cost_basis='api_equivalent')
    for index in range(2):
        name = str(index)
        store.record_attempt(ExecutionAttempt(job.id, task.id, name, name, 'today', 'local'))
        store.record_usage_observation(UsageObservation(job.id, name, 'event', 'provider', 'today',
            cost_state='measured', cost_usd=1e308, cost_basis='api'))
    data = project_job_evidence(store, job, [task])
    metric = data['cost']['recorded_attempts']['api_cost_usd']
    assert metric['total'] is None and metric['known_subtotal'] is None
    assert metric['status'] == 'unknown'
    json.dumps(data, allow_nan=False)


def test_foreign_observation_fails_closed(tmp_path, monkeypatch):
    store, job, task, svc, qs = setup_job(tmp_path)
    store.record_attempt(ExecutionAttempt(job.id, task.id, 'run', 'attempt', 'today', 'local'))
    foreign = UsageObservation('foreign-job', 'attempt', 'event', 'provider', 'today',
        cost_state='measured', cost_usd=3, cost_basis='api')
    monkeypatch.setattr(store, 'list_usage_observations', lambda _: [foreign])
    assert get_job_evidence(qs, svc) == (503, {'error': 'Evidence records could not be read.'})
