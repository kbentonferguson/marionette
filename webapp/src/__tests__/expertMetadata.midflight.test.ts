import { describe, expect, it } from 'vitest';
import payload from './fixtures/midflight-running.json';
import { MetadataError, parseMetadataDetail, parseMetadataList, parseMetadataPins } from '../lib/jobMetadata';
import { parseExpertHeader, parseExpertMetadata } from '../lib/expertMetadata';
import type { MetadataContext, MetadataSelection } from '../lib/jobMetadata';

const ctx = payload.context as MetadataContext;
const selection = payload.selection as MetadataSelection;
const cursors = { task_cursor: null, artifact_cursor: null };

describe('mid-flight running job fixtures', () => {
  it('parses producer detail, pins, and running membership page', () => {
    const detail = parseMetadataDetail(payload.detail, ctx, selection, cursors);
    expect(detail.lifecycle).toBe('running');
    expect(detail.expert?.kind === 'unavailable' || (detail.expert?.tasks.length ?? 0) > 0).toBe(true);
    const pins = parseMetadataPins(payload.pins, ctx, [selection]);
    expect(pins.results[0].result.kind).toBe('present');
    const stream = { store: { source: selection.source, state_id: selection.job_ref.state_id }, status: 'running' as const };
    const page = parseMetadataList(payload.page, ctx, stream, { mode: 'snapshot', after_revision: 0, cursor: null });
    expect(page.rows.some(row => !row.deleted && row.lifecycle === 'running')).toBe(true);
  });

  it('degrades lane revision skew to unavailable expert instead of throwing', () => {
    const skewed = structuredClone(payload.detail);
    skewed.artifacts.page.revision += 1;
    skewed.artifacts.page.checkpoint = skewed.artifacts.page.revision;
    const parsed = parseMetadataDetail(skewed, ctx, selection, cursors);
    expect(parsed.expert?.kind).toBe('unavailable');
    expect(parsed.expert?.reason).toBe('lane_revision_skew');
    expect(parsed.tasks.rows.length).toBeGreaterThan(0);
  });

  it('names failing fields on MetadataError.detail', () => {
    try {
      parseExpertHeader({
        created_at: null, completed_at: null,
        completed_workers: 3, selected_workers: 1, workers_complete: true,
        usage: { tokens: 1, tokens_known_workers: 1, cost_known_workers: 1, selected_workers: 1, complete: false },
        cost: { selected_usd: 1, source: 'selected_current_records', basis: 'estimated', measured_cost_usd: null, estimated_cost_usd: 1, complete: false, plan_workers: 0 },
        savings: { routing_usd: null, cache_usd: null, compaction_usd: null, compact_tokens: null, selected_usd: null, basis: 'estimated', source: 'selected_current_records' },
      });
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).message).toContain('invalid_metadata');
      expect((error as Error & { detail?: string }).detail).toBe('header.usage');
    }
    try {
      parseMetadataDetail({ ...payload.detail, version: 2 }, ctx, selection, cursors);
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(MetadataError);
      expect((error as MetadataError).code).toBe('invalid_metadata');
    }
  });

  it('degrades orphan sources, blank models, bad clocks, and over-confidence', () => {
    const expert = structuredClone(payload.detail.expert);
    if (!expert?.tasks?.[0] || !expert.artifacts?.[0]) return;
    expert.tasks[0].model = '';
    expert.tasks[0].created_at = '2026-09-11T12:00:00+0000';
    expert.artifacts[0].confidence = 1.5;
    expert.artifacts[0].check_result = 'pending';
    if (expert.economics?.tasks?.[expert.tasks[0].id]) {
      expert.economics.tasks[expert.tasks[0].id].source_artifact_id = 'missing-artifact';
    }
    const parsed = parseExpertMetadata(expert, payload.detail.artifacts.rows);
    expect(parsed.tasks[0].model).toBeNull();
    expect(parsed.tasks[0].created_at).toBeNull();
    expect(parsed.artifacts[0].confidence).toBeNull();
    expect(parsed.artifacts[0].check_result).toBe('unavailable');
    if (parsed.tasks[0].usage.source_artifact_id !== undefined) {
      expect(parsed.tasks[0].usage.source_artifact_id).toBeNull();
    }
  });
});
