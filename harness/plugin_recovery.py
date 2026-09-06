"""Durable install journal; callers hold the registry lock throughout."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
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


def _sync_staged_file(path):
    """Flush an owned copy without changing its bytes or published mode."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AgentPluginError(f'plugin recovery refuses non-private regular file: {path}')
    mode = stat.S_IMODE(info.st_mode)
    readonly = not mode & stat.S_IWUSR
    try:
        if readonly:
            path.chmod(mode | stat.S_IWUSR)
        # Windows fsync requires a writable descriptor, even for copied files.
        with path.open('r+b') as stream:
            if readonly:
                path.chmod(mode)
            os.fsync(stream.fileno())
    finally:
        if readonly:
            path.chmod(mode)


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
            _sync_staged_file(Path(parent) / name)
        sync_directory(Path(parent))
    atomic_bytes(transaction / MARKER, json.dumps(marker).encode())
    sync_directory(root)


def _retirement_entries(tree):
    """Preflight the whole obsolete tree before changing any attributes."""
    entries = {}

    def visit(path):
        info = path.lstat()
        if (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            raise AgentPluginError(f'plugin retirement refuses non-private plain entry: {path}')
        entries[str(path.relative_to(tree))] = [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)]
        if stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():
                visit(child)

    visit(tree)
    if set(p.name for p in tree.iterdir()) - {MARKER, 'old', 'new'}:
        raise AgentPluginError(f'plugin retirement refuses unexpected contents: {tree}')
    return entries


def _remove_retired(retired, verify=None):
    try:
        entries = _retirement_entries(retired)
        if len(entries) == 1:
            # A crash after unlinking the last marker leaves no data to authorize.
            retired.chmod(stat.S_IMODE(retired.lstat().st_mode) | stat.S_IWUSR)
            retired.rmdir()
            sync_directory(retired.parent)
            return
        marker = json.loads((retired / MARKER).read_text())
        if (marker['version'] != 1 or marker['phase'] not in ('pending', 'committed')
                or marker['root'] != identity(retired.parent)
                or marker['transaction'] != identity(retired)):
            raise AgentPluginError('invalid retired journal identity or schema')
        if 'retirement' not in marker:
            # Older retirees have no inventory: only intact, verified payloads
            # can establish one. Incomplete legacy evidence remains blocked.
            if verify is None:
                raise AgentPluginError('missing retirement inventory')
            for name in ('old', 'new'):
                path = retired / name
                if path.exists():
                    expected = marker[name]
                    if (expected is None or identity(path) != expected['identity']
                            or verify(path) != expected['digest']):
                        raise AgentPluginError('legacy retired package does not match journal')
            marker['retirement'] = {name: info for name, info in entries.items() if name != MARKER}
            for path in (retired, retired / MARKER):
                mode = stat.S_IMODE(path.lstat().st_mode)
                if not mode & stat.S_IWUSR:
                    path.chmod(mode | stat.S_IWUSR)
            atomic_bytes(retired / MARKER, json.dumps(marker).encode())
            entries = _retirement_entries(retired)
        expected = marker['retirement']
        if any(expected.get(name) != info for name, info in entries.items() if name != MARKER):
            raise AgentPluginError('retired contents do not match retirement inventory')
        # Keep the marker until all payloads are gone so interrupted cleanup is retryable.
        paths = [retired / name for name in entries if name not in ('.', MARKER)]
        for path in [retired] + paths + [retired / MARKER]:
            info = path.lstat()
            if [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)] != entries[str(path.relative_to(retired))]:
                raise AgentPluginError(f'plugin retirement entry changed: {path}')
            if (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise AgentPluginError(f'plugin retirement entry is no longer private and plain: {path}')
            if not info.st_mode & stat.S_IWUSR:
                path.chmod(stat.S_IMODE(info.st_mode) | stat.S_IWUSR)
        for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
            if entries[str(path.relative_to(retired))][2] == stat.S_IFDIR:
                path.rmdir()
            else:
                path.unlink()
        (retired / MARKER).unlink()
        retired.rmdir()
        sync_directory(retired.parent)
    except Exception as exc:
        raise AgentPluginError(f'plugin retirement blocked; evidence retained at {retired}: {exc}') from exc


def retire(transaction):
    retired = transaction.with_name(transaction.name.replace('.install-', '.retired-', 1))
    if retired.exists() or retired.is_symlink():
        raise AgentPluginError(f'plugin recovery refuses occupied retirement path: {retired}')
    entries = _retirement_entries(transaction)
    marker = json.loads((transaction / MARKER).read_text())
    marker['retirement'] = {name: info for name, info in entries.items() if name != MARKER}
    atomic_bytes(transaction / MARKER, json.dumps(marker).encode())
    os.replace(transaction, retired)
    sync_directory(transaction.parent)
    _remove_retired(retired)


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
    for retired in sorted(root.glob('.retired-*')):
        _remove_retired(retired, verify)
    for transaction in sorted(root.glob('.install-*')):
        if transaction.is_symlink():
            raise AgentPluginError(f'plugin recovery refuses symlink: {transaction}')
        if any(path.exists() or path.is_symlink()
               for path in (transaction / MARKER, transaction / 'old')):
            recover_one(transaction, verify)
