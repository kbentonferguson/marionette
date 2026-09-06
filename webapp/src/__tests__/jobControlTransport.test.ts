import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { JobControlSelection } from '../lib/jobControl';
import { endpointDescriptor } from './endpointFixture';

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllGlobals());
it('captures the cancellation selection before endpoint discovery awaits', async () => {
  let release: (response: Response) => void = () => {};
  const handshake = new Promise<Response>(resolve => { release = resolve; });
  const bodies: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    if (path === '/api/endpoint') return handshake;
    bodies.push(JSON.parse(options.body));
    return Response.json({ ok: true });
  }));
  const { api } = await import('../lib/api');
  const selection: JobControlSelection = { version: 1, source: 'cli', repo: '/A', session_id: 'A',
    job_ref: { job_id: 'same', state_id: 'state_a' } };
  const pending = api.swarmCancel(selection);
  selection.repo = '/B'; selection.session_id = 'B'; selection.job_ref.state_id = 'state_b';
  release(Response.json(endpointDescriptor));
  await pending;
  expect(bodies).toEqual([{ selection: { version: 1, source: 'cli', repo: '/A', session_id: 'A',
    job_ref: { job_id: 'same', state_id: 'state_a' } } }]);
});
