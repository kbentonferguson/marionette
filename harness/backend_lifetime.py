"""Explicit externally owned backend receipt; no daemon or process supervisor."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

_SOURCE_PATHS = ('harness', 'pmharness', 'webapp/electron', 'pyproject.toml', 'uv.lock')
_active = None


def source_snapshot(root: Path) -> dict:
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)

    try:
        sha = git('rev-parse', 'HEAD').decode().strip()
    except subprocess.CalledProcessError:
        sha = ''
    names = git('ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', *_SOURCE_PATHS)
    digest = hashlib.sha256()
    for name in sorted(set(names.split(b'\0')) - {b''}):
        file = root / os.fsdecode(name)
        digest.update(name + b'\0')
        if file.is_symlink():
            digest.update(b'link\0' + os.fsencode(os.readlink(file)))
        elif file.exists():
            digest.update(b'file\0' + hashlib.sha256(file.read_bytes()).digest())
        else:
            digest.update(b'missing\0')
    return {'source_sha': sha, 'dirty': bool(git('status', '--porcelain', '--untracked-files=normal')),
            'source_digest': digest.hexdigest(), 'source_scope': list(_SOURCE_PATHS)}


def environment_descriptor(root: Path) -> dict:
    import puppetmaster
    return {**source_snapshot(root), 'python': sys.version, 'executable': sys.executable,
            'platform': platform.platform(),
            'puppetmaster_version': importlib.metadata.version('puppetmaster-ai'),
            'puppetmaster_path': str(Path(puppetmaster.__file__).resolve())}


class BackendLifetime:
    def __init__(self, root: Path, receipt: Path):
        self.root = root.resolve()
        self.path = receipt.resolve()
        self.environment = environment_descriptor(self.root)
        self.receipt = None

    def publish(self, port: int, identity: dict, token_file: Path) -> None:
        data = {'schema': 1, 'owner': 'external', 'port': port, 'pid': os.getpid(),
                'launch_id': str(uuid.uuid4()), 'endpoint_id': identity['endpoint_id'],
                'boot_id': identity['boot_id'], 'repo_root': str(self.root),
                'token_file': str(token_file.resolve()), 'environment': self.environment}
        # Existing receipts require an explicit operator decision, never silent adoption.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        self.receipt = data

    def status(self):
        if self.receipt is None:
            return 503, {'code': 'backend_not_ready'}
        try:
            current = environment_descriptor(self.root)
        except Exception:
            return 503, {'code': 'backend_environment_unavailable'}
        if current != self.environment:
            return 409, {'code': 'backend_source_drift', 'error': 'Backend inputs changed; operator restart required.'}
        return 200, self.receipt

    def close(self):
        if self.receipt is None:
            return
        try:
            if json.loads(self.path.read_text()) == self.receipt:
                self.path.unlink()
        except (OSError, ValueError):
            pass


def prepare(receipt: str):
    global _active
    _active = BackendLifetime(Path(__file__).resolve().parents[1], Path(receipt))
    return _active


def get_status():
    if _active is None:
        return 404, {'code': 'backend_not_external'}
    return _active.status()


def _lock_state(fd):
    if os.name == 'posix':
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif os.name == 'nt':
        import msvcrt
        # Windows locks a byte range, including beyond EOF.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        raise RuntimeError('Backend launch lease is unsupported on this platform')


def _require_stale_marker(marker: Path):
    import errno
    import socket
    diagnostic = 'Backend owner is active or uncertain; stop/restart through its owner. State retained.'
    try:
        data = json.loads(marker.read_text())
        pid, port = data['pid'], data['port']
        if type(pid) is not int or pid <= 0 or type(port) is not int or not 0 < port < 65536:
            raise ValueError('invalid marker')
        # os.kill(pid, 0) is an existence probe on POSIX only. Never use it on Windows.
        if os.name != 'posix':
            raise RuntimeError(diagnostic + ' Stale-marker recovery requires a POSIX ESRCH probe.')
        try:
            os.kill(pid, 0)
        except OSError as exc:
            if exc.errno != errno.ESRCH:
                raise RuntimeError(diagnostic) from exc
        else:
            raise RuntimeError(diagnostic)
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                pass
        except OSError as exc:
            if exc.errno == errno.ECONNREFUSED:
                return
            raise RuntimeError(diagnostic) from exc
        raise RuntimeError(diagnostic)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(diagnostic) from exc


@contextmanager
def exclusive_startup(state: Path, receipt: Path = None):
    """Lease cooperating CLI/native launches before import through serve cleanup.

    Keep the lock inode. Direct server imports and network filesystems are not
    serialized. Receipt mode requires fresh evidence; normal mode may recover
    an absent POSIX owner and refused loopback endpoint in the same state.
    """
    state = state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    fd = os.open(state / '.backend-lifetime.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            _lock_state(fd)
        except OSError as exc:
            raise RuntimeError('Backend state is owned by another launcher; restart through its owner. State retained.') from exc
        marker = state / 'backend.json'
        if receipt is not None:
            if receipt.exists() or marker.exists():
                raise RuntimeError('Receipt or backend marker already exists; resolve it through the backend owner first')
        elif marker.exists():
            _require_stale_marker(marker)
        yield
    finally:
        os.close(fd)
