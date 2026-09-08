import type { ExpertMetadata } from '../lib/expertMetadata';
import type { MetadataDetail, MetadataSelection } from '../lib/jobMetadata';
import { detail, selection } from './jobMetadata.fixtures';
export function currentFacts(model = 'gpt-6-astra', reason = 'Tests passed'): ExpertMetadata {
  return { kind: 'available', reason: null, header: { created_at: '2026-09-07T12:00:00Z', completed_at: null,
    cost: { selected_usd: null, source: 'unavailable', basis: 'unknown', measured_cost_usd: null, estimated_cost_usd: null } },
    tasks: [{ id: 'task-1', role: 'Auditor', instruction: 'Exact current instruction', instruction_truncated: false,
      adapter: 'codex', model, created_at: null, updated_at: null,
      usage: { tokens_in: 100, tokens_out: 20, est_cost_usd: 0, estimated: false, cost_provenance: 'provider' } }],
    artifacts: [{ id: 'artifact-1', task_id: 'task-1', type: 'verification', created_by: 'worker', created_at: null,
      headline: 'Regression checks', detail: reason, result: 'passed', failure: null, confidence: 1, model: null,
      adapter: null, policy: null, provider: null, role: null, est_cost_usd: null, rejected: [], check_result: 'passed' }],
    coverage: { tasks: 'complete', artifacts: 'complete' }, quality: 'ok' };
}
export function currentDetail(expert = currentFacts(), s: MetadataSelection = { ...selection(), job_ref: { ...selection().job_ref, version: 2 as const, incarnation: '12345678-1234-4234-8234-123456789abc' } }, revision = 100): MetadataDetail {
  const d = detail();
  return { ...d, selection: s, expert, tasks: { page: { ...d.tasks.page, revision, checkpoint: revision, scanned: expert.tasks.length }, rows: expert.tasks.map(t => ({ ...d.tasks.rows[0], id: t.id, binding: { task_id: t.id, generation: 3, lease_id: 'lease', owner: 'worker' } })) },
    artifacts: { page: { ...d.artifacts.page, revision, checkpoint: revision, scanned: expert.artifacts.length }, rows: expert.artifacts.map(a => ({ ...d.artifacts.rows[0], id: a.id, task_id: a.task_id, type: a.type })) } };
}
