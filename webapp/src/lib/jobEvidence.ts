import { getJSON } from './transport';

export type ConsumptionMetric = {
  total: number | null; known_subtotal: number | null;
  status: 'unknown' | 'partial' | 'measured' | 'estimated';
  known_attempts: number; unknown_attempts: number;
  estimated_attempts: number; conflicting_attempts: number;
};

export type ConsumptionMetrics = {
  tokens_in: ConsumptionMetric; tokens_out: ConsumptionMetric;
  cache_read_tokens: ConsumptionMetric; cache_write_tokens: ConsumptionMetric;
  api_cost_usd: ConsumptionMetric; plan_marginal_cost_usd: ConsumptionMetric;
  api_equivalent_cost_usd: ConsumptionMetric;
};

export type JobEvidenceData = {
  job_ref: { job_id: string; state_id: string };
  source: 'harness';
  status: string;
  links: { request: null; turn: null; action: null; attempts: 'recorded' | 'unavailable' };
  tasks: { id: string; status: string; attempt_count: number }[];
  artifacts: {
    id: string; task_id: string | null; type: string; presence: 'recorded';
    check_result: 'passed' | 'failed' | 'unavailable';
  }[];
  attempts: {
    attempt_id: string; run_id: string; task_id: string; adapter: string;
    provider: string | null; model: string | null; outcome: 'unavailable';
    consumption: ConsumptionMetrics;
  }[];
  attempt_coverage: 'unverified';
  totals: { tasks: number; artifacts: number; attempts: number };
  truncated: boolean;
  cost: { selected_usd: number | null; total_attempt_usd: null; source: 'terminal_cost_receipt' | 'unavailable';
    recorded_attempts: ConsumptionMetrics;
  };
  missing: string[];
  provenance: string;
};

export type EvidenceSelection = { jobId: string; stateId?: string; sessionId: string; repo: string; source: string };

export type JobEvidenceUnavailable = { code: 'job_evidence_unavailable'; message: string };
export type JobEvidenceResult = JobEvidenceData | JobEvidenceUnavailable;

export async function fetchJobEvidence(selection: EvidenceSelection): Promise<JobEvidenceResult> {
  selection = { ...selection };
  if (!selection.stateId || selection.source !== 'harness' || !selection.repo || !selection.sessionId) {
    return { code: 'job_evidence_unavailable', message: 'Evidence is unavailable for this selection.' };
  }
  const query = new URLSearchParams({
    state_id: selection.stateId, job_id: selection.jobId, session_id: selection.sessionId,
    repo: selection.repo, source: selection.source,
  });
  const result = await getJSON<JobEvidenceResult>(`/api/jobs/evidence?${query}`, {
    sessionId: selection.sessionId, repo: selection.repo,
  });
  if (!('code' in result) && (result.job_ref?.job_id !== selection.jobId
      || result.job_ref.state_id !== selection.stateId || result.source !== selection.source)) {
    return { code: 'job_evidence_unavailable', message: 'Evidence is unavailable for this selection.' };
  }
  return result;
}
