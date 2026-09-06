from types import SimpleNamespace

import pytest
from puppetmaster.cancellation import is_cancelled
from puppetmaster.state import state_identity
from tests.test_scoped_job_artifacts import stores
from harness.api import jobs


def store_dump(store):
    import sqlite3
    with sqlite3.connect(store.root / 'state.sqlite3') as connection:
        return list(connection.iterdump())


def selection(qs, **changes):
    values = {key: value[0] for key, value in qs.items()}
    values.update(changes)
    return {'version': 1, 'job_ref': {'job_id': values.pop('job_id'),
            'state_id': values.pop('state_id')}, **values}


@pytest.mark.parametrize('source', ['harness', 'cli'])
def test_running_durable_cancel_refuses_without_changing_either_store(stores, source):
    primary, cli, svc, qs = stores
    chosen, other = (primary, cli) if source == 'harness' else (cli, primary)
    jid = qs['job_id'][0]
    chosen.store.update_job_status(jid, "running")
    before = [store_dump(s.store) for s in (chosen, other)]
    flag_before = is_cancelled(jid)
    code, result = jobs.post_swarm_cancel({'job_id': jid, 'selection': selection(qs,
        source=source, state_id=state_identity(chosen.store.root))}, svc)
    assert code == 409
    assert result['code'] == 'scoped_kernel_cancellation_required'
    assert result['ok'] is False
    assert [store_dump(s.store) for s in (chosen, other)] == before
    assert is_cancelled(jid) == flag_before


@pytest.mark.parametrize('field,value', [('state_id', 'wrong'), ('source', 'other'),
    ('session_id', 'foreign'), ('repo', '/foreign'), ('job_id', 'missing')])
def test_mismatch_has_no_effect(stores, field, value):
    primary, cli, svc, qs = stores
    before = [s.store.get_job(qs['job_id'][0]).status for s in (primary, cli)]
    assert jobs.post_swarm_cancel({'selection': selection(qs, **{field: value})}, svc)[0] == 409
    assert [s.store.get_job(qs['job_id'][0]).status for s in (primary, cli)] == before
    assert not is_cancelled(qs['job_id'][0])


@pytest.mark.parametrize('body', [{}, {'job_id': 'job_collision'}, {'selection': None},
    {'selection': {}}, {'selection': {'version': 2}}, {'selection': []}])
def test_missing_or_malformed_selection(stores, body):
    primary, _, svc, qs = stores
    before = primary.store.get_job(qs['job_id'][0]).status
    assert jobs.post_swarm_cancel(body, svc)[0] in (400, 409)
    assert primary.store.get_job(qs['job_id'][0]).status == before


@pytest.mark.parametrize('method', ['get_job', 'list_tasks'])
def test_real_failure_is_503(stores, method):
    primary, _, svc, qs = stores
    def fail(*args, **kwargs):
        raise OSError('private store failure')
    setattr(primary.store, method, fail)
    code, result = jobs.post_swarm_cancel({'selection': selection(qs)}, svc)
    assert code == 503
    assert 'private' not in str(result)
    assert not is_cancelled(qs['job_id'][0])


def test_context_switch_before_mutation_refuses(stores):
    primary, _, svc, qs = stores
    original = primary.store.list_tasks
    def switch(jid):
        tasks = original(jid)
        svc.sessions.active = 'other'
        return tasks
    primary.store.list_tasks = switch
    before = primary.store.get_job(qs['job_id'][0]).status
    assert jobs.post_swarm_cancel({'selection': selection(qs)}, svc)[0] == 409
    assert primary.store.get_job(qs['job_id'][0]).status == before


def test_local_cancel_uses_only_captured_pilot(stores):
    _, _, svc, qs = stores
    cancelled = []
    pilot = SimpleNamespace(harness_session_id='session-a',
        get_local_job=lambda jid: {'id': jid, 'session_id': 'session-a', 'cwd': svc.cfg.repo},
        cancel_local_job=lambda jid: cancelled.append(jid) or True)
    svc.get_pilot = lambda: pilot
    svc.get_session = lambda: pytest.fail('local selection must not open a durable session')
    ref = selection(qs, source='local', job_id='local-test', state_id=None)
    assert jobs.post_swarm_cancel({'selection': ref}, svc)[0] == 200
    assert cancelled == ['local-test']
    assert not is_cancelled('local-test')
    ref['session_id'] = 'other'
    assert jobs.post_swarm_cancel({'selection': ref}, svc)[0] == 409
    assert cancelled == ['local-test']


def test_live_rows_expose_actual_store_refs(stores):
    from dataclasses import asdict
    primary, cli, svc, qs = stores
    svc.cfg.driver = 'test'
    svc.job_swarm_accounting = lambda *args: (0, 0)
    errors = []
    svc.diag = lambda *args: errors.append(str(args))
    jid = qs['job_id'][0]
    svc.scoped_jobs_with_stores = lambda **_: ([
        {**asdict(primary.store.get_job(jid)), 'source': 'harness'},
        {**asdict(cli.store.get_job(jid)), 'source': 'cli'},
    ], primary.store, cli.store)
    code, result = jobs.get_swarm_live(None, svc)
    assert code == 200
    assert result['jobs'], errors
    assert [(j['source'], j['job_ref']) for j in result['jobs']] == [
        ('harness', {'job_id': jid, 'state_id': state_identity(primary.store.root)}),
        ('cli', {'job_id': jid, 'state_id': state_identity(cli.store.root)}),
    ]


def test_legacy_unique_primary_refuses_running_worker(stores, monkeypatch):
    primary, _, svc, qs = stores
    monkeypatch.setattr('harness.cli_job_merge.resolve_cli_state_dir', lambda _: None)
    jid = qs['job_id'][0]
    before = (primary.store.get_job(jid), primary.store.list_tasks(jid))
    assert jobs.post_swarm_cancel({'job_id': jid}, svc)[0] == 409
    assert (primary.store.get_job(jid), primary.store.list_tasks(jid)) == before
    assert not is_cancelled(jid)


