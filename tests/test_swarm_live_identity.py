from dataclasses import asdict
from types import SimpleNamespace

import pytest
from puppetmaster import models
from puppetmaster.models import Artifact, ArtifactType, Task
from puppetmaster.state import state_identity
from puppetmaster.store_factory import create_store

from harness.api.jobs import get_swarm_live, make_job_services
from harness.cli_job_merge import merge_scoped_cli_jobs
from harness.job_scoping import job_label_for_session, stamp_task_payload
from harness.state import DurableState


@pytest.fixture
def collision(tmp_path, monkeypatch, request):
    monkeypatch.setattr(models, 'new_id', lambda prefix: prefix + '_collision')
    monkeypatch.setenv('HARNESS_APP_RUN_ID', 'run-current')
    monkeypatch.setenv('HARNESS_CLI_COST_MERGE', '1')
    states = []
    for n, name in enumerate(('primary', 'cli', 'foreign'), 1):
        store = create_store('sqlite', tmp_path / name)
        job = store.create_job(name, label=job_label_for_session('session-a', app_run_id='run-current'))
        store.update_job_status(job.id, 'running')
        task = Task(id='task-' + name, job_id=job.id, role=name, instruction=name,
                    payload=stamp_task_payload({'model': name}, session_id='session-a', cwd=str(tmp_path)))
        store.save_task(task)
        for kind, payload in ((ArtifactType.FINDING, {'claim': name, 'validation_fingerprint': name}),
                              (ArtifactType.VERIFICATION, {'check': 'usage', 'result': 'ok', 'model': name,
                               'tokens_in': n * 100, 'tokens_out': n * 10})):
            if name == getattr(request, "param", None):
                continue
            store.save_artifact(Artifact(id='artifact-' + kind.value, job_id=job.id, task_id=task.id,
                type=kind, created_by=name, payload=payload, confidence=1, evidence=[name]))
        state = DurableState.__new__(DurableState)
        state.store = store
        states.append(state)
    monkeypatch.setattr('harness.cli_job_merge.resolve_cli_state_dir', lambda _: str(states[1].store.root))
    monkeypatch.setattr('harness.cli_job_merge.open_cli_durable_state', lambda _: states[1])
    monkeypatch.setattr('harness.cli_job_merge._foreign_state_dir_candidates', lambda _: [str(states[2].store.root)])
    return states


def live(states, rows=None, cli_available=True):
    from harness.api.swarm_cost import _job_swarm_accounting, _task_swarm_accounting
    if rows is None:
        rows = [{**asdict(s.store.get_job('job_collision')), 'source': 'harness' if i == 0 else 'cli',
                 'cli_state_dir': str(s.store.root) if i else '', 'accounting_owned': True}
                for i, s in enumerate(states)]
    svc = make_job_services(cfg=SimpleNamespace(repo='', driver='test'),
        sessions=SimpleNamespace(active='session-a'),
        get_session=lambda: SimpleNamespace(state=lambda: states[0]),
        get_pilot=lambda: SimpleNamespace(_session_job_ids=[], live_local_jobs=lambda: []),
        scoped_jobs_with_stores=lambda **_: (rows, states[0].store, states[1].store if cli_available else None),
        swarm_registry=lambda: [SimpleNamespace(id=name, adapter_model_name=name, input_per_mtok_usd=1.0,
            output_per_mtok_usd=2.0, billing='metered',
            marginal_cost_usd=lambda tin, tout: (tin + 2 * tout) / 1_000_000,
            estimate_cost_usd=lambda tin, tout: (tin + 2 * tout) / 1_000_000)
                                for name in ('primary', 'cli', 'foreign')],
        slim_swarm_list_artifacts=lambda arts, _: [asdict(a) for a in arts],
        job_swarm_accounting=_job_swarm_accounting, task_swarm_accounting=_task_swarm_accounting)
    status, result = get_swarm_live(None, svc)
    assert status == 200
    return result['jobs']


def test_live_collision_keeps_each_store_preview_tasks_and_cost(collision):
    rows = live(collision)
    assert len(rows) == 3
    for n, (row, state) in enumerate(zip(rows, collision), 1):
        name = ('primary', 'cli', 'foreign')[n - 1]
        assert row['job_ref']['state_id'] == state_identity(state.store.root)
        assert [t['id'] for t in row['tasks']] == ['task-' + name]
        finding = next(a for a in row['artifacts'] if a['type'] == ArtifactType.FINDING)
        assert finding['payload']['claim'] == name
        assert finding['payload']['validation_fingerprint'] == name
        assert row['tokens'] == n * 110
        assert row['est_cost_usd'] == pytest.approx(n * .00012)
        assert row['tasks'][0]['est_cost_usd'] == row['est_cost_usd']


@pytest.mark.parametrize("collision", ["primary"], indirect=True)
def test_empty_primary_does_not_borrow_cli_preview(collision):
    rows = live(collision)
    assert rows[0]['artifacts'] == []
    assert rows[0]['tokens'] == 0
    assert rows[1]['artifacts']


def test_missing_cli_store_is_unavailable(collision):
    rows = live(collision, rows=[{'id': 'job_collision', 'source': 'cli'}], cli_available=False)
    assert len(rows) == 1
    assert rows[0]['tasks'] == []
    assert rows[0]['artifacts'] == []
    assert 'job_ref' not in rows[0]
    assert rows[0]['read_status'] == 'unavailable'


