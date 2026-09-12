/** Current, bounded producer facts. Historical receipts never enter this projection. */
export type ExpertHeader = { model?: string | null; model_provenance?: 'job_routing' | 'task_assignment' | 'uniform_task_assignments' | 'unknown'; created_at: string | null; completed_at: string | null; updated_at?: string | null; latest_task_updated_at?: string | null; completed_workers?: number; selected_workers?: number; workers_complete?: boolean;
  usage?: { tokens: number | null; tokens_known_workers: number; cost_known_workers: number; selected_workers: number; complete: boolean };
  savings?: { routing_usd: number | null; cache_usd: number | null; compaction_usd: number | null; compact_tokens: number | null; selected_usd: number | null; basis: 'estimated'; source: 'selected_current_records' };
  quality?: 'ok' | 'degraded' | 'unverified'; cost: {
  selected_usd: number | null; source: 'terminal_cost_receipt' | 'selected_current_records' | 'unavailable'; basis: 'measured' | 'estimated' | 'mixed' | 'plan' | 'unknown'; complete?: boolean; plan_workers?: number;
  measured_cost_usd: number | null; estimated_cost_usd: number | null;
} };
export type ExpertTask = { id: string; role: string; instruction: string; instruction_truncated: boolean; adapter: string; model: string | null;
  created_at: string | null; updated_at: string | null; usage: { tokens_in: number | null; tokens_out: number | null; est_cost_usd: number | null;
    estimated: boolean | null; cost_provenance: string | null; tokens?: number | null; source_artifact_id?: string | null; route_forecast_usd?: number | null; plan_billed?: boolean } };
export type ExpertArtifact = { id: string; task_id: string | null; type: string; created_by: string; created_at: string | null;
  headline: string; detail: string | null; result: string | null; failure: string | null; confidence: number | null;
  model: string | null; adapter: string | null; policy: string | null; provider: string | null; role: string | null; est_cost_usd: number | null;
  rejected: { model: string; reason: string }[]; check_result: 'passed' | 'failed' | 'unavailable' };
export type ExpertMetadata = { kind: 'available' | 'partial' | 'unavailable'; reason: string | null; header: ExpertHeader | null; live_economics?: ExpertHeader | null; compaction?: { coverage: 'complete' | 'partial' | 'unavailable'; reason: string };
  tasks: ExpertTask[]; artifacts: ExpertArtifact[]; coverage: { tasks: 'complete' | 'partial' | 'unknown'; artifacts: 'complete' | 'partial' | 'unknown' };
  quality: 'ok' | 'degraded' | 'unverified' };
