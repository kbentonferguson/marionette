import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import SwarmPane from '../components/SwarmPane';
import { api, type Artifact, type Job } from '../lib/api';
import { fetchJobArtifacts } from '../lib/jobArtifacts';
import { dispatchProjectSelected } from '../lib/panelTransition';
import { clearSWRCache } from '../lib/useStaleWhileRevalidate';
vi.mock('../lib/jobArtifacts', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/jobArtifacts')>(), fetchJobArtifacts: vi.fn(),
}));
vi.mock('../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: { ...actual.api, swarmCancel: vi.fn(), swarmLive: vi.fn(), sessions: vi.fn(), artifacts: vi.fn() } };
});
const base: Job = { id: 'job_same', job_ref: { job_id: 'job_same', state_id: 'state_a' },
  source: 'harness', session_id: 'A', status: 'running', goal: 'Inspect A', artifacts_complete: false };
function rows(jobs: Job[]) {
  vi.mocked(api.swarmLive).mockResolvedValue({ session: { tokens_used: 0, est_cost_usd: 0 }, jobs });
}
async function expand(name: string) {
  const row = await screen.findByRole('button', { name: new RegExp(name) });
  if (row.getAttribute('aria-expanded') === 'false') fireEvent.click(row);
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); clearSWRCache();
  dispatchProjectSelected('/A');
  vi.mocked(api.sessions).mockResolvedValue([{ id: 'A', active: true, title: 'A' }]);
  rows([base]);
  vi.mocked(fetchJobArtifacts).mockResolvedValue([]);
});
it('cancels only one of two rows sharing a job id', async () => {
  rows([base, { ...base, goal: 'Inspect CLI', source: 'cli', job_ref: { job_id: base.id, state_id: 'state_cli' } }]);
  vi.mocked(api.swarmCancel).mockReturnValue(new Promise(() => {}));
  render(<SwarmPane />);
  const cli = await screen.findByRole('button', { name: /Inspect CLI/ });
  const cancel = within(cli).getByRole('button', { name: 'Cancel this job' });
  await waitFor(() => expect(cancel).toBeEnabled());
  fireEvent.click(cancel);
  expect(api.swarmCancel).toHaveBeenCalledWith({ version: 1, source: 'cli', repo: '/A', session_id: 'A',
    job_ref: { job_id: base.id, state_id: 'state_cli' } });
  expect(screen.getAllByText('cancelling...')).toHaveLength(1);
  expect(within(screen.getByRole('button', { name: /Inspect A/ })).getByRole('button', { name: 'Cancel this job' })).toBeEnabled();
});
it('dismisses one colliding terminal row and persists only scoped keys', async () => {
  rows([{ ...base, status: 'failed' }, { ...base, goal: 'Inspect CLI', status: 'failed', source: 'cli', job_ref: { job_id: base.id, state_id: 'state_cli' } }]);
  localStorage.setItem('swarm.dismissed.v2', JSON.stringify({ '/A': [base.id] }));
  render(<SwarmPane />);
  fireEvent.click(await screen.findByRole('button', { name: /Finished/ }));
  const cli = await screen.findByRole('button', { name: /Inspect CLI/ });
  fireEvent.click(within(cli).getByRole('button', { name: /Dismiss from tracker/ }));
  expect(screen.queryByRole('button', { name: /Inspect CLI/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Inspect A/ })).toBeInTheDocument();
  expect(localStorage.getItem('swarm.dismissed.v3')).toContain('state_cli');
  expect(localStorage.getItem('swarm.dismissed.v2')).toContain(base.id);
});
it('fences cancel rejection after switching sessions and starting another cancel', async () => {
  let release: (result: { ok: boolean }) => void = () => {};
  vi.mocked(api.swarmCancel).mockReturnValueOnce(new Promise(resolve => { release = resolve; }))
    .mockReturnValue(new Promise(() => {}));
  render(<SwarmPane />);
  await screen.findByRole('button', { name: /Inspect A/ });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel this job' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Cancel this job' }));
  rows([{ ...base, goal: 'Inspect B', session_id: 'B' }]);
  act(() => window.dispatchEvent(new CustomEvent('harness-session-changed', { detail: { sessionId: 'B' } })));
  await screen.findByRole('button', { name: /Inspect B/ });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel this job' }));
  const polls = vi.mocked(api.swarmLive).mock.calls.length;
  await act(async () => release({ ok: false }));
  expect(screen.getAllByText('cancelling...')).toHaveLength(1);
  expect(api.swarmLive).toHaveBeenCalledTimes(polls);
});
it('sends a session-scoped local selection without a durable reference', async () => {
  rows([{ ...base, id: 'local-test', job_ref: undefined }]);
  vi.mocked(api.swarmCancel).mockReturnValue(new Promise(() => {}));
  render(<SwarmPane />);
  await screen.findByRole('button', { name: /Inspect A/ });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel this job' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Cancel this job' }));
  expect(api.swarmCancel).toHaveBeenCalledWith({ version: 1, source: 'local', repo: '/A', session_id: 'A',
    job_ref: { job_id: 'local-test', state_id: null } });
});
it.each([{ ...base, job_ref: undefined }, { ...base, cross_project: true },
  { ...base, session_id: 'foreign' }, { ...base, job_ref: { job_id: 'different', state_id: 'state_a' } }])(
  'disables cancellation when the row cannot prove its identity', async job => {
    localStorage.setItem('marionette.jobScope.v1', 'all');
    rows([job]); render(<SwarmPane />);
    await screen.findByRole('button', { name: /Inspect A/ });
    const cancel = screen.getByRole('button', { name: 'Cancel this job' });
    expect(cancel).toBeDisabled();
    fireEvent.click(cancel);
    expect(api.swarmCancel).not.toHaveBeenCalled();
  });
