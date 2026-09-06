import { afterEach, expect, it, vi } from 'vitest';
import { getJSON } from '../lib/transport';
import { fetchJobEvidence } from '../lib/jobEvidence';
vi.mock('../lib/transport', () => ({ getJSON: vi.fn() }));
afterEach(() => vi.resetAllMocks());
const selection = { jobId: 'job_a', stateId: 'state_a', source: 'harness', sessionId: 'A', repo: '/A' };
it('does not request evidence with an absent selected state', async () => {
  expect(await fetchJobEvidence({ ...selection, stateId: undefined })).toMatchObject({ code: 'job_evidence_unavailable' });
  expect(getJSON).not.toHaveBeenCalled();
});
it('refuses a colliding job returned from another state', async () => {
  vi.mocked(getJSON).mockResolvedValue({ job_ref: { job_id: 'job_a', state_id: 'state_b' }, source: 'harness' });
  expect(await fetchJobEvidence(selection)).toMatchObject({ code: 'job_evidence_unavailable' });
  expect(getJSON).toHaveBeenCalledWith(expect.stringContaining('state_id=state_a'), { sessionId: 'A', repo: '/A' });
});
