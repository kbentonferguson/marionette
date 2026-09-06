import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import SwarmPane from '../components/SwarmPane';
import { api, type Job, type SwarmLive } from '../lib/api';
import { dispatchProjectSelected } from '../lib/panelTransition';
import { clearSWRCache } from '../lib/useStaleWhileRevalidate';
vi.mock('../lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: { ...actual.api, swarmLive: vi.fn(), sessions: vi.fn() } };
});
const job: Job = { id: 'job_same', job_ref: { job_id: 'job_same', state_id: 'state_a' },
  source: 'harness', session_id: 'A', status: 'running', goal: 'Inspect A', artifacts_complete: true, artifacts: [] };
const payload = (jobs: Job[]): SwarmLive => ({ session: { tokens_used: 0, est_cost_usd: 0 }, jobs });
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); clearSWRCache();
  dispatchProjectSelected('/A');
  vi.mocked(api.sessions).mockResolvedValue([{ id: 'A', active: true, title: 'A' }]);
});
it('shows exhausted reads and retries even when the successful row is otherwise identical', async () => {
  vi.mocked(api.swarmLive).mockResolvedValue(payload([{ ...job, read_status: 'unavailable', unavailable_fields: ['artifacts'] }]));
  render(<SwarmPane />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Job data could not be read');
  expect(screen.queryByText('No artifacts recorded.')).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Retry job data' })).toBeEnabled());
  vi.mocked(api.swarmLive).mockResolvedValue(payload([job]));
  fireEvent.click(screen.getByRole('button', { name: 'Retry job data' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
});
it('shows transport failure instead of an empty tracker and retries', async () => {
  vi.mocked(api.swarmLive).mockRejectedValue(new Error('offline'));
  render(<SwarmPane />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Swarm data could not be read');
  expect(screen.queryByText('No swarm jobs yet')).not.toBeInTheDocument();
  vi.mocked(api.swarmLive).mockResolvedValue(payload([]));
  fireEvent.click(screen.getByRole('button', { name: 'Retry swarm data' }));
  await screen.findByText('No swarm jobs yet');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('does not clear a new scope error when an old retry succeeds', async () => {
  let release: (v: SwarmLive) => void = () => {};
  vi.mocked(api.swarmLive).mockResolvedValue(payload([{ ...job, read_status: 'unavailable' }]));
  render(<SwarmPane />);
  await screen.findByRole('alert');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Retry job data' })).toBeEnabled());
  vi.mocked(api.swarmLive).mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Retry job data' }));
  await act(async () => {});
  vi.mocked(api.swarmLive).mockResolvedValue(payload([{ ...job, goal: 'Inspect B', session_id: 'B', read_status: 'unavailable' }]));
  act(() => window.dispatchEvent(new CustomEvent('harness-session-changed', { detail: { sessionId: 'B' } })));
  await screen.findByRole('button', { name: /Inspect B/ });
  await act(async () => release(payload([job])));
  expect(screen.getByRole('alert')).toHaveTextContent('Job data could not be read');
  expect(screen.getByRole('button', { name: /Inspect B/ })).toBeInTheDocument();
});

it('retries incomplete summary even when all rows stay identical', async () => {
  vi.mocked(api.swarmLive).mockResolvedValue({ ...payload([job]), session: {
    tokens_used: 0, est_cost_usd: 0, read_status: 'unavailable',
  } });
  render(<SwarmPane />);
  const retry = await screen.findByRole('button', { name: 'Retry swarm totals' });
  await waitFor(() => expect(retry).toBeEnabled());
  vi.mocked(api.swarmLive).mockResolvedValue(payload([job]));
  fireEvent.click(retry);
  await waitFor(() => expect(screen.queryByText('Swarm totals are partial / unavailable.')).not.toBeInTheDocument());
});