def test_legacy_local_can_cancel_without_touching_global_flag(stores):
    _, _, svc, qs = stores
    cancelled = []
    pilot = SimpleNamespace(harness_session_id='session-a',
        get_local_job=lambda jid: {'id': jid, 'session_id': 'session-a', 'cwd': svc.cfg.repo},
        cancel_local_job=lambda jid: cancelled.append(jid) or True)
    svc.get_pilot = lambda: pilot
    assert jobs.post_swarm_cancel({'job_id': 'local-test'}, svc)[0] == 200
    assert cancelled == ['local-test']
    assert not is_cancelled('local-test')


@pytest.mark.parametrize('status', ['complete', 'failed', 'cancelled'])
def test_terminal_row_is_not_rewritten(stores, status):
    primary, _, svc, qs = stores
    jid = qs['job_id'][0]
    primary.store.update_job_status(jid, status)
    before = primary.store.get_job(jid)
    code, result = jobs.post_swarm_cancel({'selection': selection(qs)}, svc)
    assert code == 200
    assert result['marked'] is False
    assert primary.store.get_job(jid) == before


@pytest.mark.parametrize('field,value', [('job_id', 'missing'), ('state_id', 'wrong'),
    ('session_id', 'foreign'), ('repo', '/foreign')])
def test_refusal_does_not_write_cli_records(stores, field, value):
    import sqlite3
    _, cli, svc, qs = stores
    def dump():
        with sqlite3.connect(cli.store.root / 'state.sqlite3') as connection:
            return list(connection.iterdump())
    before = dump()
    ref = selection(qs, source='cli', state_id=state_identity(cli.store.root))
    if field in ('job_id', 'state_id'):
        ref['job_ref'][field] = value
    else:
        ref[field] = value
    assert jobs.post_swarm_cancel({'selection': ref}, svc)[0] == 409
    assert dump() == before


def test_cli_attach_failure_is_503(stores, monkeypatch):
    _, cli, svc, qs = stores
    def fail(*args, **kwargs):
        raise OSError('private attach detail')
    monkeypatch.setattr('puppetmaster.store_factory.create_store', fail)
    ref = selection(qs, source='cli', state_id=state_identity(cli.store.root))
    code, result = jobs.post_swarm_cancel({'selection': ref}, svc)
    assert code == 503
    assert 'private' not in str(result)
    assert not is_cancelled(qs['job_id'][0])


def test_no_sibling_discovery_during_legacy_cancel(stores, monkeypatch):
    _, _, svc, _ = stores
    monkeypatch.setattr('puppetmaster.state.find_state_dir_for_job',
                        lambda *_: pytest.fail('sibling discovery'))
    assert jobs.post_swarm_cancel({'job_id': 'missing'}, svc)[0] == 409


def test_local_real_event_and_record_are_scoped(stores, tmp_path):
    import threading
    from harness.local_jobs import LocalJobsMixin
    _, _, svc, qs = stores
    pilot = LocalJobsMixin()
    pilot.harness_session_id = 'session-a'
    pilot.config = svc.cfg
    pilot._local_jobs_lock = threading.RLock()
    pilot._local_jobs_path = str(tmp_path / 'local-jobs.json')
    pilot._local_jobs = {jid: {'id': jid, 'session_id': 'session-a', 'cwd': svc.cfg.repo,
                              'status': 'running'} for jid in ('local-selected', 'local-other')}
    pilot._local_job_cancels = {jid: threading.Event() for jid in pilot._local_jobs}
    svc.get_pilot = lambda: pilot
    ref = selection(qs, source='local', job_id='local-selected', state_id=None)
    assert jobs.post_swarm_cancel({'selection': ref}, svc)[0] == 200
    assert pilot._local_job_cancels['local-selected'].is_set()
    assert not pilot._local_job_cancels['local-other'].is_set()
    assert pilot.get_local_job('local-selected')['status'] == 'cancelled'
    assert pilot.get_local_job('local-other')['status'] == 'running'
    assert not is_cancelled('local-selected')


def test_refusal_on_fresh_harness_reader_does_not_initialize_store(stores):
    import sqlite3
    from puppetmaster.store_factory import create_store
    primary, _, svc, qs = stores
    root = primary.store.root
    def dump():
        with sqlite3.connect(root / 'state.sqlite3') as connection:
            return list(connection.iterdump())
    before = dump()
    primary.store = create_store('sqlite', root)
    assert jobs.post_swarm_cancel({'selection': selection(qs, job_id='missing')}, svc)[0] == 409
    assert dump() == before


@pytest.mark.parametrize('source', ['harness', 'cli'])
@pytest.mark.parametrize('field,value', [('session_id', 'foreign'), ('cwd', '/foreign'), ('cwd', '')])
def test_task_authority_refusal_preserves_exact_stores(stores, source, field, value):
    primary, cli, svc, qs = stores
    chosen = primary if source == 'harness' else cli
    jid = qs['job_id'][0]
    task = chosen.store.list_tasks(jid)[0]
    task.payload[field] = value
    chosen.store.save_task(task)
    before = [store_dump(s.store) for s in (primary, cli)]
    flag_before = is_cancelled(jid)
    ref = selection(qs, source=source, state_id=state_identity(chosen.store.root))
    code, body = jobs.post_swarm_cancel({'selection': ref}, svc)
    assert code == 409
    assert body['code'] == 'job_cancel_unavailable'
    assert [store_dump(s.store) for s in (primary, cli)] == before
    assert is_cancelled(jid) == flag_before
