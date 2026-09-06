"""GET /api/jobs/evidence: active workspace/session only, no store discovery."""
from __future__ import annotations

import re

from ..job_evidence import project_job_evidence
from ..job_scoping import parse_job_origin, parse_job_session_id
from ..paths import same_workspace_path
from .jobs import JobServices


def get_job_evidence(qs: dict, svc: JobServices) -> tuple[int, dict]:
    from puppetmaster.state import state_identity

    state_id = (qs.get('state_id') or [''])[0]
    job_id = (qs.get('job_id') or [''])[0]
    session_id = (qs.get('session_id') or [''])[0]
    repo = (qs.get('repo') or [''])[0]
    source = (qs.get('source') or [''])[0]
    refused = (200, {'code': 'job_evidence_unavailable',
                     'message': 'Evidence is unavailable for this job in the active workspace and session.'})
    if not re.fullmatch(r'job_[a-zA-Z0-9_-]{1,128}', job_id) or not state_id or not session_id or not repo or source != 'harness':
        return refused
    if not same_workspace_path(repo, svc.cfg.repo or ''):
        return refused
    active = getattr(svc.sessions, 'active', None)
    if not active or session_id != active:
        return refused
    try:
        store = svc.get_session().state().store
        if state_identity(store.root) != state_id:
            return refused
        job = store.get_job(job_id)
    except (KeyError, FileNotFoundError):
        return refused
    except Exception:
        return 503, {'error': 'Evidence store is unavailable.'}
    if job is None:
        return refused
    # A label must authorize the read before task payloads or artifacts are loaded.
    if (parse_job_session_id(job.label, []) != session_id
            or parse_job_origin(job.label, []) != 'marionette'):
        return refused
    try:
        tasks = store.list_tasks(job_id)
        for task in tasks:
            payload = task.payload
            if (payload.get('session_id') != session_id
                    or not payload.get('cwd')
                    or not same_workspace_path(payload['cwd'], repo)):
                return refused
        if not tasks:
            return refused
        result = project_job_evidence(store, job, tasks)
        if getattr(svc.sessions, 'active', None) != session_id or not same_workspace_path(repo, svc.cfg.repo or ''):
            return refused
        return 200, result
    except Exception:
        return 503, {'error': 'Evidence records could not be read.'}
