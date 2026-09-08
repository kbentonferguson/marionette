import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { JobMetadataStore, useJobMetadata } from './useJobMetadata';
import type { JobMetadataState } from './useJobMetadata';
import type { Job } from './api';
import { metadataSelectionKey } from './jobMetadata';
import { localKey, nativeActiveStatuses } from './localJobMetadata';

const inactive = new JobMetadataStore();
export const JobMetadataContext = createContext(inactive);
export function JobMetadataOwner({ repo, sessionId, children }: { repo: string; sessionId: string | null; children: ReactNode }) {
  const [store] = useState(() => new JobMetadataStore());
  useEffect(() => {
    if (!repo || !sessionId) { store.invalidate(); return; }
    store.setTarget({ repo, session_id: sessionId, scope: 'all' });
    const tick = () => { if (!document.hidden) void store.ownerTick(); };
    store.startTicks(2000); tick();
    document.addEventListener('visibilitychange', tick);
    return () => { store.stopTicks(); store.invalidate(); document.removeEventListener('visibilitychange', tick); };
  }, [store, repo, sessionId]);
  // Effect cleanup must support React StrictMode's setup-cleanup-setup replay.
  useEffect(() => () => { store.stopTicks(); store.invalidate(); store.closeConnection(); }, [store]);
  return <JobMetadataContext.Provider value={store}>{children}</JobMetadataContext.Provider>;
}
export function useSharedJobMetadata() {
  const store = useContext(JobMetadataContext);
  return { store, state: useJobMetadata(store) };
}
/** Leaf provider workers belong under Swarm Tracker inspect, not Jobs or the composer rail. */
export function isJobsListRow(job: Pick<Job, "job_kind">): boolean {
  return job.job_kind !== "provider";
}
export function metadataActivity(state: JobMetadataState): { count: number; label: string } {
  const active = new Set(nativeActiveStatuses);
  const count = state.observations.filter(o => o.freshness === 'observed' && active.has(o.row.lifecycle ?? '')).length
    + state.local.observations.filter(o => o.freshness === 'observed' && active.has(o.row.lifecycle)).length;
  return { count, label: count ? `At least ${count} active jobs; coverage incomplete` : 'Job activity unknown; coverage incomplete' };
}
/** Current selected facts are valid only for this exact source and revision. */
export function currentExpert(state: JobMetadataState, key: string) {
  const selected = state.detail.kind === 'selected' && metadataSelectionKey(state.detail.selection) === key ? state.detail : state.detailCache[key];
  if (!selected || selected.freshness !== 'observed' || selected.error || !selected.observation) return undefined;
  const listed = state.observations.find(o => metadataSelectionKey(o.row.selection) === key);
  if (listed?.freshness === 'stale') return undefined;
  const latest = Math.max(0, ...[...state.observations, ...state.pins.flatMap(p => p.observation ? [p.observation] : [])].filter(o => metadataSelectionKey(o.row.selection) === key).map(o => o.row.revision), state.headers[key]?.observation.row.revision ?? 0);
  return selected.observation.tasks.page.revision >= latest && selected.observation.artifacts.page.revision >= latest ? selected.observation.expert : undefined;
}
export function currentHeader(state: JobMetadataState, key: string) {
  const expert = currentExpert(state, key);
  const cached = state.headers[key];
  const stale = state.observations.some(o => metadataSelectionKey(o.row.selection) === key && o.freshness === 'stale');
  const header = !stale && cached?.observation.freshness === 'observed'
    ? cached.observation.row.header : undefined;
  const selected = expert?.kind !== 'unavailable' ? expert?.live_economics ?? expert?.header : undefined;
  if (selected) return selected.model_provenance === undefined && header?.model_provenance !== undefined
    ? { ...selected, model: header.model, model_provenance: header.model_provenance } : selected;
  return header;
}
/** Presentation only: missing bodies/economics remain explicitly unavailable. No identity inference. */
export function metadataJobs(state: JobMetadataState): Job[] {
  if (state.view.kind !== 'view') return [];
  const view = state.view;
  const observed = new Map(state.observations.map(o => [metadataSelectionKey(o.row.selection), o]));
  for (const pin of state.pins) {
    if (!pin.observation) continue;
    const key = metadataSelectionKey(pin.selection), current = observed.get(key);
    if (!current || pin.observation.row.revision > current.row.revision
      || (pin.observation.row.revision === current.row.revision && pin.observation.freshness === 'observed')) observed.set(key, pin.observation);
  }
  const pm: Job[] = [...observed.values()].filter(({ row }) => row.selection.source !== 'cli'
    || (row.stamp === 'known' && !!row.ownership.session_id?.trim())).map(({ row, freshness }) => ({
    id: row.selection.job_ref.job_id, job_ref: row.selection.job_ref, source: row.selection.source,
    metadata_key: metadataSelectionKey(row.selection), metadata_only: true,
    goal: row.display.kind === 'available' && row.display.goal_preview ? row.display.goal_preview : `${row.selection.source === 'cli' ? 'PM CLI job' : 'PM harness job'}`,
    status: row.lifecycle ?? 'unknown', session_id: row.ownership.session_id ?? undefined,
    cross_project: view.view.sources.find(s => s.state_id === row.selection.job_ref.state_id)?.cross_project,
    ...(freshness === 'stale' ? { read_status: 'unavailable' } : {}),
    unavailable_fields: ['artifacts', 'tasks'], artifacts_complete: false,
    ...(row.task_count === null ? {} : { task_count: row.task_count }),
  }));
  const nativeObserved = new Map(state.local.observations.map(o => [localKey(o.row.local_ref), o]));
  const selectedSummary = state.localDetail?.observation?.summary;
  if (selectedSummary && !nativeObserved.has(localKey(selectedSummary.local_ref))) nativeObserved.set(localKey(selectedSummary.local_ref), { row: selectedSummary, freshness: 'stale', observedAt: 0 });
  const local: Job[] = [...nativeObserved.values()].map(({ row, freshness }) => ({
    id: row.local_ref.job_id, local_ref: row.local_ref, source: 'local', metadata_only: true,
    metadata_key: localKey(row.local_ref), goal: (row.display ? `${row.display.label}${row.display.model ? ` · ${row.display.model}` : ''}` : row.kind.replaceAll('_', ' ')),
    status: row.lifecycle, session_id: row.session_id, job_kind: row.kind, role: row.kind,
    ...(freshness === 'stale' ? { read_status: 'unavailable' } : {}),
    updated_at: row.updated_at, unavailable_fields: ['artifacts', 'tasks'], artifacts_complete: false,
    ...(row.task_count === null ? {} : { task_count: row.task_count }),
  }));
  return [...pm, ...local];
}
