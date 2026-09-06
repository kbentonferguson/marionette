from types import SimpleNamespace

import pytest
from puppetmaster import models
from puppetmaster.models import Artifact, ArtifactType, Task
from puppetmaster.state import state_identity
from puppetmaster.store_factory import create_store

from harness.api import jobs
from harness.job_scoping import job_label_for_session, stamp_task_payload
from harness.state import DurableState


@pytest.fixture
def stores(tmp_path, monkeypatch):
    repo = str(tmp_path / 'repo')
    monkeypatch.setattr(models, 'new_id', lambda prefix: prefix + '_collision')
    states = []
    for name in ('primary', 'cli'):
        store = create_store('sqlite', tmp_path / name)
        job = store.create_job('goal', label=job_label_for_session('session-a'))
        store.save_task(Task(job_id=job.id, role='test', instruction='test',
            payload=stamp_task_payload({}, session_id='session-a', cwd=repo)))
        state = DurableState.__new__(DurableState)
        state.store = store
        states.append(state)
    primary, cli = states
    cli.store.save_artifact(Artifact(job_id=job.id, task_id='task_collision', type=ArtifactType.GATE,
        created_by='test', payload={'gate': 'test', 'passed': True}, confidence=1, evidence=['test'] ))
    monkeypatch.setattr('harness.cli_job_merge.resolve_cli_state_dir', lambda _: str(cli.store.root))
    monkeypatch.setattr('harness.cli_job_merge.open_cli_durable_state', lambda _: cli)
    svc = jobs.make_job_services(cfg=SimpleNamespace(repo=repo, state_dir=str(primary.store.root)),
        sessions=SimpleNamespace(active='session-a'), get_pilot=lambda: SimpleNamespace(_session_job_ids=[]),
        get_session=lambda: SimpleNamespace(state=lambda: primary))
    qs = {'job_id': [job.id], 'state_id': [state_identity(primary.store.root)],
          'source': ['harness'], 'session_id': ['session-a'], 'repo': [repo]}
    return primary, cli, svc, qs


def test_selected_empty_primary_does_not_fall_through(stores):
    primary, cli, svc, qs = stores
    status, data = jobs.get_scoped_artifacts(qs, svc)
    assert status == 200
    assert data['artifacts'] == []
    assert data['job_ref'] == {'job_id': qs['job_id'][0], 'state_id': qs['state_id'][0]}
    assert cli.store.list_artifacts(qs['job_id'][0])


def test_cli_collision_reads_only_selected_store(stores):
    _, cli, svc, qs = stores
    qs.update(source=['cli'], state_id=[state_identity(cli.store.root)])
    status, data = jobs.get_scoped_artifacts(qs, svc)
    assert status == 200
    assert len(data['artifacts']) == 1
    assert data['artifacts'][0]['headline'] == ''


@pytest.mark.parametrize('field,value', [('state_id', 'state_wrong'), ('source', 'other'),
    ('session_id', 'session-other'), ('repo', '/other'), ('job_id', 'job_missing')])
def test_mismatch_is_unavailable_without_artifact_read(stores, field, value):
    primary, _, svc, qs = stores
    primary.store.list_artifacts = lambda _: pytest.fail('read artifacts for mismatched reference')
    status, data = jobs.get_scoped_artifacts({**qs, field: [value]}, svc)
    assert status == 409
    assert data['code'] == 'job_artifacts_unavailable'


@pytest.mark.parametrize('method', ['get_job', 'list_tasks', 'list_artifacts'])
def test_store_failure_is_503_not_empty(stores, method):
    primary, _, svc, qs = stores
    def fail(*args):
        raise OSError('private error detail')
    setattr(primary.store, method, fail)
    status, data = jobs.get_scoped_artifacts(qs, svc)
    assert status == 503
    assert 'private' not in str(data)


def test_context_change_during_read_is_unavailable(stores):
    primary, _, svc, qs = stores
    def change(_):
        svc.sessions.active = 'session-b'
        return []
    primary.store.list_artifacts = change
    assert jobs.get_scoped_artifacts(qs, svc)[0] == 409


def test_foreign_task_scope_cannot_read_artifacts(stores):
    primary, _, svc, qs = stores
    task = primary.store.list_tasks(qs['job_id'][0])[0]
    from dataclasses import replace
    primary.store.save_task(replace(task, payload={**task.payload, 'session_id': 'foreign'}))
    primary.store.list_artifacts = lambda _: pytest.fail('foreign read')
    assert jobs.get_scoped_artifacts(qs, svc)[0] == 409


def test_legacy_duplicate_id_is_unavailable(stores):
    _, _, svc, qs = stores
    status, data = jobs.get_artifacts(qs['job_id'][0], svc)
    assert status == 409
    assert data['code'] == 'job_artifacts_unavailable'


def test_legacy_store_error_is_503(stores):
    primary, _, svc, qs = stores
    def fail(*args):
        raise OSError('private read error')
    primary.store.get_job = fail
    status, data = jobs.get_artifacts(qs['job_id'][0], svc)
    assert status == 503
    assert 'private' not in str(data)


def test_list_refs_distinguish_colliding_sources(stores):
    primary, cli, svc, qs = stores
    jid = qs['job_id'][0]
    svc.scoped_jobs_snapshot = lambda **_: [
        {'id': jid, 'source': 'harness'},
        {'id': jid, 'source': 'cli', 'cli_state_dir': str(cli.store.root)},
    ]
    code, rows = jobs.get_jobs(None, svc)
    assert code == 200
    assert rows[0]['job_ref']['state_id'] == state_identity(primary.store.root)
    assert rows[1]['job_ref']['state_id'] == state_identity(cli.store.root)
    assert rows[0]['job_ref'] != rows[1]['job_ref']


def test_cli_cannot_use_harness_ref(stores):
    _, _, svc, qs = stores
    assert jobs.get_scoped_artifacts({**qs, 'source': ['cli']}, svc)[0] == 409


def test_foreign_label_refused_before_task_or_artifact_reads(stores):
    from dataclasses import replace
    primary, _, svc, qs = stores
    job = primary.store.get_job(qs['job_id'][0])
    primary.store.get_job = lambda _: replace(job, label=job_label_for_session('foreign'))
    primary.store.list_tasks = lambda _: pytest.fail('foreign task read')
    primary.store.list_artifacts = lambda _: pytest.fail('foreign artifact read')
    assert jobs.get_scoped_artifacts(qs, svc)[0] == 409


def test_cli_open_error_is_503(stores, monkeypatch):
    _, cli, svc, qs = stores
    def fail(*args):
        raise OSError('private open detail')
    monkeypatch.setattr('harness.state.DurableState', fail)
    qs.update(source=['cli'], state_id=[state_identity(cli.store.root)])
    status, data = jobs.get_scoped_artifacts(qs, svc)
    assert status == 503
    assert 'private' not in str(data)


def test_legacy_empty_primary_with_no_cli_remains_empty(stores, monkeypatch):
    _, _, svc, qs = stores
    monkeypatch.setattr('harness.cli_job_merge.open_cli_durable_state', lambda _: None)
    status, data = jobs.get_artifacts(qs['job_id'][0], svc)
    assert (status, data) == (200, [])
