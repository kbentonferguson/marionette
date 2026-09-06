"""Offline paired evaluation of recorded PM jobs; never launches workers."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from pmharness.analysis_bench import ANALYSIS_QUESTIONS, BENCHMARK_VERSION, score_analysis

QUESTIONS = {q.id: q for q in ANALYSIS_QUESTIONS}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def seal(value):
    return dict(value, sha256=digest(value))


def verify(value):
    if value.get('sha256') != digest({k: v for k, v in value.items() if k != 'sha256'}):
        raise ValueError('content hash mismatch')


def manifest(repo):
    repo = Path(repo)
    paths = sorted({q.source.split(':')[0] for q in QUESTIONS.values()} |
                   {'pmharness/analysis_bench.py'})
    return seal({'version': 1, 'scorer_version': BENCHMARK_VERSION,
                 'files': {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in paths},
                 'tasks': [{'id': q.id, 'split': 'train' if q.id == 'registry_return' else 'heldout',
                            'task_sha256': digest(asdict(q))} for q in QUESTIONS.values()]})


def validate_manifest(value, repo):
    verify(value)
    if value != manifest(repo):
        raise ValueError('manifest differs from fixed task, split, source or scorer snapshot')


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def ingest(store, job_id, task_id, snapshot_sha256):
    """Capture public records from one already existing job, without repricing."""
    from puppetmaster.models import JobRef
    from puppetmaster.state import state_identity

    job = store.get_job(job_id)
    if job is None:
        raise ValueError('job missing')
    tasks = store.list_tasks(job_id)
    artifacts = store.list_artifacts(job_id)
    if any(t.job_id != job_id for t in tasks) or any(a.job_id != job_id for a in artifacts):
        raise ValueError('foreign record')
    task_ids = {t.id for t in tasks}
    if any(a.task_id not in task_ids for a in artifacts):
        raise ValueError('orphan artifact')
    # A second read detects ordinary concurrent updates, not an atomic transaction.
    if job != store.get_job(job_id) or tasks != store.list_tasks(job_id) or artifacts != store.list_artifacts(job_id):
        raise ValueError('job changed during capture')
    return seal({'task_id': task_id, 'snapshot_sha256': snapshot_sha256,
                 'job_ref': JobRef(job_id=job.id, state_id=state_identity(store.root)).as_dict(),
                 'job_status': str(job.status), 'tasks': [asdict(t) for t in tasks],
                 'artifacts': [asdict(a) for a in artifacts], 'cost_receipt': job.cost_receipt,
                 'latency_ms': None, 'attempt_cost': None,
                 'attempt_cost_reason': 'PM 1.22.48 selected receipt does not expose all retry spend'})


def run_record(policy, config, snapshot, records, *, origin):
    if not policy or not isinstance(config, dict) or origin not in ('recorded', 'fixture'):
        raise ValueError('policy, config and recorded/fixture origin required')
    return seal({'policy': policy, 'config': config, 'config_sha256': digest(config),
                 'manifest_sha256': snapshot['sha256'], 'origin': origin, 'records': records})


def outcome(record):
    from puppetmaster.cost import is_cost_final_job_status, valid_terminal_cost_receipt
    from puppetmaster.models import Artifact, JobStatus
    from puppetmaster.validation import validation_status_of

    q = QUESTIONS[record['task_id']]
    claims = [a['payload'].get('claim', '') for a in record['artifacts'] if a['type'] == 'finding'
              and validation_status_of(Artifact(**a)) not in ('stale', 'superseded')]
    scored = score_analysis(q, json.dumps(claims))
    completed = (record['job_status'] == 'complete' and bool(record['tasks'])
                 and all(t['status'] == 'complete' for t in record['tasks']))
    success = completed and scored['hit']
    receipt = record.get('cost_receipt')
    selected = None
    try:
        final = is_cost_final_job_status(JobStatus(record['job_status']))
    except ValueError:
        final = False
    if final and valid_terminal_cost_receipt(receipt, record['job_ref']['job_id']):
        actual = receipt['actual_cost']
        value = actual.get('total_marginal_cost_usd')
        if (number(value) and type(actual.get('priced_tasks')) is int
                and actual['priced_tasks'] == len(record['tasks']) > 0
                and type(actual.get('unpriced_tasks')) is int and actual['unpriced_tasks'] == 0):
            selected = value
    return {'task_id': q.id, 'success': success, 'score': scored,
            'completion_gate': 'passed' if completed else 'failed',
            'selected_marginal_usd': selected,
            'all_attempt_marginal_usd': None,
            'frozen_receipt': receipt,
            'nominal_usage_usd': (receipt.get('estimate_drift', {}).get('nominal_usage_cost_usd')
                                  if isinstance(receipt, dict) else None),
            'token_usage': receipt.get('token_usage') if isinstance(receipt, dict) else None,
            'latency_ms': record.get('latency_ms'),
            'abstention': scored['status'] in ('incomplete', 'unscorable')}


def compare(snapshot, left, right, repo):
    validate_manifest(snapshot, repo)
    expected = {t['id'] for t in snapshot['tasks'] if t['split'] == 'heldout'}
    reasons = []
    reports = []
    pairs = []
    all_refs = set()
    for run in (left, right):
        verify(run)
        if run['config_sha256'] != digest(run['config']) or run['manifest_sha256'] != snapshot['sha256']:
            raise ValueError('run identity or snapshot mismatch')
        if run['origin'] not in ('recorded', 'fixture'):
            raise ValueError('unknown origin')
        if run['origin'] == 'fixture':
            reasons.append('fixtures are ingestion evidence, not model quality evidence')
        indexed = {}
        refs = set()
        for record in run['records']:
            verify(record)
            task_id = record['task_id']
            if task_id not in expected or task_id in indexed:
                raise ValueError('unexpected or duplicate heldout task')
            if record['snapshot_sha256'] != snapshot['sha256']:
                raise ValueError('record snapshot mismatch')
            ref = record['job_ref']
            key = (ref['state_id'], ref['job_id'])
            if not all(key) or key in refs or key in all_refs:
                raise ValueError('missing or reused job reference')
            refs.add(key)
            indexed[task_id] = outcome(record)
        all_refs.update(refs)
        pairs.append(indexed)
        missing = expected - indexed.keys()
        if missing:
            reasons.append('incomplete heldout coverage; unmatched tasks are not compared')
        rows = [indexed.get(t, {'task_id': t, 'success': False, 'missing': True}) for t in sorted(expected)]
        successes = sum(r['success'] for r in rows)
        costs = [r.get('selected_marginal_usd') for r in rows]
        latencies = [r.get('latency_ms') for r in rows]
        known_latency = sorted(x for x in latencies if number(x))
        selected_total = sum(costs) if all(number(x) for x in costs) else None
        reports.append({'policy': run['policy'], 'config_sha256': run['config_sha256'],
                        'run_sha256': run['sha256'], 'n': len(expected), 'observed': len(indexed),
                        'missing': len(missing), 'successes': successes, 'failures': len(expected) - successes,
                        'success_rate': successes / len(expected),
                        'abstentions': sum(r.get('abstention', False) for r in rows),
                        'unknown_selected_cost': sum(x is None for x in costs),
                        'selected_marginal_usd': selected_total,
                        'all_attempt_marginal_usd': None, 'unknown_attempt_cost': len(expected),
                        'cost_per_verified_completion_usd': None,
                        'latency_samples': len(known_latency),
                        'unknown_latency': len(expected) - len(known_latency),
                        'latency_p95_ms': (known_latency[math.ceil(.95 * len(known_latency)) - 1]
                                           if len(known_latency) == len(expected) else None),
                        'rows': rows})
    reasons.append('all-attempt spend unavailable from PM 1.22.48 public selected receipts')
    if any(r['unknown_latency'] for r in reports):
        reasons.append('end-to-end monotonic latency evidence missing')
    paired = []
    if all(set(p) == expected for p in pairs):
        paired = [{'task_id': t, 'left_success': pairs[0][t]['success'],
                   'right_success': pairs[1][t]['success']} for t in sorted(expected)]
    return {'verdict': 'INCONCLUSIVE', 'reasons': sorted(set(reasons)),
            'policies': reports, 'paired_n': len(paired), 'pairs': paired,
            'savings_fraction': None, 'quality_improvement_claim': None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('manifest')
    make.add_argument('--repo', default='.')
    capture = commands.add_parser('ingest')
    capture.add_argument('manifest')
    capture.add_argument('state')
    capture.add_argument('job_id')
    capture.add_argument('task_id', choices=QUESTIONS)
    capture.add_argument('--repo', default='.')
    compare_cmd = commands.add_parser('compare')
    compare_cmd.add_argument('manifest')
    compare_cmd.add_argument('left')
    compare_cmd.add_argument('right')
    compare_cmd.add_argument('--repo', default='.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'manifest':
            result = manifest(args.repo)
        else:
            snapshot = json.loads(Path(args.manifest).read_text())
            validate_manifest(snapshot, args.repo)
            if args.command == 'ingest':
                from puppetmaster.store_factory import create_store
                if not Path(args.state).is_dir():
                    raise ValueError('existing state directory required')
                result = ingest(create_store('sqlite', args.state), args.job_id, args.task_id, snapshot['sha256'])
            else:
                result = compare(snapshot, json.loads(Path(args.left).read_text()),
                                 json.loads(Path(args.right).read_text()), args.repo)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result = {'verdict': 'INCONCLUSIVE', 'error': str(exc)}
        print(json.dumps(result, allow_nan=False))
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
