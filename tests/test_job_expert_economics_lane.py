from dataclasses import replace

import pytest
from puppetmaster.models import Artifact, ArtifactType, Job, Task, TaskStatus
from puppetmaster.model_registry import ModelSpec

from harness.job_expert_economics import project_economics

CLOCK = '2026-09-07T12:00:00+00:00'
COVERAGE = dict(tasks='complete', artifacts='complete')


def setup_records():
    job = Job(id='job', goal='economics', created_at=CLOCK, session_id='session')
    task = Task(id='task', job_id=job.id, role='worker', instruction='', created_at=CLOCK, updated_at=CLOCK)
    return job, task


def usage(task, **payload):
    return Artifact(job_id=task.job_id, task_id=task.id, type=ArtifactType.VERIFICATION,
                    created_by='worker', payload=payload, confidence=1, evidence=[], created_at=CLOCK)


def project(job, tasks, arts, **kwargs):
    return project_economics(job, tasks, arts, COVERAGE, **kwargs)


def test_live_cumulative_observations_are_selected_not_summed():
    job, task = setup_records()
    old = usage(task, tokens_in=100, tokens_out=10, real_cost_usd=.1)
    new = usage(task, tokens_in=200, tokens_out=20, real_cost_usd=.2)
    result = project(job, [task], [old, new])
    assert result['header']['usage']['tokens'] == 220
    assert result['header']['cost']['selected_usd'] == .2
    assert result['tasks']['task']['source_artifact_id'] == new.id


def test_missing_partial_and_genuine_zero_do_not_collapse():
    job, task = setup_records()
    empty = project(job, [task], [])
    assert empty['header']['cost']['selected_usd'] is None
    assert empty['header']['usage']['tokens'] is None
    zero = project(job, [task], [usage(task, tokens_in=0, real_cost_usd=0)])
    assert zero['header']['cost']['selected_usd'] == 0
    assert zero['header']['usage']['tokens'] is None  # missing output is not zero
    assert zero['tasks']['task']['cost_provenance'] == 'provider'
    second = replace(task, id='second')
    partial = project(job, [task, second], [usage(task, tokens_in=0, tokens_out=0, real_cost_usd=0)])
    assert partial['header']['cost']['complete'] is False
    assert partial['header']['usage']['cost_known_workers'] == 1


def test_current_epoch_and_ownership_are_required():
    job, task = setup_records()
    reset = replace(task, generation=2, attempts=2)
    stale = usage(reset, tokens_in=100, tokens_out=10, real_cost_usd=10, generation=1)
    foreign = replace(usage(reset, tokens_in=100, tokens_out=10, real_cost_usd=10, generation=2), job_id='other')
    assert project(job, [reset], [stale, foreign])['header']['cost']['selected_usd'] is None
    with pytest.raises(ValueError):
        project(job, [replace(task, job_id='other')], [])


def test_provider_zero_overrides_plan_and_catalog_is_estimated():
    job, task = setup_records()
    registry = [ModelSpec(id='api', adapter='agentic', adapter_model_name='api', billing='api', input_per_mtok_usd=1, output_per_mtok_usd=2),
                ModelSpec(id='plan', adapter='codex', adapter_model_name='plan', billing='plan')]
    second = replace(task, id='second', status=TaskStatus.COMPLETE)
    result = project(job, [task, second], [usage(task, model='plan', tokens_in=100, tokens_out=20, real_cost_usd=0),
        usage(second, model='api', tokens_in=1000000, tokens_out=0, tokens_estimated=False)], registry=registry)
    assert result['header']['cost']['basis'] == 'mixed'
    assert result['header']['cost']['measured_cost_usd'] == 0
    assert result['header']['cost']['estimated_cost_usd'] == 1
    assert result['header']['completed_workers'] == 1
    plan = project(job, [task], [usage(task, model='plan', tokens_in=100, tokens_out=0)], registry=registry)
    assert plan['header']['cost']['basis'] == 'plan'
    assert plan['header']['cost']['measured_cost_usd'] is None


def test_compaction_is_exact_and_deduplicated_and_cache_uses_selected_observation():
    job, task = setup_records()
    record = dict(job_id=job.id, session_id=job.session_id, tool_call_id='call', original_chars=800, compact_chars=400)
    registry = [ModelSpec(id='api', adapter='agentic', adapter_model_name='api', billing='api', input_per_mtok_usd=1)]
    result = project(job, [task], [usage(task, model='api', tokens_in=100, tokens_out=0, tokens_cached=50),
        usage(task, model='api', tokens_in=200, tokens_out=0, tokens_cached=100)], registry=registry,
        compaction_records=[record, record, dict(record, job_id='other', tool_call_id='foreign')], compaction_price_in=2)
    assert result['header']['savings']['compact_tokens'] == 100
    assert result['header']['savings']['compaction_usd'] == .0002
    assert result['header']['savings']['cache_usd'] == pytest.approx(.00009)
    assert project(job, [task], [])['header']['savings']['compact_tokens'] is None


