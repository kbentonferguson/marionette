"""Regression coverage for command recovery truth and batch ownership."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from command_shell_helpers import python_shell_command

import pytest

from test_command_batches import _Session, _wait_batch_terminal
from harness.command_batches import start_command_batch
from harness.command_jobs import build_pending_receipt
from harness.local_job_swarm_view import project_local_job_for_swarm_live


def test_running_checkpoint_is_pending_outcome(tmp_path):
    session = _Session(str(tmp_path), str(tmp_path))
    session._register_command_job('local-cmd-live', command='echo x', action_id='live')
    session._checkpoint_command_job_launch('local-cmd-live')
    session._mark_command_job_running('local-cmd-live')
    receipt = build_pending_receipt(session.get_local_job('local-cmd-live'))
    assert receipt['status'] == 'running'
    assert receipt['terminal_receipt'] is None


def test_replay_preserves_batch_process_bound(tmp_path):
    session = _Session(str(tmp_path), str(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    active = peak = calls = 0

    def run(command, **kwargs):
        nonlocal active, peak, calls
        with lock:
            active += 1
            calls += 1
            peak = max(peak, active)
        entered.set()
        try:
            assert release.wait(4)
            return 'ok', 0, 'ok'
        finally:
            with lock:
                active -= 1

    with patch('harness.command_policy.run_cancellable', side_effect=run):
        first = start_command_batch(session, ['echo a', 'echo b', 'echo c'], 'bound', max_concurrency=1)
        assert entered.wait(2)
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda _: start_command_batch(session, ['echo a', 'echo b', 'echo c'], 'bound'), range(3)))
            time.sleep(.15)
            assert peak == 1
        finally:
            release.set()
            _wait_batch_terminal(session, first['batch_id'])
    assert calls == 3


def test_restart_unknown_is_durable_and_retains_legacy_receipt(tmp_path):
    session = _Session(str(tmp_path), str(tmp_path))
    with patch('harness.command_batches._start_batch_supervisor'):
        receipt = start_command_batch(session, ['echo a'], 'legacy')
    cid = receipt['child_job_ids'][0]
    session._checkpoint_command_job_launch(cid)
    legacy = {'status': 'cancelled', 'exit_code': -1, 'recovery': 'terminal_after_restart', 'had_launch_checkpoint': True}
    session._local_jobs[cid].update(status='cancelled', terminal_receipt=legacy)
    session._persist_local_jobs()
    for _ in range(2):
        session = _Session(str(tmp_path), str(tmp_path))
        session._load_local_jobs()
        child = session.get_local_job(cid)
        assert child['status'] == 'unknown'
        assert child['terminal_receipt'] is None
        assert child['recovery_receipt'] == legacy
        assert 'exit_code' not in child
        batch = session.get_local_job(receipt['batch_id'])
        assert batch['status'] == 'unknown'
        assert batch['children'][0]['status'] == 'unknown'
        assert project_local_job_for_swarm_live(child)['status'] == 'unknown'
        rows = {j['id']: j for j in json.loads((tmp_path / 'swarm_local_jobs.json').read_text())['jobs']}
        assert rows[cid]['status'] == rows[receipt['batch_id']]['status'] == 'unknown'


@pytest.mark.parametrize('reload_session', [True, False])
def test_product_session_fake_driver_replays_unknown_receipt(tmp_path, reload_session):
    import subprocess
    from harness.config import HarnessConfig
    from harness.conversation import ConversationalSession
    from pmharness.drivers.base import DriverResponse

    command = python_shell_command("from pathlib import Path; Path('effect').open('a').write('x')")
    config = HarnessConfig(driver='stub-oracle-v2', state_dir=str(tmp_path), repo=str(tmp_path))
    session = ConversationalSession(config)
    with patch('harness.command_batches._start_batch_supervisor'):
        first = start_command_batch(session, [command], 'same-action')
    session._checkpoint_command_job_launch(first['child_job_ids'][0])
    subprocess.run(command, shell=True, cwd=tmp_path, check=True)
    session._load_local_jobs()

    class Pilot:
        model = 'stub-oracle-v2'
        supports_streaming = False
        calls = 0
        receipts = []
        outbound = []

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls % 2:
                return DriverResponse(text='', meta={'tool_calls': [{'id': 'same-action', 'type': 'function', 'function': {'name': 'run_command_batch', 'arguments': json.dumps({'commands': [command]})}}]}, tokens_in=1, tokens_out=1, latency_ms=1)
            import copy
            self.outbound.append(copy.deepcopy(messages))
            results = [m for m in messages if m.get('role') == 'tool']
            self.receipts.append(json.JSONDecoder().raw_decode(results[-1]['content'])[0])
            return DriverResponse(text='Observed unknown command outcome.', tokens_in=1, tokens_out=1, latency_ms=1)

        def complete(self, prompt, **kwargs):
            raise AssertionError('Expected native chat')

    pilot = Pilot()
    for _ in range(2):
        if reload_session:
            restored_history = json.loads(json.dumps(session._history))
            session = ConversationalSession(config)
            session._history = restored_history
        session.pilot = pilot
        session._build_visible_tools_schema = lambda: [{'type': 'function', 'function': {'name': 'run_command_batch', 'parameters': {'type': 'object'}}}]
        session._maybe_compact_history = lambda *a, **k: iter(())
        session._submit_housekeeping = lambda *a, **k: None
        events = list(session.send('Observe the same command action.'))
        results = [e.data for e in events if e.kind == 'action_result' and e.data.get('kind') == 'run_command_batch']
        assert results, [(e.kind, e.data) for e in events]
        assert results[-1]['status'] == 'unknown'
        assert results[-1]['recovery_state'] == 'unknown'
        assert results[-1]['terminal_receipt'] is None
        assert results[-1]['child_job_ids'] == first['child_job_ids']
    assert len(pilot.receipts) == 2, (pilot.calls, [(e.kind, e.data) for e in events], session._history)
    assert all(r['status'] == 'unknown' and r['terminal_receipt'] is None for r in pilot.receipts)
    assert (tmp_path / 'effect').read_text() == 'x'
    for messages in pilot.outbound:
        ids = []
        for index, message in enumerate(messages):
            if message.get('role') != 'assistant' or not message.get('tool_calls'):
                continue
            call, = message['tool_calls']
            ids.append(call['id'])
            result = messages[index + 1]
            assert result['role'] == 'tool'
            assert result['tool_call_id'] == call['id']
            receipt = json.JSONDecoder().raw_decode(result['content'])[0]
            assert receipt['action_id'] == 'same-action'
            assert receipt['child_job_ids'] == first['child_job_ids']
            assert receipt['status'] == 'unknown'
        assert len(ids) == len(set(ids))
        from pmharness.drivers.anthropic import AnthropicDriver
        driver = AnthropicDriver(name='test', model='test', base_url='https://unused', api_key_env='UNUSED')
        body = driver._build_body(messages, None, None)
        uses = []
        replies = []
        for row in body['messages']:
            for block in row['content']:
                if block['type'] == 'tool_use':
                    uses.append(block['id'])
                elif block['type'] == 'tool_result':
                    replies.append(block['tool_use_id'])
                    assert json.JSONDecoder().raw_decode(block['content'])[0]['status'] == 'unknown'
                    assert 'is_error' not in block
        assert uses == replies == ids
    assert len(ids) == 2
    assert pilot.outbound[0][1]['tool_calls'][0]['id'] == ids[0]
    # Round-trip the actual canonical history, as session archives do.
    session._history = json.loads(json.dumps(session._history))
    assert session._messages_for_provider() == pilot.outbound[-1]


def test_concurrent_replay_bounds_real_processes(tmp_path):
    session = _Session(str(tmp_path), str(tmp_path))
    commands = []
    for index in range(4):
        code = (
            "from pathlib import Path; import time; "
            f"p=Path('started-{index}'); p.write_text('started'); "
            "log=Path('events'); "
            f"log.open('a').write('start {index}\\n'); "
            "deadline=time.monotonic()+10\n"
            "while not Path('release').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
            "assert Path('release').exists(), 'release deadline expired'\n"
            f"log.open('a').write('end {index}\\n')"
        )
        commands.append(python_shell_command(code))
    first = start_command_batch(session, commands, 'real-bound', max_concurrency=2)
    try:
        deadline = time.monotonic() + 3
        while len(list(tmp_path.glob('started-*'))) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        assert len(list(tmp_path.glob('started-*'))) == 2
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: start_command_batch(session, commands, 'real-bound'), range(4)))
        time.sleep(.2)
        assert len(list(tmp_path.glob('started-*'))) == 2
        assert all(r['batch_id'] == first['batch_id'] for r in receipts)
    finally:
        (tmp_path / 'release').touch()
        settled = _wait_batch_terminal(session, first['batch_id'])
    assert settled['status'] == 'completed'
    active = peak = 0
    for line in (tmp_path / 'events').read_text().splitlines():
        active += 1 if line.startswith('start') else -1
        peak = max(peak, active)
    assert peak == 2
    assert active == 0
    assert len((tmp_path / 'events').read_text().splitlines()) == 8
