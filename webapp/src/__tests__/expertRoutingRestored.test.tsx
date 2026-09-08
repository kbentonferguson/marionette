import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ExpertWorkers } from '../components/ExpertWorkerDetails';
import type { ExpertArtifact, ExpertMetadata, ExpertTask } from '../lib/expertMetadata';
import { parseExpertMetadata } from '../lib/expertMetadata';
import type { MetadataTask } from '../lib/jobMetadata';
import { expertWorkerSlot, resolveExpertRouting } from '../lib/expertRoutingFacts';

afterEach(cleanup);
function task(id = 'task-a', overrides: Partial<ExpertTask> = {}): ExpertTask {
  return { id, role: id, instruction: 'Exact worker instructions', instruction_truncated: false, adapter: 'agentic', model: null,
    created_at: null, updated_at: null, usage: { tokens_in: null, tokens_out: null, est_cost_usd: null, estimated: null, cost_provenance: null }, ...overrides };
}
function route(id: string, overrides: Partial<ExpertArtifact> = {}): ExpertArtifact {
  return { id, task_id: 'task-a', type: 'routing', created_by: 'router', created_at: null, headline: '', detail: null,
    result: null, failure: null, confidence: null, model: 'model-a', adapter: null, policy: null, provider: null, role: null,
    est_cost_usd: null, rejected: [], check_result: 'unavailable', ...overrides };
}
function expert(tasks: ExpertTask[], artifacts: ExpertArtifact[] = [], overrides: Partial<ExpertMetadata> = {}): ExpertMetadata {
  return parseExpertMetadata({ kind: 'available', reason: null, header: null, tasks, artifacts,
    coverage: { tasks: 'complete', artifacts: 'complete' }, quality: 'unverified', ...overrides });
}
function refs(tasks: ExpertTask[], status = 'running'): MetadataTask[] {
  return tasks.map(t => ({ id: t.id, status, stamp: 'known', revision: 1, binding: null }));
}

