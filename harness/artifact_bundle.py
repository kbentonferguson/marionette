"""Bounded local CAS bundles. The manifest is the completion marker.

Only completed objects resume; incomplete copies restart. Import never executes
content or upserts the source store. Callers own the local directories exclusively
while operating; remote identities and hostile concurrent directory writers are
outside this single-user filesystem protocol.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import tempfile
from typing import Callable, Mapping, Optional

from puppetmaster.models import JobRef

CHUNK = 1024 * 1024
MAX_FILE = 256 * CHUNK
MAX_TOTAL = 1024 * CHUNK
MAX_ENTRIES = 256
MAX_MANIFEST = 2 * CHUNK
MAX_ARTIFACT = 8 * CHUNK


class BundleError(ValueError):
    pass


def _validate_scope(job: JobRef, session_id: str):
    for value in (job.job_id, job.state_id, session_id):
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise BundleError('invalid job identity or session scope')


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise BundleError('invalid relative path')
    for part in value.split('/'):
        if (not part or part in ('.', '..') or part[-1] in ' .'
                or re.search(r'[\\:<>"|?*\x00-\x1f\x7f]', part)
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                    *('COM' + str(i) for i in range(1, 10)),
                    *('LPT' + str(i) for i in range(1, 10))}):
            raise BundleError('unsafe relative path: ' + value)
    return value


def _path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for parent in (*reversed(path.parents), path):
        if parent.is_symlink():
            raise BundleError('symlink path: ' + str(parent))
    return path


def _fingerprint(path: Path):
    info = _path(path).stat()
    if not stat.S_ISREG(info.st_mode):
        raise BundleError('source must be a regular file')
    if info.st_size > MAX_FILE:
        raise BundleError('file exceeds byte limit')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _stream(path: Path, output=None, *, limit: Optional[int] = None):
    before = _fingerprint(path)
    limit = MAX_FILE if limit is None else limit
    if before[2] > limit:
        raise BundleError('file exceeds declared byte limit')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(os.open(path, flags), 'rb') as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != before[:2]:
            raise BundleError('source changed while opening')
        while True:
            block = source.read(CHUNK)
            if not block:
                break
            size += len(block)
            if size > limit:
                raise BundleError('file exceeds byte limit')
            digest.update(block)
            if output is not None:
                output.write(block)
    if _fingerprint(path) != before:
        raise BundleError('source changed during read')
    return digest.hexdigest(), size


def _read_json(path: Path):
    _fingerprint(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_MANIFEST + 1)
    if len(data) > MAX_MANIFEST:
        raise BundleError('manifest exceeds byte limit')
    try:
        return json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise BundleError('invalid bundle JSON') from exc


def _exclusive(path: Path, data: bytes):
    with path.open('xb') as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())


def _publish_manifest(destination: Path, manifest: dict):
    data = _json(manifest)
    if len(data) > MAX_MANIFEST:
        raise BundleError('manifest exceeds byte limit')
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        staged = Path(temporary) / 'manifest.json'
        _exclusive(staged, data)
        os.link(staged, destination / 'manifest.json')


def _paths(entries):
    seen = set()
    for entry in entries:
        path = _relative(entry['path']).casefold()
        if path in seen or any(path.startswith(p + '/') or p.startswith(path + '/') for p in seen):
            raise BundleError('duplicate or overlapping paths')
        seen.add(path)


def export_bundle(job: JobRef, files: Mapping[str, Path], artifacts: Mapping[str, dict],
                  destination: Path, *, session_id: str, resume: bool = False,
                  validate_source: Optional[Callable[[], None]] = None) -> dict:
    """Export an explicit selection. Source metadata is rechecked before commit."""
    _validate_scope(job, session_id)
    if not 0 < len(files) + len(artifacts) <= MAX_ENTRIES:
        raise BundleError('select between 1 and 256 entries')
    fingerprints = {}
    entries = []
    artifact_bytes = {}
    for name, source in files.items():
        source = _path(Path(source))
        fingerprints[name] = _fingerprint(source)
        entries.append({'kind': 'file', 'identity': name, 'path': 'files/' + _relative(name)})
    for identity, artifact in artifacts.items():
        if '/' in _relative(identity):
            raise BundleError('artifact identity must be a single path component')
        data = _json(artifact)
        if len(data) > MAX_ARTIFACT:
            raise BundleError('artifact exceeds byte limit')
        artifact_bytes[identity] = data
        if sum(map(len, artifact_bytes.values())) > 32 * CHUNK:
            raise BundleError('selected artifact JSON exceeds byte limit')
        entries.append({'kind': 'artifact', 'identity': identity,
                        'path': 'artifacts/' + identity + '.json'})
    _paths(entries)
    total = sum(f[2] for f in fingerprints.values()) + sum(map(len, artifact_bytes.values()))
    if total > MAX_TOTAL:
        raise BundleError('bundle exceeds total byte limit')
    plan = {'schema_version': 2, 'job_ref': job.as_dict(), 'session_id': session_id,
            'files': {k: list(v) for k, v in fingerprints.items()},
            'artifacts': {k: hashlib.sha256(v).hexdigest() for k, v in artifact_bytes.items()}}
    destination = _path(Path(destination))
    marker = destination / 'in-progress.json'
    if resume:
        if _read_json(marker) != plan:
            raise BundleError('source changed or resume selection differs')
        if (destination / 'manifest.json').exists():
            raise BundleError('bundle already published')
    else:
        destination.mkdir()
        _exclusive(marker, _json(plan))
        (destination / 'objects').mkdir()
    objects = _path(destination / 'objects')
    if not objects.is_dir():
        raise BundleError('missing objects directory')
    if shutil.disk_usage(destination).free < total + MAX_MANIFEST:
        raise BundleError('insufficient free disk space')
    for entry in entries:
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            staged = Path(temporary) / 'object'
            with staged.open('xb') as target:
                if entry['kind'] == 'file':
                    digest, size = _stream(_path(Path(files[entry['identity']])), target)
                else:
                    data = artifact_bytes[entry['identity']]
                    target.write(data)
                    digest, size = hashlib.sha256(data).hexdigest(), len(data)
                target.flush()
                os.fsync(target.fileno())
            object_path = _path(objects / digest)
            if object_path.exists():
                if _stream(object_path) != (digest, size):
                    raise BundleError('corrupt resumed object')
            else:
                if _stream(staged) != (digest, size):
                    raise BundleError('staged object verification failed')
                os.link(staged, object_path)
            if _stream(object_path) != (digest, size):
                raise BundleError('object verification failed')
            entry.update(sha256=digest, size=size)
    if validate_source is not None:
        validate_source()
    for name, before in fingerprints.items():
        if _fingerprint(Path(files[name])) != before:
            raise BundleError('source changed before manifest publication')
    try:
        kernel_version = version('puppetmaster-ai')
    except PackageNotFoundError:
        kernel_version = 'unavailable'
    manifest = {'schema_version': 2, 'job_ref': job.as_dict(), 'session_id': session_id,
                'environment': {'system': platform.system(), 'python': platform.python_version(),
                                'puppetmaster': kernel_version},
                'snapshot': {'status': 'partial', 'reason': 'explicit selection; no atomic PM snapshot'},
                'entries': entries}
    _publish_manifest(destination, manifest)
    return manifest


def _manifest(bundle: Path, expected_job: JobRef, session_id: str):
    manifest = _read_json(bundle / 'manifest.json')
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 2):
        raise BundleError('unsupported manifest schema')
    if manifest.get('job_ref') != expected_job.as_dict():
        raise BundleError('JobRef mismatch')
    if manifest.get('session_id') != session_id:
        raise BundleError('session scope mismatch')
    snapshot = manifest.get('snapshot')
    if not isinstance(snapshot, dict) or snapshot.get('status') != 'partial':
        raise BundleError('unsupported snapshot status')
    if not isinstance(manifest.get('environment'), dict):
        raise BundleError('missing environment descriptor')
    entries = manifest.get('entries')
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_ENTRIES:
        raise BundleError('invalid entry count')
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise BundleError('invalid entry')
        kind, identity = entry.get('kind'), entry.get('identity')
        if kind not in ('artifact', 'file') or not isinstance(identity, str):
            raise BundleError('invalid entry identity')
        _relative(identity)
        if kind == 'artifact' and '/' in identity:
            raise BundleError('invalid artifact identity')
        expected_path = ('files/' + identity if kind == 'file' else 'artifacts/' + identity + '.json')
        if entry.get('path') != expected_path:
            raise BundleError('entry path does not match identity')
        if not isinstance(entry.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise BundleError('invalid digest')
        size = entry.get('size')
        if type(size) is not int or size < 0 or size > (MAX_ARTIFACT if kind == 'artifact' else MAX_FILE):
            raise BundleError('invalid entry size')
        total += size
    _paths(entries)
    if total > MAX_TOTAL:
        raise BundleError('bundle exceeds total byte limit')
    return manifest, total


def import_bundle(bundle: Path, destination: Path, expected_job: JobRef, *,
                  session_id: str) -> dict:
    """Restore files for an origin JobRef and session; never update PM state.

    Callers resolve the current store identity. All bytes are verified before
    creating the new destination; existing destinations are never overwritten.
    """
    _validate_scope(expected_job, session_id)
    bundle, destination = _path(Path(bundle)), _path(Path(destination))
    if destination.exists():
        raise BundleError('destination already exists')
    manifest, total = _manifest(bundle, expected_job, session_id)
    if shutil.disk_usage(destination.parent).free < total + MAX_MANIFEST:
        raise BundleError('insufficient free disk space')
    with tempfile.TemporaryDirectory(prefix='.bundle-verify-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        for entry in manifest['entries']:
            target = stage / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                observed = _stream(_path(bundle / 'objects' / entry['sha256']), output,
                                   limit=entry['size'])
                output.flush()
                os.fsync(output.fileno())
            if observed != (entry['sha256'], entry['size']):
                raise BundleError('object digest or size mismatch')
            if _stream(target, limit=entry['size']) != observed:
                raise BundleError('staged file verification failed')
        # mkdir reserves the name without rename's empty-directory overwrite.
        destination.mkdir()
        for entry in manifest['entries']:
            target = _path(destination / entry['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(stage / entry['path'], target)
        _publish_manifest(destination, manifest)
    return manifest