def test_budgets_and_invalid_numbers():
    job, task = setup_records()
    with pytest.raises(ValueError):
        project(job, [replace(task, id=str(i)) for i in range(51)], [])
    assert project(job, [task], [usage(task, tokens_in=float('inf'), real_cost_usd=1)])['header']['cost']['selected_usd'] is None


def test_route_forecast_and_plan_billing_do_not_become_spend():
    job, task = setup_records()
    route = Artifact(job_id=job.id, task_id=task.id, type=ArtifactType.ROUTING,
        created_by='router', payload=dict(model_id='plan', billing='plan', estimated_cost_usd=0),
        confidence=1, evidence=[], created_at=CLOCK)
    result = project(job, [task], [route])
    assert result['tasks']['task']['plan_billed'] is True
    assert result['tasks']['task']['route_forecast_usd'] == 0
    assert result['header']['cost']['selected_usd'] is None


def test_header_clock_is_attested_and_task_clock_is_separate():
    job, task = setup_records()
    second = replace(task, id='second', updated_at='2026-09-07T08:00:00-05:00')
    result = project(job, [task, second], [])['header']
    assert result['created_at'] == CLOCK
    assert result['updated_at'] is None
    assert result['latest_task_updated_at'] == second.updated_at


def test_source_attested_routing_cache_compaction_values_are_additive():
    job, task = setup_records()
    route = Artifact(job_id=job.id, task_id=task.id, type=ArtifactType.ROUTING,
        created_by='router', payload=dict(model_id='api', policy='cheap', baseline_cost_usd=.06, estimated_cost_usd=.02),
        confidence=1, evidence=[], created_at=CLOCK)
    result = project(job, [task], [route])['header']
    assert result['savings']['routing_usd'] == pytest.approx(.04)
    assert result['savings']['selected_usd'] == pytest.approx(.04)
    assert result['savings']['cache_usd'] is None


def test_actual_selection_savings_zero_is_not_replaced_by_forecast():
    job, task = setup_records()
    registry = [ModelSpec(id='api', adapter='agentic', adapter_model_name='api', billing='api', input_per_mtok_usd=1, output_per_mtok_usd=2)]
    route = Artifact(job_id=job.id, task_id=task.id, type=ArtifactType.ROUTING,
        created_by='router', payload=dict(model_id='api', baseline_model_id='api', policy='cheap', baseline_cost_usd=5, estimated_cost_usd=1),
        confidence=1, evidence=[], created_at=CLOCK)
    result = project(job, [task], [route, usage(task, model='api', tokens_in=100, tokens_out=10)], registry=registry)
    assert result['header']['savings']['routing_usd'] == 0
    assert result['header']['savings']['selected_usd'] == 0
    partial = project(job, [task], [route, usage(task, model='api', tokens_in=100)], registry=registry)
    assert partial['header']['savings']['routing_usd'] is None


def test_versioned_missing_facts_override_legacy_normalized_zero():
    job, task = setup_records()
    registry = [ModelSpec(id='api', adapter='agentic', adapter_model_name='api', billing='api', input_per_mtok_usd=1)]
    artifact = usage(task, model='api', tokens_in=0, tokens_out=0, tokens_cached=0, tokens_estimated=False,
                     selected_facts=dict(version=1, tokens_in=None, tokens_out=None, cache_read_tokens=None))
    result = project(job, [task], [artifact], registry=registry)
    assert result['tasks']['task']['tokens'] is None
    assert result['tasks']['task']['est_cost_usd'] is None
    assert result['header']['savings']['cache_usd'] is None


def test_versioned_facts_preserve_zero_missing_splits_and_unknown_cache():
    from puppetmaster.usage import token_usage
    job, task = setup_records()
    payload = token_usage(sdk_usage={'inputTokens': 120, 'outputTokens': 0})
    payload.update(real_cost_usd=0, model='api', tokens_cached=0)
    registry = [ModelSpec(id='api', adapter='agentic', adapter_model_name='api', billing='api', input_per_mtok_usd=1)]
    result = project(job, [task], [usage(task, **payload)], registry=registry)
    assert result['tasks']['task']['tokens'] == 120
    assert result['header']['cost']['selected_usd'] == 0
    assert result['header']['savings']['cache_usd'] is None
    payload['selected_facts']['version'] = 99
    result = project(job, [task], [usage(task, **payload)], registry=registry)
    assert result['tasks']['task']['tokens'] is None
    assert result['header']['usage']['complete'] is False
    assert result['header']['cost']['selected_usd'] == 0  # Explicit provider amount is independent.
