"""Local owned-job export/import commands; no provider or store writes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys

from puppetmaster.models import JobRef
from puppetmaster.state import state_identity

from .artifact_bundle import (BundleError, MAX_ARTIFACT, MAX_ENTRIES,
                              export_bundle, import_bundle, _json, _path, _relative)
from .job_scoping import inspect_store_job_ownership, parse_job_session_id


def _owned(store, ref: JobRef, session_id: str):
    if state_identity(store.root) != ref.state_id:
        raise BundleError('JobRef mismatch')
    if inspect_store_job_ownership(store, ref.job_id, allow_registered_heal=False) is not True:
        raise BundleError('existing Marionette-owned job required')
    job = store.get_job(ref.job_id)
    if parse_job_session_id(job.label, store.list_tasks(ref.job_id)) != session_id:
        raise BundleError('job session does not match session scope')


def _selected(store, ref: JobRef, session_id: str, identities):
    _owned(store, ref, session_id)
    selected = {}
    total = 0
    for identity in identities:
        rows = store.get_artifacts_by_ids(ref.job_id, [identity])
        artifact = rows.get(identity)
        if artifact is None or artifact.job_id != ref.job_id or artifact.id != identity:
            raise BundleError('selected artifact is missing from owned job: ' + identity)
        if artifact.sha256 and artifact.sha256 != store.artifact_hash(artifact):
            raise BundleError('stored artifact hash mismatch: ' + identity)
        data = asdict(artifact)
        encoded = _json(data)
        total += len(encoded)
        if len(encoded) > MAX_ARTIFACT or total > 32 * 1024 * 1024:
            raise BundleError('selected artifact JSON exceeds byte limit')
        selected[identity] = data
    return selected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='harness artifact-bundle',
        description='Export selected local owned-job artifacts/files; import verified files into a new directory.')
    sub = parser.add_subparsers(dest='command', required=True)
    for verb in ('export', 'import'):
        command = sub.add_parser(verb)
        command.add_argument('--state-dir', type=Path, required=True, help='existing origin PM SQLite store; identity must match bundle on import/resume')
        command.add_argument('--job', required=True)
        command.add_argument('--session', required=True)
        command.add_argument('--bundle', type=Path, required=True)
        if verb == 'export':
            command.add_argument('--artifact', action='append', default=[], help='explicit artifact ID; repeatable')
            command.add_argument('--root', type=Path, help='root for explicitly selected relative files')
            command.add_argument('--file', action='append', default=[], help='relative file path; repeatable')
            command.add_argument('--resume', action='store_true', help='reverify and reuse completed objects')
        else:
            command.add_argument('--destination', type=Path, required=True, help='must not already exist')
    args = parser.parse_args(argv)
    try:
        from puppetmaster.store_factory import create_store

        state_dir = _path(args.state_dir)
        if not state_dir.is_dir():
            raise BundleError('existing state directory required')
        store = create_store('sqlite', state_dir, mode='attach')
        ref = JobRef(job_id=args.job, state_id=state_identity(store.root))
        _owned(store, ref, args.session)
        if args.command == 'import':
            manifest = import_bundle(args.bundle, args.destination, ref, session_id=args.session)
        else:
            if len(args.artifact) + len(args.file) > MAX_ENTRIES:
                raise BundleError('too many selected entries')
            if len(set(args.file)) != len(args.file) or len(set(args.artifact)) != len(args.artifact):
                raise BundleError('duplicate selection')
            if args.file and args.root is None:
                raise BundleError('--root is required with --file')
            files = {}
            if args.root is not None:
                root = _path(args.root)
                if not root.is_dir():
                    raise BundleError('root must be an existing directory')
                for name in args.file:
                    files[name] = _path(root / _relative(name))
            artifacts = _selected(store, ref, args.session, args.artifact)
            def validate_source():
                if _selected(store, ref, args.session, args.artifact) != artifacts:
                    raise BundleError('source changed: selected artifacts')
            manifest = export_bundle(ref, files, artifacts, args.bundle,
                                     session_id=args.session, resume=args.resume, validate_source=validate_source)
        print(json.dumps({'job_ref': manifest['job_ref'], 'session_id': manifest['session_id'],
                          'entries': len(manifest['entries']),
                          'snapshot': manifest['snapshot']}))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print('artifact-bundle: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
