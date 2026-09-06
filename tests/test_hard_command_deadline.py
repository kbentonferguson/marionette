"""Real owned processes; no providers or commands outside temporary fixtures."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

from harness import command_policy as cp


@pytest.mark.skipif(os.name != 'posix', reason='POSIX SIGTERM/process-group proof')
@pytest.mark.parametrize('mode', ['timeout', 'cancelled'])
def test_noncooperating_tree_is_reaped_with_bounded_deadline(tmp_path, monkeypatch, mode):
    script = tmp_path / 'owned.py'
    effects = tmp_path / 'effects'
    script.write_text('''import os, signal, subprocess, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
root = Path(sys.argv[1])
if len(sys.argv) == 2:
    child = subprocess.Popen([sys.executable, __file__, str(root), 'child'])
    (root.parent / 'parent.pid').write_text(str(os.getpid()))
else:
    (root.parent / 'child.pid').write_text(str(os.getpid()))
    with root.open('a') as out:
        out.write('effect-once\\n')
    print('child-ready', flush=True)
while True:
    time.sleep(.01)
''')
    captured = []
    real_popen = subprocess.Popen
    def capture(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        captured.append(proc)
        return proc
    monkeypatch.setattr(cp.subprocess, 'Popen', capture)
    monkeypatch.setenv('HARNESS_OS_SANDBOX', 'off')
    event = threading.Event()
    timer = threading.Timer(.5, event.set)
    if mode == 'cancelled':
        timer.start()
    began = time.monotonic()
    try:
        output, code, status = cp.run_cancellable(
            'exec ' + shlex.join([sys.executable, str(script), str(effects)]),
            timeout=.5 if mode == 'timeout' else 5, cancel_event=event,
            poll_interval=.01,
        )
        elapsed = time.monotonic() - began
        pids = [int((tmp_path / name).read_text()) for name in ('parent.pid', 'child.pid')]
        deadline = time.monotonic() + 1
        live = pids[:]
        while live and time.monotonic() < deadline:
            live = []
            for pid in pids:
                try:
                    os.kill(pid, 0)
                    # Linux may retain an orphan zombie until init reaps it.
                    stat = Path(f'/proc/{pid}/stat')
                    if sys.platform.startswith('linux') and stat.exists():
                        try:
                            if stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z':
                                continue
                        except FileNotFoundError:
                            continue
                    live.append(pid)
                except ProcessLookupError:
                    pass
            if live:
                time.sleep(.01)
        proof = dict(mode=mode, elapsed=elapsed, pids=pids, live=live,
                     returncode=captured[0].returncode, output=output,
                     effects=effects.read_text(), pipe_closed=captured[0].stdout.closed)
        print(json.dumps(proof, sort_keys=True))
        assert status == mode
        assert 'child-ready' in output
        assert effects.read_text() == 'effect-once\n'
        assert elapsed < 1.8, proof
        assert not live, proof
        assert captured[0].returncode is not None, proof
        assert captured[0].stdout.closed, proof
        assert cp.owned_command_pids_for_tests(event) == []
    finally:
        timer.cancel()
        for proc in captured:
            # Fixture-only cleanup: a group is owned until its direct child is reaped.
            if proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=2)
            if proc.stdout:
                proc.stdout.close()

@pytest.mark.parametrize('status', ['timeout', 'cancelled', 'truncated'])
def test_terminal_command_does_not_claim_effects_rolled_back(status):
    from harness.command_jobs import build_pending_receipt
    receipt = build_pending_receipt({
        'id': 'fixture', 'status': status,
        'terminal_receipt': {'status': status}, 'exit_code': -1,
    })
    assert receipt['status'] == status
    assert receipt['effect_state'] == 'unknown'
    assert receipt['retry_disposition'] == 'do_not_retry'


def test_threaded_pipe_path_closes_real_pipe():
    proc = subprocess.Popen([sys.executable, '-c', "print('threaded-output')"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        output, code, status = cp._run_cancellable_wait(
            proc, cancel_event=None, stale_cancel=False, timeout=5,
            poll_interval=.01, start=time.monotonic(), fcntl=None,
        )
        assert (output, code, status) == ('threaded-output\n', 0, 'ok')
        assert proc.stdout.closed
    finally:
        proc.wait(timeout=2)
        proc.stdout.close()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX nonblocking pipe and signal proof')
def test_cancelled_final_output_cap_keeps_terminal_reason(monkeypatch):
    import fcntl
    monkeypatch.setattr(cp, 'MAX_CAPTURED_OUTPUT', 128)
    proc = subprocess.Popen([sys.executable, '-c', "print('X' * 256)"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)
    proc.wait(timeout=2)
    cancel = threading.Event()
    cancel.set()
    output, code, status = cp._run_cancellable_wait(
        proc, cancel_event=cancel, stale_cancel=False, timeout=5,
        poll_interval=.01, start=time.monotonic(), fcntl=fcntl,
    )
    assert status == 'cancelled'
    assert code == 130
    assert 'truncated' in output
    assert 'external effects unknown' in output
    assert proc.stdout.closed


@pytest.mark.skipif(os.name != 'posix', reason='POSIX PID reuse protection')
def test_reaped_group_leader_is_not_signalled(monkeypatch):
    proc = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
    proc.wait(timeout=2)
    calls = []
    monkeypatch.setattr(os, 'killpg', lambda *args: calls.append(args))
    assert cp.kill_process_group(proc) is False
    assert calls == []
