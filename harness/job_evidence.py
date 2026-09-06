"""Content-free evidence for one selected, already authorized Puppetmaster job."""
from __future__ import annotations

import math
from dataclasses import asdict

from puppetmaster.consumption import build_attempt_consumption_report
from puppetmaster.cost import is_cost_final_job_status, valid_terminal_cost_receipt
from puppetmaster.models import JobRef
from puppetmaster.state import state_identity

MAX_EVIDENCE_ROWS = 100


class _AuthorizedLedger:
    def __init__(self, store, job_id, task_ids):
        self.store = store
        self.job_id = job_id
        self.task_ids = task_ids

    def list_attempts(self, job_id):
        attempts = self.store.list_attempts(job_id)
        for attempt in attempts:
            if attempt.job_id != self.job_id or attempt.task_id not in self.task_ids:
                raise ValueError('Attempt outside authorized tasks')
        return attempts

    def list_usage_observations(self, job_id):
        observations = self.store.list_usage_observations(job_id)
        for observation in observations:
            if observation.job_id != self.job_id:
                raise ValueError('Mismatched observation job')
        return observations


def _consumption_metrics(totals):
    metrics = asdict(totals)
    for metric in metrics.values():
        # PM's empty subtotal is an arithmetic zero, not measured consumption.
        if not metric['known_attempts']:
            metric['known_subtotal'] = None
        for field in ('total', 'known_subtotal'):
            value = metric[field]
            if isinstance(value, float) and not math.isfinite(value):
                metric[field] = None
                metric['status'] = 'unknown'
    return metrics


def project_job_evidence(store, job, tasks: list) -> dict:
    artifacts = store.list_artifacts(job.id)
    task_ids = {task.id for task in tasks}
    # One public read per ledger, with the existing containment checks retained.
    report = build_attempt_consumption_report(_AuthorizedLedger(store, job.id, task_ids), job.id)
    attempt_rows = []
    for row in report.attempts[:MAX_EVIDENCE_ROWS]:
        attempt = row.attempt
        attempt_rows.append({
            'attempt_id': attempt.attempt_id, 'run_id': attempt.run_id,
            'task_id': attempt.task_id, 'adapter': attempt.adapter,
            'provider': attempt.provider, 'model': attempt.model,
            'outcome': 'unavailable', 'consumption': _consumption_metrics(row.totals),
        })
    receipt = job.cost_receipt
    amount = None
    cost_source = 'unavailable'
    if is_cost_final_job_status(job.status) and valid_terminal_cost_receipt(receipt, job.id):
        value = receipt['actual_cost'].get('total_marginal_cost_usd')
        actual = receipt['actual_cost']
        if (type(value) in (int, float) and math.isfinite(value) and value >= 0
                and type(actual.get('priced_tasks')) is int and actual['priced_tasks'] > 0
                and type(actual.get('unpriced_tasks')) is int and actual['unpriced_tasks'] == 0):
            amount = value
        cost_source = 'terminal_cost_receipt'
    missing = [
        'No durable request, turn or action link to this job is available.',
        'Request integrity covers normalized driver inputs and supported wire bodies; it does not prove job outcomes.',
        'All-attempt spend is unknown: the public ledger does not certify complete invocation coverage.',
        'Attempt outcomes are unavailable from public attempt records; current task status is not an attempt outcome.',
        'Equal usage snapshots reconcile; conflicting values remain unknown. API-equivalent estimates are not spend.',
        'Recorded artifacts and test markers have not been independently verified by this view.',
    ]
    if not artifacts:
        missing.append('No artifacts recorded.')
    if amount is None:
        missing.append('Selected delivery cost is unknown; no usable frozen cost amount is available.')
    rows = []
    for artifact in artifacts[:MAX_EVIDENCE_ROWS]:
        kind = str(artifact.type)
        check_result = 'unavailable'
        if kind in ('gate', 'verification'):
            passed = artifact.payload.get('passed')
            if passed is True:
                check_result = 'passed'
            elif passed is False:
                check_result = 'failed'
        rows.append({
            'id': artifact.id,
            'task_id': artifact.task_id if artifact.task_id in task_ids else None,
            'type': kind,
            'presence': 'recorded',
            'check_result': check_result,
        })
    return {
        'job_ref': JobRef(job_id=job.id, state_id=state_identity(store.root)).as_dict(),
        'source': 'harness',
        'status': str(job.status),
        'links': {'request': None, 'turn': None, 'action': None, 'attempts': 'recorded' if report.attempt_count else 'unavailable'},
        'tasks': [{'id': task.id, 'status': str(task.status), 'attempt_count': task.attempts}
                  for task in tasks[:MAX_EVIDENCE_ROWS]],
        'artifacts': rows,
        'attempts': attempt_rows,
        'attempt_coverage': 'unverified',
        'totals': {'tasks': len(tasks), 'artifacts': len(artifacts), 'attempts': report.attempt_count},
        'truncated': len(tasks) > MAX_EVIDENCE_ROWS or len(artifacts) > MAX_EVIDENCE_ROWS or report.attempt_count > MAX_EVIDENCE_ROWS,
        'cost': {'selected_usd': amount, 'total_attempt_usd': None, 'source': cost_source,
                 'recorded_attempts': _consumption_metrics(report.totals)},
        'missing': missing,
        'provenance': 'Public Puppetmaster store records; selected job only; non-atomic snapshot. Public ledger reads materialize all records; response rows are capped at 100 per kind.',
    }
