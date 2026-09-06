import { withEndpointDiscovery, withDesktopEndpointDiscovery } from "./endpointFixture";
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import JobEvidence from '../components/JobEvidence';
import { fetchJobEvidence, type JobEvidenceData, type ConsumptionMetric } from '../lib/jobEvidence';
import { getActiveDiagnostic, resetDiagnosticBus } from '../lib/operationalDiagnosticBus';
import { useOperationalDiagnostic } from '../lib/useOperationalDiagnostic';

const unknownMetric = {
  total: null, known_subtotal: null, status: 'unknown', known_attempts: 0,
  unknown_attempts: 0, estimated_attempts: 0, conflicting_attempts: 0,
} satisfies ConsumptionMetric;
const emptyConsumption = {
  tokens_in: unknownMetric, tokens_out: unknownMetric, cache_read_tokens: unknownMetric,
  cache_write_tokens: unknownMetric, api_cost_usd: unknownMetric,
  plan_marginal_cost_usd: unknownMetric, api_equivalent_cost_usd: unknownMetric,
};
const selection = { stateId: 'state_a', jobId: 'job_a', sessionId: 'A', repo: '/A', source: 'harness' };
const unavailable = { code: 'job_evidence_unavailable', message: 'Unavailable' };
const data: JobEvidenceData = {
  job_ref: { job_id: 'job_a', state_id: 'state_a' }, source: 'harness', status: 'completed',
  links: { request: null, turn: null, action: null, attempts: 'unavailable' },
  attempts: [], attempt_coverage: 'unverified', totals: { tasks: 1, artifacts: 1, attempts: 0 },
  tasks: [{ id: 'task_a', status: 'completed', attempt_count: 1 }],
  artifacts: [{ id: 'gate_a', task_id: null, type: 'gate', presence: 'recorded', check_result: 'failed' }],
  cost: { selected_usd: 0, total_attempt_usd: null, recorded_attempts: emptyConsumption, source: 'terminal_cost_receipt' },
  missing: [], truncated: false, provenance: 'Public records',
};
function Scope({ sessionId, repo }: { sessionId: string; repo: string }) {
  const diagnostic = useOperationalDiagnostic({ sessionId, repo });
  return <output>{diagnostic ? 'Scoped failure' : 'Healthy'}</output>;
}
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'X-Correlation-Id': 'evidence-A' } });
}
afterEach(() => { cleanup(); resetDiagnosticBus(); vi.unstubAllGlobals(); Reflect.deleteProperty(window, 'harnessIPC'); });

it('parses typed unavailable locally through fetch without poisoning the active view', async () => {
  vi.stubGlobal('fetch', withEndpointDiscovery(vi.fn(async () => response(unavailable))));
  render(<><Scope sessionId="A" repo="/A" /><JobEvidence {...selection} /></>);
  fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
  expect(await screen.findByText(/Evidence is unavailable/)).toBeInTheDocument();
  expect(screen.getByText('Healthy')).toBeInTheDocument();
  expect(getActiveDiagnostic()).toBeNull();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
});

it.each([401, 403, 404, 503])('keeps real HTTP %i operational and scoped', async status => {
  vi.stubGlobal('fetch', withEndpointDiscovery(vi.fn(async () => response({ error: 'Request failed' }, status))));
  await expect(fetchJobEvidence(selection)).rejects.toMatchObject({ status });
  expect(getActiveDiagnostic()).toMatchObject({ sessionId: 'A', repo: '/A', severity: 'error' });
});

it('keeps network failure operational', async () => {
  vi.stubGlobal('fetch', withEndpointDiscovery(async () => { throw new Error('network down'); }));
  await expect(fetchJobEvidence(selection)).rejects.toThrow('network down');
  expect(getActiveDiagnostic()).toMatchObject({ sessionId: 'A', repo: '/A' });
});

