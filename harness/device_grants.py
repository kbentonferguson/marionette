"""Product-local credential store. A transaction also fences bounded response writes."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
import uuid

from .device_principal import Grant, RequestPrincipal

_TOKEN = re.compile(r'dev1\.([0-9a-f-]{36})\.([0-9a-f]{64})\Z')


class DeviceDenied(Exception):
    pass


class DeviceUnavailable(Exception):
    pass


def _digest(secret):
    return hashlib.sha256(b'marionette-device-v1\0' + secret.encode('ascii')).hexdigest()


def storage_supported():
    return os.name == 'posix'


def _metadata(revision, digest, encoded_grants):
    if type(revision) is not int or revision < 1:
        raise DeviceUnavailable()
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise DeviceUnavailable()
    try:
        items = json.loads(encoded_grants)
        if not isinstance(items, list) or not 1 <= len(items) <= 64:
            raise ValueError()
        grants = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {'operation', 'resource_id', 'binding'}:
                raise ValueError()
            if any(not isinstance(value, str) or not value for value in item.values()):
                raise ValueError()
            if item['operation'] not in ('endpoint.read', 'session.read', 'session.events.read'):
                raise ValueError()
            grant = Grant(**item)
            if grant in grants:
                raise ValueError()
            grants.append(grant)
        return tuple(grants)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise DeviceUnavailable() from exc


class DeviceGrantStore:
    def __init__(self, directory, endpoint_id):
        self.directory = Path(directory)
        self.path = self.directory / 'grants.sqlite'
        self.endpoint_id = endpoint_id

    def _permissions(self):
        # POSIX mode checks cannot prove an NTFS ACL; unsupported hosts fail closed.
        if not storage_supported():
            raise DeviceUnavailable()
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        for path, is_dir in ((self.directory, True), (self.path, False)):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if is_dir:
                    raise DeviceUnavailable()
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                info = path.lstat()
            expected = stat.S_ISDIR if is_dir else stat.S_ISREG
            if not expected(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DeviceUnavailable()
            if not is_dir and info.st_nlink != 1:
                raise DeviceUnavailable()

    @contextmanager
    def transaction(self):
        db = None
        try:
            self._permissions()
            db = sqlite3.connect(str(self.path), timeout=3, isolation_level=None)
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, endpoint TEXT NOT NULL, label TEXT NOT NULL, created REAL NOT NULL, revoked REAL, revision INTEGER NOT NULL, digest TEXT NOT NULL, grants TEXT NOT NULL)')
            yield db
            db.commit()
        except (sqlite3.Error, OSError) as exc:
            raise DeviceUnavailable() from exc
        finally:
            if db is not None:
                db.close()

    def enroll(self, db, label, grants):
        device_id, secret = str(uuid.uuid4()), secrets.token_hex(32)
        db.execute('INSERT INTO devices VALUES (?,?,?,?,NULL,1,?,?)',
                   (device_id, self.endpoint_id, label, time.time(), _digest(secret),
                    json.dumps([g.__dict__ for g in grants])))
        return {'ok': True, 'device_id': device_id, 'credential': f'dev1.{device_id}.{secret}', 'grants_revision': 1}

    def authenticate(self, db, token):
        match = _TOKEN.fullmatch(token)
        if match is None:
            raise DeviceDenied()
        row = db.execute('SELECT endpoint,revoked,revision,digest,grants FROM devices WHERE id=?', (match[1],)).fetchone()
        if row is None or row[0] != self.endpoint_id or row[1] is not None:
            raise DeviceDenied()
        grants = _metadata(row[2], row[3], row[4])
        if not hmac.compare_digest(row[3], _digest(match[2])):
            raise DeviceDenied()
        return RequestPrincipal(match[1], row[0], row[2], grants)

    def list(self, db):
        return [{'device_id': r[0], 'label': r[1], 'created_at': r[2], 'revoked_at': r[3],
                 'grants_revision': r[4], 'grants': [g.__dict__ for g in _metadata(r[4], r[6], r[5])]}
                for r in db.execute('SELECT id,label,created,revoked,revision,grants,digest FROM devices WHERE endpoint=?', (self.endpoint_id,))]

    def revoke(self, db, device_id):
        row = db.execute('SELECT revoked FROM devices WHERE id=? AND endpoint=?', (device_id, self.endpoint_id)).fetchone()
        if row is None:
            return False
        if row[0] is None:
            db.execute('UPDATE devices SET revoked=?, revision=revision+1 WHERE id=?', (time.time(), device_id))
        return True
