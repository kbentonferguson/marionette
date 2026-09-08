import type { ExpertHeader, ExpertTask } from './expertMetadata';

export type ExpertUsageFacts = ExpertTask['usage'] & { tokens?: number | null; source_artifact_id?: string | null; route_forecast_usd?: number | null; plan_billed?: boolean };
export type ExpertEconomicsHeader = Omit<ExpertHeader, 'cost'> & {
  updated_at: string | null;
  latest_task_updated_at: string | null;
  completed_workers: number;
  selected_workers: number;
  workers_complete: boolean;
  usage: { tokens: number | null; tokens_known_workers: number; cost_known_workers: number; selected_workers: number; complete: boolean };
  cost: Omit<ExpertHeader['cost'], 'source' | 'basis'> & {
    source: 'selected_current_records'; basis: 'measured' | 'estimated' | 'mixed' | 'plan' | 'unknown';
    plan_workers: number; complete: boolean;
  };
  savings: { routing_usd: number | null; cache_usd: number | null; compaction_usd: number | null;
    compact_tokens: number | null; selected_usd: number | null; basis: 'estimated'; source: 'selected_current_records' };
};
export function expertDollars(value: number): string {
  return value === 0 ? '$0' : `$${value.toFixed(value < 0.01 ? 4 : 2)}`;
}
export function expertTokens(usage: ExpertUsageFacts): number | null {
  const total = usage.tokens !== undefined ? usage.tokens : usage.tokens_in !== null && usage.tokens_out !== null ? usage.tokens_in + usage.tokens_out : null;
  return total !== null && Number.isFinite(total) ? total : null;
}
export function expertWorkerCost(usage: ExpertUsageFacts, planBilled: boolean): string | null {
  const cost = usage.est_cost_usd;
  if (cost !== null && usage.estimated === false && usage.cost_provenance === 'provider') return `Provider-reported cost ${expertDollars(cost)}`;
  if (usage.cost_provenance === 'plan' || planBilled && (cost === null || cost === 0)) return 'Plan-billed in-subscription';
  if (cost === null) return null;
  return `${usage.estimated === true ? 'Estimated cost ~' : 'Reported cost '}$${cost.toFixed(4)}`;
}
function epoch(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}
/** Missing clocks sort last in both directions; stable ties retain source order. */
export function sortExpertByCreation<T extends { created_at: string | null }>(rows: readonly T[], direction: 'newest' | 'oldest' = 'newest'): T[] {
  return [...rows].sort((a, b) => {
    const left = epoch(a.created_at), right = epoch(b.created_at);
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    return direction === 'newest' ? right - left : left - right;
  });
}
export function expertAge(createdAt: string | null, now: number): string | null {
  const created = epoch(createdAt);
  if (created === null || !Number.isFinite(now) || created > now) return null;
  const seconds = Math.floor((now - created) / 1000);
  return seconds < 60 ? `${seconds}s ago` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
}
