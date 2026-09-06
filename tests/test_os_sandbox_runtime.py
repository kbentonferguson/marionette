"""Real Seatbelt policy checks using only owned files and TCP loopback."""
from __future__ import annotations

import errno
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys

import pytest

from harness import os_sandbox


@pytest.fixture
def seatbelt_backend():
    if sys.platform != "darwin":
        pytest.skip("Seatbelt runtime checks require macOS")
    exe = shutil.which("sandbox-exec")
    if exe is None:
        pytest.skip("sandbox-exec is not installed")
    probe = subprocess.run(
        [exe, "-p", "(version 1)\n(allow default)", "/usr/bin/true"],
        capture_output=True, text=True, timeout=10,
    )
    if probe.returncode:
        pytest.skip(
            "Seatbelt backend cannot start (nested sandbox may prohibit sandbox_apply): "
            f"exit={probe.returncode}, stderr={probe.stderr.strip()}"
        )
    os_sandbox.reset_probe_cache()
    yield
    os_sandbox.reset_probe_cache()


_CHILD = """
import json, os, pathlib, socket, sys
port, denied_path = int(sys.argv[1]), sys.argv[2]
result = {}
try:
    with socket.create_connection(('127.0.0.1', port), timeout=3) as connection:
        connection.sendall(b'sandbox-policy')
    result['network'] = 'connected'
except OSError as exc:
    result['network'] = exc.errno
for name, path in [('cwd', pathlib.Path('allowed.txt')),
                   ('temp', pathlib.Path(os.environ['TMPDIR']) / 'allowed.txt'),
                   ('denied', pathlib.Path(denied_path))]:
    try:
        path.write_text('child write', encoding='utf-8')
        result[name] = 'written'
    except OSError as exc:
        result[name] = exc.errno
print(json.dumps(result))
"""


@pytest.mark.parametrize("path_name", ["repo", 'repo\\\" ) (allow default) ;\nquoted'], ids=["plain", "quoted"])
@pytest.mark.parametrize(
    "mode,network,allowed",
    [("required", "allow", True), ("required", "deny", False),
     ("required", None, False), ("auto", None, True)],
    ids=["explicit-allow", "explicit-deny", "required-default", "auto-default"],
)
def test_macos_runtime_policy(seatbelt_backend, tmp_path, path_name, mode, network, allowed):
    cwd = tmp_path / path_name
    cwd.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    denied = state / "sessions.db"
    denied.write_text("unchanged", encoding="utf-8")
    env = dict(os.environ, HARNESS_OS_SANDBOX=mode, HARNESS_STATE_DIR=str(state))
    env.pop("HARNESS_OS_SANDBOX_NETWORK", None)
    if network is not None:
        env["HARNESS_OS_SANDBOX_NETWORK"] = network

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        server.settimeout(3)
        port = server.getsockname()[1]
        # Establish that the same child interpreter can reach this owned listener.
        baseline = subprocess.run(
            [sys.executable, "-c", "import socket,sys; socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=3).close()", str(port)],
            capture_output=True, text=True, timeout=10,
        )
        assert baseline.returncode == 0, baseline.stderr
        connection, _ = server.accept()
        connection.close()

        command = shlex.join([sys.executable, "-c", _CHILD, str(port), str(denied)])
        plan = os_sandbox.prepare_sandbox_spawn(command, cwd=str(cwd), env=env)
        assert plan is not None
        try:
            result = subprocess.run(
                plan.command, shell=True, cwd=cwd,
                env=dict(env, **(plan.child_env or {})),
                capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0, result.stderr
            observed = json.loads(result.stdout)
            assert observed["cwd"] == "written", observed
            assert observed["temp"] == "written", observed
            assert observed["denied"] in (errno.EPERM, errno.EACCES), observed
            assert denied.read_text(encoding="utf-8") == "unchanged"
            if allowed:
                assert observed["network"] == "connected", observed
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(3)
                    assert connection.recv(64) == b"sandbox-policy"
            else:
                assert observed["network"] in (errno.EPERM, errno.EACCES), observed
        finally:
            if plan.cleanup:
                plan.cleanup()