describe('restored current expert worker routing', () => {
  it('prefers escalation over fallback over router and later equal-rank final decisions', () => {
    const t = task();
    const artifacts = [route('fallback', { created_by: 'router-fallback', model: 'fallback' }),
      route('first', { created_by: 'router-escalation', model: 'first' }), route('final', { created_by: 'router-escalation', model: 'final' }),
      route('router', { model: 'stale' })];
    render(<ExpertWorkers expert={expert([t], artifacts)} tasks={refs([t])} />);
    expect(screen.getByLabelText('Model: final')).toBeInTheDocument();
    expect(screen.queryByLabelText('Model: stale')).not.toBeInTheDocument();
    expect(resolveExpertRouting(expert([t], artifacts.slice(0, 1))).routingForTask.get(t.id)?.model).toBe('fallback');
  });
  it('uses recorded time for equal ranks even when the page order differs', () => {
    const e = expert([task()], [route('new', { model: 'new', created_at: '2026-09-07T12:00:00Z' }),
      route('old', { created_at: '2026-09-07T11:00:00Z' })]);
    expect(resolveExpertRouting(e).routingForTask.get('task-a')?.model).toBe('new');
  });
  it('applies parser-validated routing-only poll updates with unchanged task facts and counts', () => {
    const tasks = [task()];
    const { rerender } = render(<ExpertWorkers expert={expert(tasks, [route('r', { model: null })])} tasks={refs(tasks)} />);
    expect(screen.getByText('routing…')).toBeInTheDocument();
    rerender(<ExpertWorkers expert={expert(tasks, [route('r', { model: 'gpt-6-astra' })])} tasks={refs(tasks)} />);
    expect(screen.getByLabelText('Model: gpt-6-astra')).toBeInTheDocument();
    rerender(<ExpertWorkers expert={expert(tasks, [route('r', { model: 'gpt-6-astra-low' })])} tasks={refs(tasks)} />);
    expect(screen.getByLabelText('Model: gpt-6-astra-low')).toBeInTheDocument();
    expect(screen.queryByText('gpt-6-astra')).not.toBeInTheDocument();
  });
  it.each(['agentic', 'native', 'agentic/native', 'codex'])('keeps the actual task model over engine-only %s', stamp => {
    const t = task('task-a', { model: 'agentic/native/openai/gpt-6' });
    expect(expertWorkerSlot(t, 'running', route('r', { model: stamp }))).toBe('openai/gpt-6');
  });
  it('shows each own model or adapter without borrowing a sibling model', () => {
    const tasks = [task('a', { model: 'own-a' }), task('b', { adapter: 'openrouter' }), task('c')];
    render(<ExpertWorkers expert={expert(tasks)} tasks={refs(tasks)} headerModel="job-model" />);
    expect(screen.getByLabelText('Model: own-a')).toBeInTheDocument();
    expect(screen.getByLabelText('Model: openrouter')).toBeInTheDocument();
    expect(screen.getByText('routing…')).toBeInTheDocument();
    expect(screen.queryByText('job-model')).not.toBeInTheDocument();
    expect(expertWorkerSlot(task(), 'complete')).toBe('No model recorded');
    expect(expertWorkerSlot(task(), 'pending')).toBe('routing…');
    expect(expertWorkerSlot(task(), 'queued')).toBe('routing…');
  });
  it('associates only a unique normalized role and never steals an explicit task id', () => {
    const tasks = [task('a', { role: 'Reviewer' }), task('b', { role: 'builder' })];
    const result = resolveExpertRouting(expert(tasks, [route('role', { task_id: null, role: ' reviewer ' }),
      route('foreign', { task_id: 'other', role: 'builder', model: 'foreign' })]));
    expect(result.routingForTask.get('a')?.id).toBe('role');
    expect(result.routingForTask.has('b')).toBe(false);
    expect(result.unmatched.map(r => r.id)).toEqual(['foreign']);
    const ambiguous = resolveExpertRouting(expert([task('a', { role: 'same' }), task('b', { role: 'same' })], [route('r', { task_id: null, role: 'same' })]));
    expect(ambiguous.routingForTask.size).toBe(0);
    const partial = resolveExpertRouting(expert([task()], [route('r', { task_id: null, role: 'task-a' })], { coverage: { tasks: 'partial', artifacts: 'complete' } }));
    expect(partial.routingForTask.size).toBe(0);
  });
  it('associates one unscoped decision to one remaining worker but preserves ambiguous residuals', () => {
    const t = task();
    expect(resolveExpertRouting(expert([t], [route('r', { task_id: null })])).routingForTask.get(t.id)?.id).toBe('r');
    const ambiguous = resolveExpertRouting(expert([t], [route('r', { task_id: null }), route('s', { task_id: null, model: 'other' })]));
    expect(ambiguous.routingForTask.size).toBe(0);
    expect(ambiguous.unmatched).toHaveLength(2);
  });
  it('dedupes residual decisions in one note after workers and suppresses a supplied header duplicate', () => {
    const tasks = [task('task-a', { model: 'worker-model' })];
    const artifacts = [route('old', { task_id: 'orphan', model: 'old' }), route('final', { task_id: 'orphan', model: 'orphan-model', provider: 'openrouter' })];
    const { rerender } = render(<ExpertWorkers expert={expert(tasks, artifacts)} tasks={refs(tasks)} />);
    expect(screen.getByText('Unmatched routing · orphan-model · no matching worker')).toBeInTheDocument();
    expect(screen.queryByText('old')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Model: orphan-model')).not.toBeInTheDocument();
    const headerRoute = route('r', { task_id: null, model: 'glm-5.2', provider: 'openrouter', policy: 'balanced' });
    rerender(<ExpertWorkers expert={expert([], [headerRoute])} tasks={[]} headerModel="glm-5.2" />);
    expect(screen.queryByText(/Unmatched routing/)).not.toBeInTheDocument();
    rerender(<ExpertWorkers expert={expert([], [{ ...headerRoute, policy: 'explicit_pin' }])} tasks={[]} headerModel="glm-5.2" />);
    expect(screen.getByText(/Unmatched routing/)).toBeInTheDocument();
  });
  it('reveals exact instruction, pin, provider, and rejected alternatives only on expansion', () => {
    const tasks = [task()];
    render(<ExpertWorkers expert={expert(tasks, [route('r', { policy: 'explicit_pin', provider: 'codex', rejected: [{ model: 'alternative', reason: 'Too small' }] })])} tasks={refs(tasks)} />);
    expect(screen.queryByText('Exact worker instructions')).not.toBeInTheDocument();
    expect(screen.queryByText(/explicit_pin|Too small|Provider:/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /task-a/ }));
    expect(screen.getByText('Exact worker instructions')).toBeInTheDocument();
    expect(screen.getByText('Policy: explicit_pin')).toBeInTheDocument();
    expect(screen.getByText('Provider: codex')).toBeInTheDocument();
    expect(screen.getByText('alternative: Too small')).toBeInTheDocument();
  });
  it('keeps failure information exact-task and updates expanded detail on poll', () => {
    const tasks = [task('a'), task('b')];
    const failure = route('f', { task_id: 'a', type: 'verification', check_result: 'failed', failure: 'auth_failure', detail: 'Expired credential' });
    const { rerender } = render(<ExpertWorkers expert={expert(tasks, [failure])} tasks={refs(tasks, 'complete')} />);
    fireEvent.click(screen.getByRole('button', { name: /^a / }));
    fireEvent.click(screen.getByRole('button', { name: /^b / }));
    expect(screen.getByText('Expired credential')).toBeInTheDocument();
    const second = screen.getByRole('button', { name: /^b / }).parentElement;
    if (!second) throw new Error('missing worker container');
    expect(within(second).queryByText('auth_failure')).not.toBeInTheDocument();
    rerender(<ExpertWorkers expert={expert(tasks, [{ ...failure, detail: 'Credential rejected' }])} tasks={refs(tasks, 'complete')} />);
    expect(screen.getByText('Credential rejected')).toBeInTheDocument();
    expect(screen.queryByText('Expired credential')).not.toBeInTheDocument();
  });
  it.each([220, 320])('uses separate shrinkable role and model columns at %ipx', width => {
    const tasks = [task('a', { role: 'test-coverage-reviewer', model: 'provider/a-very-long-model-identifier' })];
    const { container } = render(<div style={{ width }}><ExpertWorkers expert={expert(tasks)} tasks={refs(tasks)} /></div>);
    const slot = container.querySelector('[data-worker-model-slot]');
    expect(slot).toHaveClass('min-w-0', '[overflow-wrap:anywhere]');
    expect(slot?.parentElement).toHaveClass('grid', 'grid-cols-[minmax(0,1fr)_minmax(0,1fr)]');
    expect(slot?.previousElementSibling?.textContent).toContain('test-coverage-reviewer');
  });
  it('keeps provider-attested zero measured even when the route is plan-billed', () => {
    const tasks = [task('task-a', { usage: { tokens_in: 500, tokens_out: 100, est_cost_usd: 0, estimated: false, cost_provenance: 'provider' } })];
    render(<ExpertWorkers expert={expert(tasks, [route('r', { detail: 'plan-billed in-subscription' })])} tasks={refs(tasks)} />);
    fireEvent.click(screen.getByRole('button', { name: /task-a/ }));
    expect(screen.queryByText('Measured cost: $0')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Worker usage' }));
    expect(screen.getByText('Measured cost: $0')).toBeInTheDocument();
    expect(screen.getByText(/Input tokens: 500/)).toBeInTheDocument();
  });
  it('does not assign job-level failures or foreign failures to workers', () => {
    const tasks = [task('a')];
    render(<ExpertWorkers expert={expert(tasks, [
      route('job-failure', { task_id: null, type: 'verification', check_result: 'failed', failure: 'job-only-failure' }),
      route('foreign-failure', { task_id: 'other', type: 'error', failure: 'foreign-failure' }),
    ], { quality: 'degraded' })} tasks={refs(tasks, 'complete')} />);
    fireEvent.click(screen.getByRole('button', { name: /^a / }));
    expect(screen.queryByText('job-only-failure')).not.toBeInTheDocument();
    expect(screen.queryByText('foreign-failure')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^a / }).parentElement).toHaveAttribute('data-quality', 'unverified');
  });
  it('does not call an unattested plan zero measured and allows an economics slot replacement', () => {
    const tasks = [task('task-a', { usage: { tokens_in: null, tokens_out: null, est_cost_usd: 0, estimated: true, cost_provenance: 'catalog' } })];
    const e = expert(tasks, [route('r', { detail: 'plan-billed in-subscription' })]);
    const { rerender } = render(<ExpertWorkers expert={e} tasks={refs(tasks)} />);
    fireEvent.click(screen.getByRole('button', { name: /task-a/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Worker usage' }));
    expect(screen.getByText('Plan-billed; provider cost unknown')).toBeInTheDocument();
    expect(screen.queryByText('Measured cost: $0')).not.toBeInTheDocument();
    rerender(<ExpertWorkers expert={e} tasks={refs(tasks)} renderUsage={({ task: worker, route: selectedRoute }) => <p>{worker.id} usage for {selectedRoute?.model}</p>} />);
    expect(screen.getByText('task-a usage for model-a')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Worker usage' })).not.toBeInTheDocument();
  });

});
