import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../lib/api';
import { fetchJobArtifacts } from '../lib/jobArtifacts';
import LeftRail from '../components/LeftRail';
import { clearSWRCache } from '../lib/useStaleWhileRevalidate';

vi.mock('../lib/api', () => ({ api: {
  getWorkspace: vi.fn().mockResolvedValue({ repo: '/workspace', branch: 'main', is_git: true,
    head_unborn: false, codegraph_status: 'ready', recents: [], home: '/home' }),
  workspaces: vi.fn().mockResolvedValue([{ name: 'main', active: true, dirty: false }]),
  sessions: vi.fn().mockResolvedValue([{ id: 'session-1', title: 'Current', active: true, repo: '/workspace' }]),
  jobs: vi.fn(),
} }));
vi.mock('../lib/jobArtifacts', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/jobArtifacts')>(), fetchJobArtifacts: vi.fn(),
}));
vi.mock('../lib/usePolling', () => ({ usePolling: vi.fn() }));
vi.mock('../lib/useOperationalDiagnostic', () => ({ useOperationalDiagnostic: () => null }));

beforeEach(() => {
  localStorage.clear();
  clearSWRCache();
  vi.mocked(fetchJobArtifacts).mockReset();
  vi.mocked(api.jobs).mockResolvedValue([{ id: 'job_one', goal: 'Artifact test job', status: 'complete',
    session_id: 'session-1', source: 'harness', job_ref: { job_id: 'job_one', state_id: 'state_one' } }]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function openCard() {
  render(<LeftRail jobsRefresh={0} />);
  fireEvent.click(await screen.findByRole('button', { name: /Artifact test job/ }));
}
it('shows a recorded summaryless gate rather than empty', async () => {
  vi.mocked(fetchJobArtifacts).mockResolvedValue([{ type: 'gate', headline: '' }]);
  await openCard();
  expect(await screen.findByText('1 artifact recorded without a summary')).toBeTruthy();
  expect(screen.queryByText('No artifacts recorded')).toBeNull();
  expect(fetchJobArtifacts).toHaveBeenCalledWith({ job_ref: { job_id: 'job_one', state_id: 'state_one' },
    source: 'harness', repo: '/workspace', session_id: 'session-1' });
});
it('shows failure with Retry, then genuine loaded empty', async () => {
  vi.mocked(fetchJobArtifacts).mockRejectedValueOnce(new Error('network failed')).mockResolvedValueOnce([]);
  await openCard();
  const retry = await screen.findByRole('button', { name: 'Retry' });
  expect(screen.queryByText('No artifacts recorded')).toBeNull();
  fireEvent.click(retry);
  expect(await screen.findByText('No artifacts recorded')).toBeTruthy();
});
it.each(['harness-project-selected', 'harness-session-changed'])('fences late results after %s', async event => {
  let finish: (value: Awaited<ReturnType<typeof fetchJobArtifacts>>) => void = () => {};
  vi.mocked(fetchJobArtifacts).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await openCard();
  expect(screen.getByText('Loading artifacts...')).toBeTruthy();
  await act(async () => {
    window.dispatchEvent(new CustomEvent(event, { detail: '/other' }));
    finish([{ type: 'finding', headline: 'Old scope content' }]);
  });
  expect(screen.queryByText('Old scope content')).toBeNull();
});

it('renders an HTTP 503 through the real transport and retries the bound read', async () => {
  const real = await vi.importActual<typeof import('../lib/jobArtifacts')>('../lib/jobArtifacts');
  vi.mocked(fetchJobArtifacts).mockImplementation(real.fetchJobArtifacts);
  const fetch = vi.fn().mockResolvedValueOnce(Response.json({ok: true, protocol_version: 1,
    endpoint_id: 'fixture-endpoint', boot_id: 'fixture-boot', capabilities: ['endpoint_fence_v1']}))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: 'Store unavailable' }), { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ job_ref: { job_id: 'job_one', state_id: 'state_one' },
      source: 'harness', repo: '/workspace', session_id: 'session-1',
      artifacts: [{ type: 'gate', headline: '' }] }), { status: 200 }));
  vi.stubGlobal('fetch', fetch);
  await openCard();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('1 artifact recorded without a summary')).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(String(fetch.mock.calls[1][0])).toContain('state_id=state_one');
  expect(String(fetch.mock.calls[2][0])).toContain('state_id=state_one');
});
