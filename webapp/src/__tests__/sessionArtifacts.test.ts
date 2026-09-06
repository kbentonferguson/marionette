import { afterEach, expect, it, vi } from 'vitest';
import type { Job } from '../lib/api';
import { fetchJobArtifacts } from '../lib/jobArtifacts';
import { gatherSessionArtifacts } from '../components/conversation/sessionArtifacts';
vi.mock('../lib/jobArtifacts', async importOriginal => ({
  ...await importOriginal<typeof import('../lib/jobArtifacts')>(), fetchJobArtifacts: vi.fn(),
}));
afterEach(() => vi.resetAllMocks());
const job: Job = { id: 'job_one', goal: 'Review', status: 'completed', source: 'harness',
  session_id: 'A', job_ref: { job_id: 'job_one', state_id: 'state_a' } };
const opts = { display: [{ type: 'card', result: { artifacts: [{ type: 'note', headline: 'display' }] } }],
  jobIds: [job.id], jobs: [job], repo: '/A', sessionId: 'A', stillCurrent: () => true };
it('keeps the display-only path synchronous', () => {
  expect(gatherSessionArtifacts({ ...opts, jobIds: [] })).toEqual([{ type: 'note', headline: 'display' }]);
  expect(fetchJobArtifacts).not.toHaveBeenCalled();
});
it('uses the captured live reference and distinguishes genuine loaded empty', async () => {
  vi.mocked(fetchJobArtifacts).mockResolvedValue([]);
  expect(await gatherSessionArtifacts(opts)).toEqual([{ type: 'note', headline: 'display' }]);
  expect(fetchJobArtifacts).toHaveBeenCalledWith({ job_ref: job.job_ref, source: 'harness', repo: '/A', session_id: 'A' });
});
it.each([
  { jobs: [] },
  { jobs: [{ ...job, job_ref: undefined }] },
  { jobs: [job, { ...job, source: 'cli', job_ref: { job_id: job.id, state_id: 'state_b' } }] },
  { sessionId: 'B' },
  { jobs: [{ ...job, cross_project: true }] },
])('labels missing, ambiguous or foreign selections unavailable', async override => {
  const result = await gatherSessionArtifacts({ ...opts, ...override });
  expect(result.at(-1)?.headline).toContain('Artifact preview unavailable');
  expect(fetchJobArtifacts).not.toHaveBeenCalled();
});
it('does not cache failed reads as loaded empty and permits another gather', async () => {
  vi.mocked(fetchJobArtifacts).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([{ type: 'note', headline: 'recovered' }]);
  expect((await gatherSessionArtifacts(opts)).at(-1)?.headline).toContain('unavailable');
  expect((await gatherSessionArtifacts(opts)).at(-1)?.headline).toBe('recovered');
});
it('fences old responses and does not start already stale reads', async () => {
  let release: (value: []) => void = () => {};
  vi.mocked(fetchJobArtifacts).mockReturnValue(new Promise(resolve => { release = resolve; }));
  let current = true;
  const pending = gatherSessionArtifacts({ ...opts, stillCurrent: () => current });
  current = false;
  release([]);
  expect(await pending).toEqual([]);
  expect(gatherSessionArtifacts({ ...opts, stillCurrent: () => false })).toEqual([]);
  expect(fetchJobArtifacts).toHaveBeenCalledTimes(1);
});
