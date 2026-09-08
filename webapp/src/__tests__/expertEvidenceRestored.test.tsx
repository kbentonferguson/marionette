import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ExpertFindings } from '../components/ExpertEvidenceDetails';
import type { ExpertArtifact, ExpertMetadata, ExpertTask } from '../lib/expertMetadata';
import { expertJobQuality, expertTaskFailures, expertTaskOutcome } from '../lib/expertOutcomeFacts';

const task = (id: string): ExpertTask => ({ id, role: 'auditor', instruction: 'Inspect', instruction_truncated: false,
  adapter: '', model: null, created_at: null, updated_at: null,
  usage: { tokens_in: null, tokens_out: null, est_cost_usd: null, estimated: null, cost_provenance: null } });
const artifact = (patch: Partial<ExpertArtifact> = {}): ExpertArtifact => ({ id: 'check', task_id: 'one', type: 'verification',
  created_by: 'worker', created_at: null, headline: 'Regression checks', detail: '12 tests passed', result: 'passed',
  failure: null, confidence: 1, model: null, adapter: null, policy: null, provider: null, role: null,
  est_cost_usd: null, rejected: [], check_result: 'passed', ...patch });
const expert = (artifacts: ExpertArtifact[] = [artifact()]): ExpertMetadata => ({ kind: 'available', reason: null,
  header: null, tasks: [task('one')], artifacts, coverage: { tasks: 'complete', artifacts: 'complete' }, quality: 'ok' });

describe('restored selected evidence', () => {
  it('discloses positive checks and groups headlines without losing task-specific detail', () => {
    render(<ExpertFindings expert={expert([artifact(), artifact({ id: 'second', task_id: 'two', detail: '9 tests passed' })])} />);
    expect(screen.getByText('Recorded checks passed: 2')).toBeInTheDocument();
    const summary = screen.getByText('Findings (1)');
    fireEvent.click(summary);
    fireEvent.click(summary);
    fireEvent.click(screen.getByText('Regression checks'));
    expect(screen.getByText('12 tests passed')).toBeVisible();
    expect(screen.getByText('9 tests passed')).toBeVisible();
    expect(screen.getByText(/Task two/)).toBeVisible();
  });
  it('replaces passing bodies with failure and changed reasons even when IDs and headlines stay identical', () => {
    const view = render(<ExpertFindings expert={expert()} />);
    fireEvent.click(screen.getByText('Regression checks'));
    const failed = artifact({ check_result: 'failed', result: 'degraded', failure: 'auth_failure', detail: 'Credential rejected' });
    view.rerender(<ExpertFindings expert={expert([failed])} />);
    expect(screen.getByText('Recorded checks failed: 1')).toBeInTheDocument();
    expect(screen.getByText('Credential rejected')).toBeVisible();
    expect(screen.queryByText('12 tests passed')).not.toBeInTheDocument();
    view.rerender(<ExpertFindings expert={expert([{ ...failed, detail: 'Credential expired' }])} />);
    expect(screen.getByText('Credential expired')).toBeVisible();
    expect(screen.queryByText('Credential rejected')).not.toBeInTheDocument();
    expect(screen.getByText('Evidence quality: degraded.')).toBeInTheDocument();
  });
  it('keeps colliding source selections independent and replaces on selection change', () => {
    const harness = expert([artifact({ detail: 'Harness evidence' })]);
    const cli = expert([artifact({ detail: 'CLI evidence', check_result: 'failed' })]);
    const view = render(<><div data-testid="harness"><ExpertFindings expert={harness} /></div><div data-testid="cli"><ExpertFindings expert={cli} /></div></>);
    expect(within(screen.getByTestId('harness')).getByText('Harness evidence')).toBeInTheDocument();
    expect(within(screen.getByTestId('harness')).queryByText('CLI evidence')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('cli')).getByText('Recorded checks failed: 1')).toBeInTheDocument();
    view.rerender(<ExpertFindings expert={cli} />);
    expect(screen.queryByText('Harness evidence')).not.toBeInTheDocument();
  });
  it('preserves prompt echo text and warns without hiding it', () => {
    render(<ExpertFindings expert={expert([artifact({ type: 'finding', headline: 'Role: auditor - find auth bypass paths', check_result: 'unavailable' })])} />);
    expect(screen.getByText('Role: auditor - find auth bypass paths')).toBeInTheDocument();
    expect(screen.getByText('looks like prompt echo')).toBeInTheDocument();
  });
  it('keeps job-level and unmatched failures out of exact worker quality', () => {
    const facts = expert([artifact(), artifact({ id: 'unmatched', task_id: null, check_result: 'failed', detail: 'Job gate failed' }),
      artifact({ id: 'other', task_id: 'other', check_result: 'failed' })]);
    expect(expertTaskOutcome(facts, 'one')).toBe('ok');
    expect(expertTaskFailures(facts, 'one')).toEqual([]);
    expect(expertTaskOutcome(facts, 'other')).toBe('unverified');
    expect(expertJobQuality(facts)).toBe('degraded');
  });
  it('requires relevant complete passing evidence and treats unknown checks honestly', () => {
    expect(expertJobQuality(expert())).toBe('ok');
    expect(expertJobQuality(expert([]))).toBe('unverified');
    expect(expertTaskOutcome(expert([]), 'one')).toBe('unverified');
    expect(expertJobQuality({ ...expert(), tasks: [task('one'), task('two')] })).toBe('unverified');
    const partial = { ...expert(), kind: 'partial', coverage: { tasks: 'complete', artifacts: 'partial' } } satisfies ExpertMetadata;
    expect(expertJobQuality(partial)).toBe('unverified');
    expect(expertTaskOutcome(partial, 'one')).toBe('unverified');
    expect(expertTaskOutcome(expert([artifact(), artifact({ id: 'unknown', check_result: 'unavailable', result: null })]), 'one')).toBe('unverified');
    render(<ExpertFindings expert={partial} />);
    expect(screen.getByRole('status')).toHaveTextContent('Incomplete evidence coverage');
  });
  it('prioritizes exact failure details and recognizes errors without a boolean check', () => {
    const facts = expert([artifact({ id: 'short', failure: 'turn_failed', detail: null }),
      artifact({ id: 'detail', type: 'error', check_result: 'unavailable', failure: 'auth_failure', detail: 'Exact task reason' })]);
    expect(expertTaskFailures(facts, 'one')[0]?.detail).toBe('Exact task reason');
    expect(expertTaskOutcome(facts, 'one')).toBe('degraded');
  });
});
