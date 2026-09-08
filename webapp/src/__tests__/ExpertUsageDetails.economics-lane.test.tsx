import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ExpertCost, ExpertWorkerUsage } from '../components/ExpertUsageDetails';
import { expertAge, sortExpertByCreation } from '../lib/expertEconomicsFacts';
import type { ExpertEconomicsHeader } from '../lib/expertEconomicsFacts';

afterEach(cleanup);
const header: ExpertEconomicsHeader = {
  created_at: '2026-09-07T12:00:00Z', completed_at: null, updated_at: null, latest_task_updated_at: '2026-09-07T12:01:00Z',
  completed_workers: 1, selected_workers: 2, workers_complete: true,
  usage: { tokens: 12000, tokens_known_workers: 2, cost_known_workers: 2, selected_workers: 2, complete: true },
  cost: { selected_usd: 1.5, measured_cost_usd: 1.25, estimated_cost_usd: .25, source: 'selected_current_records', basis: 'mixed', plan_workers: 0, complete: true },
  savings: { routing_usd: .04, cache_usd: .0123, compaction_usd: .003, compact_tokens: 1500, selected_usd: .0553, basis: 'estimated', source: 'selected_current_records' },
};

describe('selected expert economics lane', () => {
  it('restores collapsed mixed cost, live meters, savings and attested age', () => {
    const { rerender } = render(<ExpertCost header={header} now={Date.parse('2026-09-07T12:01:00Z')} />);
    expect(screen.getByText('12,000t')).toBeTruthy();
    expect(screen.getByText('1,500 compact')).toBeTruthy();
    expect(screen.getByText('1m ago')).toBeTruthy();
    expect(screen.getByText('1/2 workers completed')).toBeTruthy();
    expect(screen.queryByText('Measured')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Job cost' }));
    expect(screen.getByText('Measured')).toBeTruthy();
    expect(screen.getByText('$1.25')).toBeTruthy();
    expect(screen.getByText('Estimated')).toBeTruthy();
    expect(screen.getByText('$0.25')).toBeTruthy();
    expect(screen.getByText('Estimated savings ~$0.0553')).toBeTruthy();
    rerender(<ExpertCost header={{ ...header, savings: { ...header.savings, selected_usd: .11 } }} />);
    expect(screen.getByText('Estimated savings ~$0.1100')).toBeTruthy();
  });
  it('collapses worker tokens and estimated cost until click', () => {
    render(<ExpertWorkerUsage usage={{ tokens_in: 40000, tokens_out: 2000, est_cost_usd: .14, estimated: true, cost_provenance: 'catalog' }} />);
    expect(screen.queryByText('42,000t')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show tokens and cost' }));
    expect(screen.getByText('42,000t')).toBeTruthy();
    expect(screen.getByText('Estimated cost ~$0.1400')).toBeTruthy();
  });
  it('keeps provider zero distinct from plan billing and absent cost', () => {
    const { rerender } = render(<ExpertWorkerUsage planBilled usage={{ tokens_in: 0, tokens_out: 0, est_cost_usd: 0, estimated: false, cost_provenance: 'provider' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show tokens and cost' }));
    expect(screen.getByText('Provider-reported cost $0')).toBeTruthy();
    rerender(<ExpertWorkerUsage planBilled usage={{ tokens_in: null, tokens_out: null, est_cost_usd: 0, estimated: true, cost_provenance: 'plan' }} />);
    expect(screen.getByText('Plan-billed in-subscription')).toBeTruthy();
    expect(screen.queryByText('Provider-reported cost $0')).toBeNull();
    rerender(<ExpertWorkerUsage usage={{ tokens_in: null, tokens_out: null, est_cost_usd: null, estimated: null, cost_provenance: null }} />);
    expect(screen.queryByRole('button')).toBeNull();
  });
  it('sorts creation clocks in either direction, leaving missing clocks last', () => {
    const rows = [{ id: 'old', created_at: '2026-01-01T00:00:00Z' }, { id: 'unknown', created_at: null }, { id: 'new', created_at: '2026-02-01T00:00:00Z' }];
    expect(sortExpertByCreation(rows).map(r => r.id)).toEqual(['new', 'old', 'unknown']);
    expect(sortExpertByCreation(rows, 'oldest').map(r => r.id)).toEqual(['old', 'new', 'unknown']);
    expect(rows[0].id).toBe('old');
    expect(expertAge('bad clock', Date.now())).toBeNull();
  });
});
