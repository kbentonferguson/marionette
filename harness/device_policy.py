"""Exact device routes and persistent resource bindings. No active-view authority."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .device_grants import DeviceDenied, DeviceUnavailable
from .device_principal import Grant

ROUTES = {
    '/api/device/endpoint': 'endpoint.read',
    '/api/device/session': 'session.read',
    '/api/device/session/events': 'session.events.read',
}


def session_record(path, session_id):
    try:
        records = json.loads(Path(path).read_text())['sessions']
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise DeviceUnavailable()
        matches = [r for r in records if r['id'] == session_id]
        if len(matches) != 1:
            raise DeviceDenied()
        row = matches[0]
        if not isinstance(row.get('created'), (int, float)):
            raise DeviceDenied()
        root = row.get('workspace_root') or row.get('repo')
        if not isinstance(root, str) or not os.path.isabs(root):
            raise DeviceDenied()
        workspace_id = hashlib.sha256(os.path.normcase(os.path.realpath(root)).encode()).hexdigest()
        binding = hashlib.sha256(json.dumps([workspace_id, row.get('created')], sort_keys=True).encode()).hexdigest()
        return {'id': session_id, 'title': row.get('title', ''), 'created': row.get('created'), 'workspace_id': workspace_id}, binding
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DeviceUnavailable() from exc


def enrollment_grants(items, endpoint_id, sessions_path):
    if not isinstance(items, list) or not 1 <= len(items) <= 64:
        raise ValueError()
    grants = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'operation', 'resource_id'}:
            raise ValueError()
        op, rid = item['operation'], item['resource_id']
        if op not in ROUTES.values() or not isinstance(rid, str) or not rid or len(rid) > 200:
            raise ValueError()
        if op == 'endpoint.read':
            if rid != endpoint_id:
                raise DeviceDenied()
            binding = endpoint_id
        else:
            _, binding = session_record(sessions_path, rid)
        grant = Grant(op, rid, binding)
        if grant in grants:
            raise ValueError()
        grants.append(grant)
    return tuple(grants)


def resolve_request(method, target, endpoint_id):
    u = urlsplit(target)
    if method != 'GET' or u.path not in ROUTES or u.fragment or u.netloc or u.scheme:
        raise DeviceDenied()
    qs = parse_qs(u.query, keep_blank_values=True, strict_parsing=True) if u.query else {}
    op = ROUTES[u.path]
    allowed = set() if op == 'endpoint.read' else {'session_id'}
    if op == 'session.events.read':
        allowed |= {'since', 'generation'}
    if set(qs) - allowed or any(len(v) != 1 or not v[0] for v in qs.values()):
        raise ValueError()
    rid = endpoint_id if op == 'endpoint.read' else qs.get('session_id', [''])[0]
    if op != 'endpoint.read' and (not rid or rid.strip() != rid or len(rid) > 200):
        raise ValueError()
    since, generation = 0, None
    for key in ('since', 'generation'):
        if key in qs:
            raw = qs[key][0]
            if not raw.isascii() or not raw.isdecimal() or len(raw) > 16 or str(int(raw)) != raw:
                raise ValueError()
            if key == 'since':
                since = int(raw)
            else:
                generation = int(raw)
    if since and generation is None:
        raise ValueError()
    return op, rid, since, generation
