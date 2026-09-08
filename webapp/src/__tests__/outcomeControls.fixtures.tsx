import { act } from '@testing-library/react';
import { expertMetadataFixture, expertSummary } from './metadataExpert.fixtures';
import { selection } from './jobMetadata.fixtures';
import { nativeActiveStatuses, nativeAttentionStatuses } from '../lib/localJobMetadata';
import type { LocalSummary } from '../lib/localJobMetadata';

export function outcomeSummary(id: string, goal: string, lifecycle: string) {
  return { ...expertSummary({ ...selection(), job_ref: { ...selection().job_ref, job_id: id.replaceAll('-', '_') } }, goal), lifecycle };
}
export async function nativeControlFixture() {
  const fixture = await expertMetadataFixture([outcomeSummary('job_fixture_pm', 'PM context', 'running')]);
  let row: LocalSummary = { local_ref: { job_id: 'local-kill', incarnation: 'native-1' }, revision: 1, deleted: false,
    session_id: fixture.context().session_id, lifecycle: 'running', kind: 'provider', parent_ref: null,
    task_count: 1, action_count: 0, artifact_count: 0, child_count: 0, created_at: null, updated_at: null,
    receipts: { terminal: false, launch: true, recovery: false, child: false }, economics: { kind: 'unavailable' },
    display: { label: 'Provider worker', model: '', adapter: 'agentic', truncated: false } };
  const original = fixture.request.getMockImplementation();
  if (!original) throw Error('Missing wire responder');
  fixture.request.mockImplementation(async (method, path) => {
    const url = new URL(path, 'http://fixture');
    if (url.pathname.endsWith('/view')) {
      const result = await original(method, path);
      if (!result || typeof result !== 'object') throw Error('Missing view');
      return { ...result, local: { available: true, incarnation: 'native-1', version: 1, lanes: ['active', 'history'], active_statuses: nativeActiveStatuses, attention_statuses: nativeAttentionStatuses } };
    }
    if (url.pathname.includes('/metadata/local')) {
      const lane = url.searchParams.get('lane') ?? 'history';
      const active = lane === 'active';
      const detail = url.pathname.endsWith('/detail');
      if (detail && (lane === 'tasks' || lane === 'routing')) {
        const rows = lane === 'tasks'
          ? [{ task_id: 'local-kill-w0', role: 'implement (agentic)', instruction: 'Stop this implement', status: row.lifecycle,
            adapter: 'agentic', model: '', model_kind: 'unavailable', truncated: false }]
          : [];
        return { version: 1, context: fixture.context(), incarnation: 'native-1',
          coverage: { membership: 'retained_local_history', historical: 'unavailable', ordering: 'id' },
          page: { outcome: 'complete', revision: row.revision, checkpoint: row.revision, scanned: rows.length, next_cursor: null },
          rows, missing: [], local_ref: row.local_ref, summary: row, cancellation_authority: false, lane, total: rows.length };
      }
      const rows = detail || active && row.lifecycle === 'cancelled' ? [] : [row];
      return { version: 1, context: fixture.context(), incarnation: 'native-1',
        coverage: { membership: active ? 'retained_local_active' : 'retained_local_history', historical: 'unavailable', ordering: 'id', ...(active ? { metadata: 'live_during_traversal' } : {}) },
        page: { outcome: 'complete', revision: row.revision, checkpoint: row.revision, scanned: rows.length, next_cursor: null }, rows, missing: [],
        ...(detail ? { local_ref: row.local_ref, summary: row, cancellation_authority: false, lane: 'actions', total: 0 } : { lane: active ? 'active' : 'history' }) };
    }
    return original(method, path);
  });
  await act(async () => { await fixture.store.readView(); });
  await act(async () => { await fixture.store.advanceLocal('active'); });
  return { ...fixture, cancel() { row = { ...row, lifecycle: 'cancelled', revision: 2, receipts: { ...row.receipts, terminal: true } }; } };
}
