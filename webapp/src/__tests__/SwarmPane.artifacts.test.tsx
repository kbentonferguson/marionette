import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  return { ...actual, api: { ...actual.api, swarmLive: vi.fn(), sessions: vi.fn(), artifacts: vi.fn() } };
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
});
it('retries locally and treats a successful empty response as loaded', async () => {
  vi.mocked(fetchJobArtifacts).mockRejectedValueOnce(new Error('store offline')).mockResolvedValueOnce([]);
  render(<SwarmPane />); await expand('Inspect A');
  fireEvent.click(await screen.findByRole('button', { name: 'Retry artifacts' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Retry artifacts' })).not.toBeInTheDocument());
  await waitFor(() => expect(fetchJobArtifacts).toHaveBeenCalledTimes(2));
  await screen.findByText('Worker running -- artifacts will stream in as they land.');
  expect(fetchJobArtifacts).toHaveBeenLastCalledWith({ job_ref: base.job_ref, source: 'harness', repo: '/A', session_id: 'A' });
  expect(api.artifacts).not.toHaveBeenCalled();
});
it.each([{ ...base, job_ref: undefined }, { ...base, cross_project: true }, { ...base, session_id: 'foreign' }])(
  'refuses an unselectable artifact preview without an id-only fallback', async job => {
    localStorage.setItem("marionette.jobScope.v1", "all");
    rows([job]); render(<SwarmPane />); await expand('Inspect A');
    expect(await screen.findByText(/Artifact preview is unavailable/)).toBeInTheDocument();
    expect(fetchJobArtifacts).not.toHaveBeenCalled(); expect(api.artifacts).not.toHaveBeenCalled();
  });
it('fences an old response when a colliding job is selected in another session', async () => {
  let release: (value: Artifact[]) => void = () => {};
  vi.mocked(fetchJobArtifacts).mockReturnValueOnce(new Promise(resolve => { release = resolve; })).mockResolvedValue([]);
  render(<SwarmPane />); await expand('Inspect A');
  await waitFor(() => expect(fetchJobArtifacts).toHaveBeenCalledTimes(1));
  rows([{ ...base, goal: 'Inspect B', session_id: 'B', job_ref: { job_id: base.id, state_id: 'state_b' } }]);
  act(() => window.dispatchEvent(new CustomEvent('harness-session-changed', { detail: { sessionId: 'B' } })));
  await expand('Inspect B');
  await act(async () => { release([{ type: 'finding', headline: 'Private A result' }]); });
  expect(screen.queryByText('Private A result')).not.toBeInTheDocument();
  if (screen.queryByRole('button', { name: 'Retry artifacts' })) fireEvent.click(screen.getByRole('button', { name: 'Retry artifacts' }));
  await waitFor(() => expect(fetchJobArtifacts).toHaveBeenCalledWith({ job_ref: { job_id: base.id, state_id: 'state_b' }, source: 'harness', repo: '/A', session_id: 'B' }));
});
it('hydrates colliding sources independently in the same live snapshot', async () => {
  rows([base, { ...base, goal: 'Inspect CLI', source: 'cli', job_ref: { job_id: base.id, state_id: 'state_cli' } }]);
  vi.mocked(fetchJobArtifacts).mockImplementation(async selection => [{ type: 'finding',
    headline: selection.source === 'cli' ? 'CLI evidence' : 'Harness evidence' }]);
  render(<SwarmPane />); await expand('Inspect A');
  await screen.findByText('Harness evidence');
  expect(screen.queryByText('CLI evidence')).not.toBeInTheDocument();
  await expand('Inspect CLI');
  expect(await screen.findByText('CLI evidence')).toBeInTheDocument();
  expect(screen.getAllByText('Harness evidence')).toHaveLength(1);
  expect(screen.getAllByText('CLI evidence')).toHaveLength(1);
  expect(fetchJobArtifacts).toHaveBeenCalledTimes(2);
});