it.each(['web', 'desktop'])('captures request scope before a deferred %s failure and session switch', async mode => {
  let release: () => void = () => {};
  const held = new Promise<void>(resolve => { release = resolve; });
  const started = vi.fn();
  if (mode === 'web') vi.stubGlobal('fetch', withEndpointDiscovery(async () => { started(); await held; return response({ error: 'Store unavailable' }, 503); }));
  else Object.defineProperty(window, 'harnessIPC', { configurable: true, value: { endpointHeaders: true, requestJSON: withDesktopEndpointDiscovery(async () => {
    started();
    await held;
    return { kind: 'response', status: 503, text: '{"error":"Store unavailable"}', correlationId: 'evidence-A' };
  }) } });
  const mutableSelection = { ...selection };
  const view = render(<Scope sessionId="A" repo="/A" />);
  const pending = fetchJobEvidence(mutableSelection);
  await waitFor(() => expect(started).toHaveBeenCalledOnce());
  mutableSelection.sessionId = 'B';
  mutableSelection.repo = '/B';
  view.rerender(<Scope sessionId="B" repo="/B" />);
  await act(async () => { release(); await expect(pending).rejects.toMatchObject({ status: 503 }); });
  expect(getActiveDiagnostic()).toMatchObject({ sessionId: 'A', repo: '/A', correlationId: 'evidence-A' });
  expect(screen.getByText('Healthy')).toBeInTheDocument();
  view.rerender(<Scope sessionId="A" repo="/A" />);
  expect(screen.getByText('Scoped failure')).toBeInTheDocument();
});

it('retries in place and shows failed gates separately from lifecycle and zero cost', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(unavailable)).mockResolvedValueOnce(response(data));
  vi.stubGlobal('fetch', withEndpointDiscovery(fetch));
  render(<JobEvidence {...selection} />);
  const toggle = screen.getByRole('button', { name: 'Evidence' });
  fireEvent.click(toggle);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Recorded checks failed: 1');
  expect(screen.getByText('Job: completed')).toBeInTheDocument();
  expect(screen.getByText('Selected delivery cost: $0.000000')).toBeInTheDocument();
  expect(screen.getByText(/No attempts recorded/)).toBeVisible();
  expect(screen.getByText(/task link missing/)).toBeVisible();
  const summary = screen.getByText('Record details');
  expect(summary.tagName).toBe('SUMMARY');
  expect(summary.parentElement?.tagName).toBe('DETAILS');
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  expect(document.getElementById(toggle.getAttribute('aria-controls') || '')).toContainElement(summary);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('fences a retry response after closing and reopening', async () => {
  let release: (value: Response) => void = () => {};
  const held = new Promise<Response>(resolve => { release = resolve; });
  const fetch = vi.fn().mockResolvedValueOnce(response(unavailable)).mockReturnValueOnce(held).mockResolvedValueOnce(response(data));
  vi.stubGlobal('fetch', withEndpointDiscovery(fetch));
  render(<JobEvidence {...selection} />);
  const toggle = screen.getByRole('button', { name: 'Evidence' });
  fireEvent.click(toggle);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  expect(screen.getByRole('status')).toHaveTextContent('Loading');
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  fireEvent.click(toggle);
  fireEvent.click(toggle);
  expect(await screen.findByRole('alert')).toHaveTextContent('Recorded checks failed');
  await act(async () => { release(response(unavailable)); });
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.queryByText(/Evidence is unavailable/)).not.toBeInTheDocument();
});

it('fences old component results after selecting a new session', async () => {
  let release: (value: Response) => void = () => {};
  const held = new Promise<Response>(resolve => { release = resolve; });
  const fetch = vi.fn().mockReturnValueOnce(held).mockResolvedValueOnce(response(data));
  vi.stubGlobal('fetch', withEndpointDiscovery(fetch));
  const view = render(<JobEvidence {...selection} />);
  fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  view.rerender(<JobEvidence {...selection} sessionId="B" />);
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  await act(async () => { release(response(unavailable)); });
  expect(screen.getByRole('alert')).toBeInTheDocument();
});
