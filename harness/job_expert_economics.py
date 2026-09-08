"""Economics for an already fenced, finite selected expert view; no store reads."""
from __future__ import annotations

from datetime import datetime

from puppetmaster.cost import final_routing_artifacts, price_job
from puppetmaster.usage import select_usage_records, usage_record_score

from .job_expert import current_artifact, number, timestamp
from .api.cost_accounting import _cache_savings_gross
from .api.routing_savings import _registry_rates, _routing_saved_usd_detail, _delegation_saved_usd_detail
from .tool_output_savings import savings_usd, tokens_avoided


def _sum(values):
    known = [v for v in values if v is not None]
    return number(sum(known)) if known else None


def _usage(task, artifact, priced):
    record = select_usage_records([artifact]).get(task.id, {}) if artifact else {}
    payload = artifact.payload if artifact else {}
    # Versioned facts preserve missing splits; legacy explicit fields also attest presence.
    facts = record.get('selected_facts', {}) if 'selected_facts' in payload else payload
    tin, tout = number(facts.get('tokens_in')), number(facts.get('tokens_out'))
    real = number(record.get('selected_facts', {}).get('real_cost_usd'))
    cost, basis = real, 'provider' if real is not None else 'unknown'
    if real is None and priced and priced.priced and tin is not None and tout is not None:
        cost = number(priced.marginal_cost_usd)
        basis = 'plan' if priced.billing == 'plan' else 'catalog'
    return dict(tokens_in=tin, tokens_out=tout,
                tokens=number(tin + tout) if tin is not None and tout is not None else None,
                est_cost_usd=cost, estimated=False if basis == 'provider' else True if cost is not None else None,
                cost_provenance=basis, source_artifact_id=artifact.id if artifact else None)


