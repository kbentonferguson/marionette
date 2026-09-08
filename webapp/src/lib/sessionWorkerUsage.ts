import type { ExpertHeader } from './expertMetadata';
import { metadataSelectionKey, metadataStreams, metadataStreamKey } from './jobMetadata';
import type { JobMetadataState } from './useJobMetadata';

export type SessionWorkerUsage =
  | { kind: 'partial'; reason: string }
  | { kind: 'complete'; jobs: number; workers: number; tokens: number | null; cost: number | null;
      measured: number | null; estimated: number | null; routing: number | null; cache: number | null; compaction: number | null };

/** Totals attest only to the current session's known PM stores, never account spend. */
export function sessionWorkerUsage(state: JobMetadataState, now = Date.now()): SessionWorkerUsage {
  const partial = (reason: string): SessionWorkerUsage => ({ kind: 'partial', reason });
  const view = state.view;
  if (view.kind !== 'view' || view.refresh !== 'idle' || view.view.refreshing || state.error)
    return partial('Current source context unavailable');
  if (view.view.availability !== 'known' || view.view.missing.length || view.view.sources.some(s => !s.available))
    return partial('Source enumeration incomplete');
  // Sibling stores expose active lanes only, so they cannot attest terminal session membership.
  if (view.view.sources.some(s => s.cross_project)) return partial('Sibling stores expose active jobs only');
  if (state.displayLimited) return partial('Membership exceeds the retained display window');
  const required = metadataStreams(view.view, view.context.scope);
  if (required.some(requiredStream => !state.streams.some(s => metadataStreamKey(s.stream) === metadataStreamKey(requiredStream)
    && s.state === 'complete' && s.missing.every(reason => ['legacy_ownership', 'display', 'economics'].includes(reason))))) return partial('Session membership is still being read');
  const headers: ExpertHeader[] = [];
  const jobs = new Map(state.observations.map(o => [metadataSelectionKey(o.row.selection), o]));
  for (const [key, observation] of jobs) {
    const row = observation.row;
    if (row.ownership.session_id !== view.context.session_id) continue;
    const cached = state.headers[key];
    if (observation.freshness !== 'observed' || row.selection.session_id !== view.context.session_id || row.selection.repo !== view.context.repo
      || !view.view.sources.some(s => s.source === row.selection.source && s.state_id === row.selection.job_ref.state_id)
      || !cached || cached.observation.freshness !== 'observed' || cached.observation.row.revision !== row.revision
      || metadataSelectionKey(cached.observation.row.selection) !== key || now - cached.refreshedAt >= 60000 || now < cached.refreshedAt)
      return partial('Current job headers are pending or stale');
    const header = cached.observation.row.header;
    if (!header?.workers_complete || !header.usage?.complete || header.cost.source !== 'selected_current_records')
      return partial('Current worker coverage incomplete');
    headers.push(header);
  }
  const sum = (read: (h: ExpertHeader) => number | null | undefined): number | null => {
    let total = 0;
    for (const header of headers) {
      const value = read(header);
      if (value == null) return null;
      total += value;
      if (!Number.isFinite(total) || total > Number.MAX_SAFE_INTEGER) return null;
    }
    return total;
  };
  const workers = sum(h => h.selected_workers);
  if (workers === null) return partial('Worker count unavailable');
  const costCovered = headers.every(h => h.cost.complete && h.usage?.cost_known_workers === h.selected_workers);
  return { kind: 'complete', jobs: headers.length, workers,
    tokens: sum(h => h.usage?.tokens_known_workers === h.selected_workers ? h.usage?.tokens : null),
    cost: costCovered ? sum(h => h.cost.selected_usd) : null,
    measured: costCovered ? sum(h => h.cost.measured_cost_usd) : null,
    estimated: costCovered ? sum(h => h.cost.estimated_cost_usd) : null,
    routing: costCovered ? sum(h => h.savings?.routing_usd) : null,
    cache: costCovered ? sum(h => h.savings?.cache_usd) : null,
    compaction: costCovered ? sum(h => h.savings?.compaction_usd) : null,
  };
}
