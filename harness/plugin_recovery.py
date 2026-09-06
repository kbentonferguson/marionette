"""Durable install journal; callers hold the registry lock throughout."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from .agent_plugins import AgentPluginError

STATE_FILES = ('enabled.json', 'capabilities.json')
MARKER = 'transaction.json'


def sync_directory(path):
    # Windows does not expose directory fsync through Python's os.open.
    if os.name != 'nt':
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_bytes(path, payload):
    temporary_dir = path.parent.parent if path.name == MARKER else path.parent
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=str(temporary_dir))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
        if temporary_dir != path.parent:
            sync_directory(temporary_dir)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identity(path):
    info = path.lstat()
    return [info.st_dev, info.st_ino]


def plain_tree(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise AgentPluginError(f'plugin recovery requires a plain directory: {path}')
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            mode = (Path(parent) / name).lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise AgentPluginError(f'plugin recovery refuses special file: {Path(parent) / name}')


def state_snapshot(root):
    result = {}
    for name in STATE_FILES:
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise AgentPluginError(f'plugin recovery refuses state path: {path}')
        result[name] = base64.b64encode(path.read_bytes()).decode('ascii') if path.exists() else None
    return result


@contextmanager
def process_lock(root):
    root.parent.mkdir(parents=True, exist_ok=True)
    path = root.parent / '.plugin-registry.lock'
    if path.is_symlink():
        raise AgentPluginError('plugin registry lock cannot be a symlink')
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'r+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            if root.is_symlink():
                raise AgentPluginError('plugin install root cannot be a symlink')
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def prepare(transaction, dest, verify):
    root = transaction.parent
    plain_tree(transaction)
    old = None
    if dest.exists() or dest.is_symlink():
        plain_tree(dest)
        old = {'identity': identity(dest), 'digest': verify(dest)}
    new = transaction / 'new'
    marker = {'version': 1, 'root': identity(root), 'transaction': identity(transaction),
              'id': dest.name, 'old': old,
              'new': {'identity': identity(new), 'digest': verify(new)},
              'state': state_snapshot(root), 'phase': 'pending'}
    for parent, _, files in os.walk(transaction):
        for name in files:
            with (Path(parent) / name).open('rb') as stream:
                os.fsync(stream.fileno())
        sync_directory(Path(parent))
    atomic_bytes(transaction / MARKER, json.dumps(marker).encode())
    sync_directory(root)


def retire(transaction):
    retired = transaction.with_name(transaction.name.replace('.install-', '.retired-', 1))
    if retired.exists() or retired.is_symlink():
        raise AgentPluginError(f'plugin recovery refuses occupied retirement path: {retired}')
    os.replace(transaction, retired)
    sync_directory(transaction.parent)
    shutil.rmtree(retired)


def commit(transaction):
    marker = json.loads((transaction / MARKER).read_text())
    marker['phase'] = 'committed'
    marker['state'] = state_snapshot(transaction.parent)
    atomic_bytes(transaction / MARKER, json.dumps(marker).encode())


def recover_one(transaction, verify):
    root = transaction.parent
    try:
        plain_tree(transaction)
        if set(p.name for p in transaction.iterdir()) - {MARKER, 'old', 'new'}:
            raise ValueError('unexpected transaction contents')
        marker = json.loads((transaction / MARKER).read_text())
        if (marker['version'] != 1 or marker['root'] != identity(root)
                or marker['transaction'] != identity(transaction)
                or not isinstance(marker['id'], str)
                or re.fullmatch(r'[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?', marker['id']) is None
                or len(marker['id']) > 64
                or marker['phase'] not in ('pending', 'committed')
                or set(marker['state']) != set(STATE_FILES)):
            raise ValueError('invalid journal identity or schema')
        snapshots = {name: None if value is None else base64.b64decode(value, validate=True)
                     for name, value in marker['state'].items()}
        state_snapshot(root)  # Validate every write target before any mutation.
        dest, old, new = root / marker['id'], transaction / 'old', transaction / 'new'

        def matches(path, expected):
            if expected is None:
                return False
            plain_tree(path)
            return identity(path) == expected['identity'] and verify(path) == expected['digest']

        old_exists, dest_exists = old.exists(), dest.exists() or dest.is_symlink()
        if old_exists and not matches(old, marker['old']):
            raise ValueError('old package does not match journal')
        if new.exists() and not matches(new, marker['new']):
            raise ValueError('staged package does not match journal')
        dest_old = dest_exists and matches(dest, marker['old'])
        dest_new = dest_exists and not dest_old and matches(dest, marker['new'])
        if dest_exists and not (dest_old or dest_new):
            raise ValueError('destination is foreign or damaged')
        if marker['phase'] == 'committed':
            if not dest_new or state_snapshot(root) != marker['state']:
                raise ValueError('committed package or state does not match journal')
        else:
            if marker['old'] is not None and not (old_exists or dest_old):
                raise ValueError('old package is missing')
            if old_exists and dest_old:
                raise ValueError('duplicate old package')
            if dest_new:
                if new.exists():
                    raise ValueError('duplicate new package')
                os.replace(dest, new)
                sync_directory(root)
                sync_directory(transaction)
            if old_exists:
                os.replace(old, dest)
                sync_directory(root)
                sync_directory(transaction)
            for name, payload in snapshots.items():
                path = root / name
                if payload is None:
                    if path.exists():
                        path.unlink()
                        sync_directory(root)
                else:
                    atomic_bytes(path, payload)
        retire(transaction)
    except Exception as exc:
        raise AgentPluginError(f'plugin recovery blocked; evidence retained at {transaction}: {exc}') from exc


def recover(root, verify):
    if not root.exists():
        return
    for transaction in sorted(root.glob('.install-*')):
        if transaction.is_symlink():
            raise AgentPluginError(f'plugin recovery refuses symlink: {transaction}')
        if any(path.exists() or path.is_symlink()
               for path in (transaction / MARKER, transaction / 'old')):
            recover_one(transaction, verify)