def test_merge_preserves_colliding_store_rows(collision, monkeypatch):
    monkeypatch.setenv('HARNESS_CLI_CROSS_PROJECT', '1')
    primary = collision[0].store
    rows, _, tasks = merge_scoped_cli_jobs([asdict(primary.get_job('job_collision'))],
        harness_store=primary, active_session_id='session-a', repo_root='', workspace_root='')
    assert len(rows) == 3
    from harness.job_scoping import annotate_jobs_accounting
    tagged = annotate_jobs_accounting(rows, active_session_id='session-a', tasks_by_job=tasks)
    assert [r['cwd'] for r in tagged[1:]] == [str(primary.root.parent)] * 2


def test_failed_foreign_open_does_not_borrow_primary_cli(collision, monkeypatch):
    monkeypatch.setattr('harness.cli_job_merge.open_cli_durable_at', lambda _: None)
    rows = live(collision)
    assert rows[1]['tokens'] == 220
    assert rows[2]['artifacts'] == rows[2]['tasks'] == []
    assert rows[2]['read_status'] == 'unavailable'
    assert 'job_ref' not in rows[2]
    assert rows[2]['financial_receipt']['spend_basis'] == 'unavailable'


def test_registered_id_does_not_give_cli_accounting_ownership(collision):
    from harness.job_scoping import annotate_jobs_accounting
    row = {'id': 'job_collision', 'source': 'cli',
           'label': job_label_for_session('session-a', app_run_id='run-old')}
    tagged = annotate_jobs_accounting([row], active_session_id='session-a',
                                      registered_job_ids=['job_collision'])
    assert tagged[0]['accounting_owned'] is False


def test_cli_task_only_ownership_does_not_use_harness_tasks(collision):
    from harness.job_scoping import annotate_jobs_accounting
    primary, cli, _ = collision
    row = {'id': 'job_collision', 'source': 'cli', 'cli_state_dir': str(cli.store.root)}
    tagged = annotate_jobs_accounting([row], active_session_id='session-a',
        tasks_by_job={'job_collision': primary.store.list_tasks('job_collision')})
    assert tagged[0]['accounting_owned'] is False
    assert 'cwd' not in tagged[0]


def test_fallback_reads_stay_in_the_selected_store(collision, monkeypatch):
    def fail(_):
        raise OSError('bulk unavailable')
    for state in collision:
        monkeypatch.setattr(state.store, 'list_tasks_for_jobs', fail)
        monkeypatch.setattr(state.store, 'list_artifacts_for_jobs', fail)
    rows = live(collision)
    assert [r['tasks'][0]['id'] for r in rows] == ['task-primary', 'task-cli', 'task-foreign']
    assert [r['tokens'] for r in rows] == [110, 220, 330]


def test_cli_store_alias_dedupes_scan_rows(collision, monkeypatch, tmp_path):
    from harness.cli_job_merge import merge_running_cli_jobs_all_projects
    alias = tmp_path / 'foreign-alias'
    alias.symlink_to(collision[2].store.root, target_is_directory=True)
    monkeypatch.setattr('harness.cli_job_merge._foreign_state_dir_candidates',
        lambda _: [str(collision[2].store.root), str(alias)])
    rows = merge_running_cli_jobs_all_projects(seen_ids=set())
    assert len(rows) == 1


def test_tool_output_savings_stay_with_the_selected_store(collision):
    import json
    for n, state in enumerate(collision, 1):
        (state.store.root / 'tool_output_savings.jsonl').write_text(json.dumps({
            'job_id': 'job_collision', 'tool_call_id': 'same-call',
            'tokens_saved': 100 * n, 'original_chars': 400 * n, 'compact_chars': 0,
        }) + '\n')
    from harness.tool_output_savings import get_ledger
    get_ledger(str(collision[0].store.root)).record(session_id='session-a',
        tool_call_id='same-call', original_chars=400, compact_chars=0, job_id='job_collision')
    rows = live(collision)
    assert [r['tool_output_tokens_saved'] for r in rows] == [100, 200, 300]


def test_scoped_snapshot_preserves_store_tasks_and_live_identity(collision, monkeypatch):
    from harness.api import cost
    monkeypatch.setenv('HARNESS_CLI_CROSS_PROJECT', '1')
    primary = collision[0].store
    monkeypatch.setattr(cost, '_jobs_snapshot', lambda: [asdict(primary.get_job('job_collision'))])
    monkeypatch.setattr(cost, '_session', lambda: SimpleNamespace(state=lambda: collision[0]))
    monkeypatch.setattr(cost, '_cfg', lambda: SimpleNamespace(repo=''))
    monkeypatch.setattr(cost, '_sessions', lambda: SimpleNamespace(active='session-a'))
    monkeypatch.setattr(cost, '_pilot', lambda: SimpleNamespace(_session_job_ids=['job_collision']))
    rows, _, _ = cost._scoped_jobs_with_stores()
    assert len(rows) == 3
    assert all(row['accounting_owned'] for row in rows)
    assert [r['tokens'] for r in live(collision, rows=rows)] == [110, 220, 330]