def project_economics(job, tasks, artifacts, coverage, *, registry=(), compaction_records=None,
                      compaction_price_in=None):
    """Return {header, tasks} extensions; caller owns incarnation/revision fencing.

    Inputs must be materialized selected pages (at most 50 rows each). Optional
    compaction_records are exact-job/session ledger rows, already selected by
    the caller under the same ownership fence, never a history or ledger path.
    """
    if len(tasks) > 50 or len(artifacts) > 50 or (compaction_records is not None and len(compaction_records) > 50):
        raise ValueError('selected economics row budget exceeded')
    if len({t.id for t in tasks}) != len(tasks) or any(t.job_id != job.id for t in tasks):
        raise ValueError('selected economics task ownership mismatch')
    task_map = {t.id: t for t in tasks}
    current = [a for a in artifacts if a.job_id == job.id and a.task_id in task_map
               and current_artifact(a, task_map[a.task_id])]
    winners = {}
    for artifact in current:
        p = artifact.payload
        if 'tokens_in' not in p and 'tokens_out' not in p:
            continue
        if any(k in p and number(p[k]) is None for k in ('tokens_in', 'tokens_out', 'tokens_cached', 'cache_read_tokens', 'cache_write_tokens', 'real_cost_usd')):
            continue
        previous = winners.get(artifact.task_id)
        if previous is None or usage_record_score(p) > usage_record_score(previous.payload):
            winners[artifact.task_id] = artifact
    routes = final_routing_artifacts(current)
    selected = list({a.id: a for a in [*routes.values(), *winners.values()]}.values())
    priced = {t.task_id: t for t in price_job(selected, list(registry)).tasks}
    usages = {t.id: _usage(t, winners.get(t.id), priced.get(t.id)) for t in tasks}
    for task_id, usage in usages.items():
        route = routes.get(task_id)
        payload = route.payload if route else {}
        usage['route_forecast_usd'] = number(payload.get('estimated_cost_usd'))
        usage['plan_billed'] = payload.get('billing') == 'plan' or usage['cost_provenance'] == 'plan'
    values = list(usages.values())
    complete = coverage.get('tasks') == 'complete' and coverage.get('artifacts') == 'complete'
    cost_count = sum(u['est_cost_usd'] is not None for u in values)
    measured = _sum([u['est_cost_usd'] for u in values if u['cost_provenance'] == 'provider'])
    estimated = _sum([u['est_cost_usd'] for u in values if u['cost_provenance'] == 'catalog'])
    plan = sum(u['cost_provenance'] == 'plan' for u in values)
    cost = _sum([u['est_cost_usd'] for u in values])
    basis = 'mixed' if measured is not None and (estimated is not None or plan) else 'measured' if measured is not None else 'estimated' if estimated is not None else 'plan' if plan else 'unknown'
    routing, cache = [], []
    for task in tasks:
        route, winner = routes.get(task.id), winners.get(task.id)
        local = list({a.id: a for a in (route, winner) if a is not None}.values())
        if route is not None and any(key in route.payload and number(route.payload[key]) is None
                                     for key in ('baseline_cost_usd', 'estimated_cost_usd', 'nominal_cost_usd')):
            local = []
        if winner is not None and usages[task.id]['tokens'] is None:
            # Partial token splits cannot support a counterfactual dollar total.
            local = []
        detail = _delegation_saved_usd_detail(local, list(registry))
        if detail['delegation_savings_counted'] and detail['delegation_savings_basis'] == 'actual_usage':
            routing.append(number(detail['delegation_saved_usd']))
        else:
            detail = _routing_saved_usd_detail(local, list(registry))
            routing.append(number(detail['routing_saved_usd']) if detail['routing_savings_counted'] and detail['routing_savings_basis'] != 'unknown' else None)
        p = winner.payload if winner else {}
        cache_facts = p.get('selected_facts') if isinstance(p.get('selected_facts'), dict) else p
        cached = number(cache_facts.get('cache_read_tokens', cache_facts.get('tokens_cached')))
        task_cost = priced.get(task.id)
        model = task_cost.model_id if task_cost else str(p.get('model') or '')
        pin, _ = _registry_rates(model, list(registry))
        cache.append(_cache_savings_gross(cached, pin) if cached is not None and pin > 0 else None)
    compact = None
    if compaction_records is not None:
        seen, counts = set(), []
        for row in compaction_records:
            key = (row.get('session_id'), row.get('tool_call_id'))
            if (row.get('job_id') != job.id or not job.session_id or key[0] != job.session_id
                    or not key[1] or key in seen):
                continue
            original, shortened = number(row.get('original_chars')), number(row.get('compact_chars'))
            if original is None or shortened is None:
                continue
            seen.add(key)
            counts.append(tokens_avoided(original, shortened))
        compact = sum(counts) if counts else (0 if not compaction_records else None)
    compact_usd = savings_usd(compact, compaction_price_in) if compact is not None and number(compaction_price_in) is not None else None
    savings = dict(routing_usd=_sum(routing), cache_usd=_sum(cache), compaction_usd=compact_usd,
                   compact_tokens=compact, basis='estimated', source='selected_current_records')
    savings['selected_usd'] = _sum([savings['routing_usd'], savings['cache_usd'], compact_usd])
    header = dict(created_at=timestamp(job.created_at), completed_at=timestamp(job.completed_at),
        updated_at=timestamp(getattr(job, 'updated_at', None)),
        latest_task_updated_at=max((timestamp(t.updated_at) for t in tasks if timestamp(t.updated_at)), key=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')), default=None),
        completed_workers=sum(str(t.status) in ('complete', 'completed') for t in tasks), selected_workers=len(tasks),
        workers_complete=coverage.get('tasks') == 'complete',
        usage=dict(tokens=_sum([u['tokens'] for u in values]), tokens_known_workers=sum(u['tokens'] is not None for u in values),
                   cost_known_workers=cost_count, selected_workers=len(tasks),
                   complete=complete and bool(tasks) and all(u['tokens'] is not None for u in values)),
        cost=dict(selected_usd=cost, measured_cost_usd=measured, estimated_cost_usd=estimated,
                  source='selected_current_records', basis=basis, plan_workers=plan,
                  complete=complete and bool(tasks) and cost_count == len(tasks)), savings=savings)
    return dict(header=header, tasks=usages)
