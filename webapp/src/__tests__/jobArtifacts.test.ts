import { afterEach, expect, it, vi } from 'vitest';
import { getJSON } from '../lib/transport';
import { fetchJobArtifacts, jobArtifactKey } from '../lib/jobArtifacts';
vi.mock('../lib/transport', () => ({ getJSON: vi.fn() }));
afterEach(() => vi.resetAllMocks());
const selection = { job_ref: { job_id: 'job_one', state_id: 'state_one' },
  source: 'harness', session_id: 'session-one', repo: '/repo' };
it('binds captured transport scope and rejects wrong refs', async () => {
  vi.mocked(getJSON).mockResolvedValue({ ...selection, job_ref: { ...selection.job_ref, state_id: 'state_other' }, artifacts: [] });
  await expect(fetchJobArtifacts(selection)).rejects.toThrow('unavailable');
  expect(getJSON).toHaveBeenCalledWith(expect.stringContaining('/api/jobs/artifacts/v1?'), { sessionId: 'session-one', repo: '/repo' });
});
it('does not turn transport errors into empty artifacts', async () => {
  vi.mocked(getJSON).mockRejectedValue(new Error('HTTP 503'));
  await expect(fetchJobArtifacts(selection)).rejects.toThrow('HTTP 503');
});
it('keys every source and context field', () => {
  for (const other of [{ ...selection, source: 'cli' }, { ...selection, repo: '/other' },
    { ...selection, session_id: 'other' }, { ...selection, job_ref: { ...selection.job_ref, state_id: 'other' } }]) {
    expect(jobArtifactKey(other)).not.toBe(jobArtifactKey(selection));
  }
});