function invalid(detail?: string): never {
  const error = new Error(detail ? `invalid_metadata:${detail}` : 'invalid_metadata');
  if (detail) (error as Error & { detail?: string }).detail = detail;
  throw error;
}
function object(value: unknown, keys?: string[], optional: string[] = [], path = 'object'): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid(path);
  const result = Object.fromEntries(Object.entries(value));
  if (keys && (keys.some(key => !Object.hasOwn(result, key)) || Object.keys(result).some(key => !keys.includes(key) && !optional.includes(key)))) return invalid(path);
  return result;
}
function string(value: unknown, path = 'string'): string { if (typeof value !== 'string' || new TextEncoder().encode(value).length > 16384) return invalid(path); return value; }
function nullableString(value: unknown, path = 'string'): string | null { return value === null ? null : string(value, path); }
function number(value: unknown, path = 'number'): number | null { if (value === null) return null; if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return invalid(path); return value; }
function boolean(value: unknown, path = 'boolean'): boolean { if (typeof value !== 'boolean') return invalid(path); return value; }
function choice<T extends string>(value: unknown, choices: readonly T[], path = 'choice'): T { for (const item of choices) if (value === item) return item; return invalid(path); }
function rows<T>(value: unknown, parse: (value: unknown) => T, max = 50, path = 'rows'): T[] { if (!Array.isArray(value) || value.length > max) return invalid(path); return value.map(parse); }
function count(value: unknown, path = 'count'): number { const n = number(value, path); if (n === null || !Number.isSafeInteger(n)) return invalid(path); return n; }
function nullableCount(value: unknown, path = 'count'): number | null { return value === null ? null : count(value, path); }
function timestamp(value: unknown, path = 'timestamp'): string | null {
  const s = nullableString(value, path);
  if (s !== null && (s.length > 64 || !/(Z|[+-]\d{2}:\d{2})$/.test(s) || !Number.isFinite(Date.parse(s)))) return null;
  return s;
}
export function parseExpertHeader(value: unknown): ExpertHeader | null {
  if (value === null) return null;
  const v = object(value, ['created_at', 'completed_at', 'cost'], ['updated_at', 'latest_task_updated_at', 'completed_workers', 'selected_workers', 'workers_complete', 'usage', 'savings', 'quality', 'model', 'model_provenance'], 'header');
  const c = object(v.cost, ['selected_usd', 'source', 'basis', 'measured_cost_usd', 'estimated_cost_usd'], ['plan_workers', 'complete'], 'header.cost');
  const header: ExpertHeader = { created_at: timestamp(v.created_at, 'header.created_at'), completed_at: timestamp(v.completed_at, 'header.completed_at'), cost: {
    selected_usd: number(c.selected_usd, 'header.cost.selected_usd'), source: choice(c.source, ['terminal_cost_receipt', 'selected_current_records', 'unavailable'], 'header.cost.source'),
    basis: choice(c.basis, ['measured', 'estimated', 'mixed', 'plan', 'unknown'], 'header.cost.basis'), measured_cost_usd: number(c.measured_cost_usd, 'header.cost.measured_cost_usd'), estimated_cost_usd: number(c.estimated_cost_usd, 'header.cost.estimated_cost_usd'),
  } };
  if (header.cost.source === 'unavailable' && (header.cost.selected_usd !== null || header.cost.measured_cost_usd !== null || header.cost.estimated_cost_usd !== null)) return invalid('header.cost.source');
  if (v.model !== undefined || v.model_provenance !== undefined) {
    let model = nullableString(v.model, 'header.model');
    let provenance = choice(v.model_provenance, ['job_routing', 'task_assignment', 'uniform_task_assignments', 'unknown'] as const, 'header.model_provenance');
    if (model !== null && (!model.trim() || model.length > 256 || /[\u0000-\u001f]/.test(model))) { model = null; provenance = 'unknown'; }
    if ((model === null) !== (provenance === 'unknown')) { model = null; provenance = 'unknown'; }
    header.model = model;
    header.model_provenance = provenance;
  }
  if (v.quality !== undefined) header.quality = choice(v.quality, ['ok', 'degraded', 'unverified'] as const, 'header.quality');
  if (v.updated_at !== undefined) header.updated_at = timestamp(v.updated_at, 'header.updated_at');
  if (v.latest_task_updated_at !== undefined) header.latest_task_updated_at = timestamp(v.latest_task_updated_at, 'header.latest_task_updated_at');
  if (v.usage !== undefined) {
    const u = object(v.usage, ['tokens', 'tokens_known_workers', 'cost_known_workers', 'selected_workers', 'complete'], [], 'header.usage');
    header.completed_workers = count(v.completed_workers, 'header.completed_workers'); header.selected_workers = count(v.selected_workers, 'header.selected_workers'); header.workers_complete = boolean(v.workers_complete, 'header.workers_complete');
    header.usage = { tokens: nullableCount(u.tokens, 'header.usage.tokens'), tokens_known_workers: count(u.tokens_known_workers, 'header.usage.tokens_known_workers'), cost_known_workers: count(u.cost_known_workers, 'header.usage.cost_known_workers'), selected_workers: count(u.selected_workers, 'header.usage.selected_workers'), complete: boolean(u.complete, 'header.usage.complete') };
    header.cost.complete = boolean(c.complete, 'header.cost.complete'); header.cost.plan_workers = count(c.plan_workers, 'header.cost.plan_workers');
    const a = object(v.savings, ['routing_usd', 'cache_usd', 'compaction_usd', 'compact_tokens', 'selected_usd', 'basis', 'source'], [], 'header.savings');
    header.savings = { routing_usd: number(a.routing_usd, 'header.savings.routing_usd'), cache_usd: number(a.cache_usd, 'header.savings.cache_usd'), compaction_usd: number(a.compaction_usd, 'header.savings.compaction_usd'), compact_tokens: nullableCount(a.compact_tokens, 'header.savings.compact_tokens'), selected_usd: number(a.selected_usd, 'header.savings.selected_usd'), basis: choice(a.basis, ['estimated'], 'header.savings.basis'), source: choice(a.source, ['selected_current_records'], 'header.savings.source') };
    if (header.completed_workers > header.selected_workers || header.usage.selected_workers !== header.selected_workers || header.usage.tokens_known_workers > header.selected_workers || header.usage.cost_known_workers > header.selected_workers || header.cost.plan_workers > header.selected_workers || header.cost.source !== 'selected_current_records') return invalid('header.usage');
  } else if (['completed_workers', 'selected_workers', 'workers_complete', 'savings'].some(key => v[key] !== undefined) || c.source === 'selected_current_records' || c.complete !== undefined || c.plan_workers !== undefined) return invalid('header.usage');
  return header;
}
export function parseExpertMetadata(value: unknown, references?: readonly Pick<ExpertArtifact, 'id' | 'task_id'>[]): ExpertMetadata {
  const v = object(value, ['kind', 'reason', 'header', 'tasks', 'artifacts', 'coverage', 'quality'], ['live_economics', 'economics', 'compaction'], 'expert'), coverage = object(v.coverage, ['tasks', 'artifacts'], [], 'expert.coverage');
  const parsed: ExpertMetadata = {
    kind: choice(v.kind, ['available', 'partial', 'unavailable'], 'expert.kind'), reason: nullableString(v.reason, 'expert.reason'), header: parseExpertHeader(v.header), ...(v.live_economics === undefined ? {} : { live_economics: parseExpertHeader(v.live_economics) }),
    tasks: rows(v.tasks, value => { const t = object(value, ['id', 'role', 'instruction', 'instruction_truncated', 'adapter', 'model', 'created_at', 'updated_at', 'usage'], [], 'expert.task'), u = object(t.usage, ['tokens_in', 'tokens_out', 'est_cost_usd', 'estimated', 'cost_provenance'], ['tokens', 'source_artifact_id', 'route_forecast_usd', 'plan_billed'], 'expert.task.usage');
      let model = nullableString(t.model, 'expert.task.model');
      if (model !== null && !model.trim()) model = null;
      return {
      id: string(t.id, 'expert.task.id'), role: string(t.role, 'expert.task.role'), instruction: string(t.instruction, 'expert.task.instruction'), instruction_truncated: boolean(t.instruction_truncated, 'expert.task.instruction_truncated'),
      adapter: string(t.adapter, 'expert.task.adapter'), model, created_at: timestamp(t.created_at, 'expert.task.created_at'), updated_at: timestamp(t.updated_at, 'expert.task.updated_at'),
      usage: { tokens_in: nullableCount(u.tokens_in, 'expert.task.usage.tokens_in'), tokens_out: nullableCount(u.tokens_out, 'expert.task.usage.tokens_out'), est_cost_usd: number(u.est_cost_usd, 'expert.task.usage.est_cost_usd'), estimated: u.estimated === null ? null : boolean(u.estimated, 'expert.task.usage.estimated'), cost_provenance: nullableString(u.cost_provenance, 'expert.task.usage.cost_provenance'), ...(u.route_forecast_usd === undefined ? {} : { route_forecast_usd: number(u.route_forecast_usd, 'expert.task.usage.route_forecast_usd') }), ...(u.plan_billed === undefined ? {} : { plan_billed: boolean(u.plan_billed, 'expert.task.usage.plan_billed') }), ...(u.tokens === undefined ? {} : { tokens: nullableCount(u.tokens, 'expert.task.usage.tokens') }), ...(u.source_artifact_id === undefined ? {} : { source_artifact_id: nullableString(u.source_artifact_id, 'expert.task.usage.source_artifact_id') }) },
    }; }, 50, 'expert.tasks'),
    artifacts: rows(v.artifacts, value => { const a = object(value, ['id', 'task_id', 'type', 'created_by', 'created_at', 'headline', 'detail', 'result', 'failure', 'confidence', 'model', 'adapter', 'policy', 'provider', 'role', 'est_cost_usd', 'rejected', 'check_result'], [], 'expert.artifact');
      const confidence = number(a.confidence, 'expert.artifact.confidence');
      const check = a.check_result === 'passed' || a.check_result === 'failed' || a.check_result === 'unavailable'
        ? a.check_result : 'unavailable';
      return {
      id: string(a.id, 'expert.artifact.id'), task_id: nullableString(a.task_id, 'expert.artifact.task_id'), type: string(a.type, 'expert.artifact.type'), created_by: string(a.created_by, 'expert.artifact.created_by'), created_at: timestamp(a.created_at, 'expert.artifact.created_at'),
      headline: string(a.headline, 'expert.artifact.headline'), detail: nullableString(a.detail, 'expert.artifact.detail'), result: nullableString(a.result, 'expert.artifact.result'), failure: nullableString(a.failure, 'expert.artifact.failure'),
      confidence: confidence !== null && confidence > 1 ? null : confidence,
      model: nullableString(a.model, 'expert.artifact.model'), adapter: nullableString(a.adapter, 'expert.artifact.adapter'), policy: nullableString(a.policy, 'expert.artifact.policy'), provider: nullableString(a.provider, 'expert.artifact.provider'), role: nullableString(a.role, 'expert.artifact.role'), est_cost_usd: number(a.est_cost_usd, 'expert.artifact.est_cost_usd'),
      rejected: rows(a.rejected, value => { const r = object(value, ['model', 'reason'], [], 'expert.artifact.rejected'); return { model: string(r.model, 'expert.artifact.rejected.model'), reason: string(r.reason, 'expert.artifact.rejected.reason') }; }, 32, 'expert.artifact.rejected'),
      check_result: check,
    }; }, 50, 'expert.artifacts'),
    coverage: { tasks: choice(coverage.tasks, ['complete', 'partial', 'unknown'], 'expert.coverage.tasks'), artifacts: choice(coverage.artifacts, ['complete', 'partial', 'unknown'], 'expert.coverage.artifacts') },
    quality: choice(v.quality, ['ok', 'degraded', 'unverified'], 'expert.quality'),
  };
  if (v.economics !== undefined) {
    if (v.live_economics !== undefined) return invalid('expert.economics');
    const economics = object(v.economics, ['header', 'tasks'], ['compaction'], 'expert.economics');
    if (economics.compaction !== undefined) { const c = object(economics.compaction, ['coverage', 'reason'], [], 'expert.economics.compaction'); parsed.compaction = { coverage: choice(c.coverage, ['complete', 'partial', 'unavailable'], 'expert.economics.compaction.coverage'), reason: string(c.reason, 'expert.economics.compaction.reason') }; }
    parsed.live_economics = parseExpertHeader(economics.header);
    if (!parsed.live_economics?.usage) return invalid('expert.economics.header.usage');
    const usages = object(economics.tasks, undefined, undefined, 'expert.economics.tasks');
    if (Object.keys(usages).length > 50 || Object.keys(usages).some(id => !parsed.tasks.some(t => t.id === id))) return invalid('expert.economics.tasks');
    parsed.tasks = parsed.tasks.map(task => {
      if (!Object.hasOwn(usages, task.id)) return task;
      const u = object(usages[task.id], ['tokens_in', 'tokens_out', 'tokens', 'est_cost_usd', 'estimated', 'cost_provenance', 'source_artifact_id', 'route_forecast_usd', 'plan_billed'], [], 'expert.economics.task');
      let source = nullableString(u.source_artifact_id, 'expert.economics.task.source_artifact_id');
      if (source !== null && !(references ?? parsed.artifacts).some(a => a.id === source && a.task_id === task.id)) source = null;
      return { ...task, usage: { tokens_in: nullableCount(u.tokens_in, 'expert.economics.task.tokens_in'), tokens_out: nullableCount(u.tokens_out, 'expert.economics.task.tokens_out'), tokens: nullableCount(u.tokens, 'expert.economics.task.tokens'), est_cost_usd: number(u.est_cost_usd, 'expert.economics.task.est_cost_usd'), estimated: u.estimated === null ? null : boolean(u.estimated, 'expert.economics.task.estimated'), cost_provenance: nullableString(u.cost_provenance, 'expert.economics.task.cost_provenance'), source_artifact_id: source, route_forecast_usd: number(u.route_forecast_usd, 'expert.economics.task.route_forecast_usd'), plan_billed: boolean(u.plan_billed, 'expert.economics.task.plan_billed') } };
    });
  }
  if (v.compaction !== undefined) { if (v.economics !== undefined) return invalid('expert.compaction'); const c = object(v.compaction, ['coverage', 'reason'], [], 'expert.compaction'); parsed.compaction = { coverage: choice(c.coverage, ['complete', 'partial', 'unavailable'], 'expert.compaction.coverage'), reason: string(c.reason, 'expert.compaction.reason') }; }
  if (parsed.compaction && parsed.compaction.coverage !== 'complete' && parsed.live_economics?.savings?.compact_tokens !== null && parsed.live_economics?.savings?.compact_tokens !== undefined) {
    parsed.live_economics = { ...parsed.live_economics, savings: { ...parsed.live_economics.savings!, compact_tokens: null } };
  }
  if (new Set(parsed.tasks.map(t => t.id)).size !== parsed.tasks.length || new Set(parsed.artifacts.map(a => a.id)).size !== parsed.artifacts.length) return invalid('expert.duplicate_id');
  if (parsed.quality === 'ok' && (parsed.coverage.tasks !== 'complete' || parsed.coverage.artifacts !== 'complete')) parsed.quality = 'unverified';
  if (parsed.kind === 'unavailable' && (parsed.tasks.length || parsed.artifacts.length || parsed.quality !== 'unverified')) {
    parsed.tasks = [];
    parsed.artifacts = [];
    parsed.quality = 'unverified';
  }
  return parsed;
}