it('persists expansion separately for each store', async () => {
  rows([base, { ...base, goal: 'Inspect CLI', source: 'cli', job_ref: { job_id: base.id, state_id: 'state_cli' } }]);
  const first = render(<SwarmPane />); await expand('Inspect A');
  expect(screen.getByRole('button', { name: /Inspect CLI/ })).toHaveAttribute('aria-expanded', 'false');
  first.unmount(); clearSWRCache();
  render(<SwarmPane />);
  await waitFor(() => expect(screen.getByRole('button', { name: /Inspect A/ })).toHaveAttribute('aria-expanded', 'true'));
  expect(screen.getByRole('button', { name: /Inspect CLI/ })).toHaveAttribute('aria-expanded', 'false');
});
it.each(['response', 'transport'])('shows %s refusal only on the selected row and keeps running controls retryable', async mode => {
  rows([base, { ...base, goal: 'Inspect CLI', source: 'cli', job_ref: { job_id: base.id, state_id: 'state_cli' } }]);
  if (mode === 'response') vi.mocked(api.swarmCancel).mockResolvedValue({ ok: false,
    error: 'Cancel is unavailable: the worker was not stopped. Scoped kernel cancellation is required; the job remains running.' });
  else vi.mocked(api.swarmCancel).mockRejectedValue(new Error('HTTP 409'));
  render(<SwarmPane />);
  const cli = await screen.findByRole('button', { name: /Inspect CLI/ });
  const cancel = within(cli).getByRole('button', { name: 'Cancel this job' });
  await waitFor(() => expect(cancel).toBeEnabled());
  fireEvent.click(cancel);
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('worker was not stopped');
  expect(alert).toHaveTextContent('remains running');
  expect(cli.closest('[data-job-id]')).toContainElement(alert);
  expect(screen.queryByText('cancelling...')).not.toBeInTheDocument();
  expect(within(cli).getByRole('button', { name: 'Cancel this job' })).toBeEnabled();
  expect(screen.getAllByRole('button', { name: 'Cancel this job' })).toHaveLength(2);
  fireEvent.click(within(cli).getByRole('button', { name: 'Cancel this job' }));
  await waitFor(() => expect(api.swarmCancel).toHaveBeenCalledTimes(2));
  rows([{ ...base, session_id: 'B', goal: 'Inspect B' }]);
  act(() => window.dispatchEvent(new CustomEvent('harness-session-changed', { detail: { sessionId: 'B' } })));
  await screen.findByRole('button', { name: /Inspect B/ });
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
