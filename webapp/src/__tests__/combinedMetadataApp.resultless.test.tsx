import { act, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RESULT_RECOVERY_DRAIN_LIMIT } from '../components/conversation/swarmPoll';

afterEach(() => { vi.unstubAllGlobals(); Reflect.deleteProperty(window, 'harnessIPC'); });

const bodyHas = (re: RegExp) => (document.body.innerHTML.match(re) ?? []).length;

// An interrupted run_parallel worker is terminal on the backend but never
// produces a swarm_result card. The poll must stop holding Still working…
// once the bounded recovery drains ran empty, instead of looping forever.
it('settles a terminal job that never delivers a result card and stops draining', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
  document.body.innerHTML = '<div id="root"></div>';
  const fixtureModule = await import('./combinedMetadataApp');
  fixtureModule.fixture.total = 1;
  fixtureModule.fixture.pmLifecycle = 'completed';
  fixtureModule.appScenario.display = [{ type: 'swarm_pending', job_ids: ['job_1'], objective: 'Interrupted implement wave', status: 'running' }];
  fixtureModule.appScenario.resultBatches = [];
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 100)); });
  await waitFor(() => expect(bodyHas(/Still working/g)).toBeGreaterThan(0), { timeout: 8000 });
  const drains = () => fixtureModule.appScenario.calls.filter(p => p === '/api/session/swarm-results').length;
  // Each poll tick spends one results call plus one recovery drain.
  await waitFor(() => expect(drains()).toBeGreaterThanOrEqual(2 * RESULT_RECOVERY_DRAIN_LIMIT), { timeout: 60000 });
  await waitFor(() => expect(bodyHas(/Still working/g)).toBe(0), { timeout: 20000 });
  const settledAt = drains();
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 5000)); });
  expect(drains()).toBe(settledAt);
  act(() => fixtureModule.appRoot.unmount());
}, 120000);
