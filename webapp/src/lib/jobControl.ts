import type { Job } from './api';
import { selectJobRef } from './jobArtifacts';

export type JobControlSelection = {
  version: 1;
  repo: string;
  session_id: string;
} & (
  | { source: 'harness' | 'cli'; job_ref: { job_id: string; state_id: string } }
  | { source: 'local'; job_ref: { job_id: string; state_id: null } }
);

export function selectJobControl(job: Job, repo: string, sessionId: string): JobControlSelection | null {
  if (job.id.startsWith('local-') && !job.job_ref && !job.cross_project
      && (job.source === 'harness' || job.source === 'local')
      && repo && sessionId && job.session_id === sessionId) {
    return { version: 1, source: 'local', repo, session_id: sessionId,
      job_ref: { job_id: job.id, state_id: null } };
  }
  const selection = selectJobRef(job, repo, sessionId);
  if (!selection || (selection.source !== 'harness' && selection.source !== 'cli')) return null;
  return { ...selection, version: 1, source: selection.source };
}

export function jobControlKey(job: Job, repo: string, sessionId: string): string {
  return JSON.stringify([1, job.id, job.job_ref?.state_id ?? null, job.source ?? 'harness',
    job.session_id ?? null, job.cwd ?? null, repo, sessionId]);
}
