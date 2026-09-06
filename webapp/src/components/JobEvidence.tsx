import { useEffect, useId, useState } from 'react';
import { fetchJobEvidence, type EvidenceSelection, type JobEvidenceData, type ConsumptionMetric } from '../lib/jobEvidence';

type EvidenceState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'unavailable' }
  | { kind: 'ready'; data: JobEvidenceData };

function dollars(value: number | null, status?: ConsumptionMetric['status']) {
  if (value === null) return 'unknown';
  return `$${value.toFixed(6)}${status ? ` (${status})` : ''}`;
}

function RecordedCost({ label, metric }: { label: string; metric: ConsumptionMetric }) {
  return <div className="tabular-nums">
    <p>{label} subtotal: {dollars(metric.known_subtotal, metric.status)}.</p>
    <p>{metric.known_attempts} known {metric.known_attempts === 1 ? 'attempt' : 'attempts'}; {metric.unknown_attempts} unknown; {metric.estimated_attempts} estimated; {metric.conflicting_attempts} conflicting.</p>
  </div>;
}

function EvidenceContent(selection: EvidenceSelection) {
  const [state, setState] = useState<EvidenceState>({ kind: 'loading' });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let current = true;
    fetchJobEvidence(selection).then(result => {
      if (current) setState('code' in result
        ? { kind: 'unavailable' } : { kind: 'ready', data: result });
    }).catch(() => {
      if (current) setState({ kind: 'error' });
    });
    return () => { current = false; };
  }, [selection.jobId, selection.stateId, selection.sessionId, selection.repo, selection.source, revision]);
  if (state.kind === 'loading') return <p role="status">Loading evidence...</p>;
  if (state.kind === 'error' || state.kind === 'unavailable') return (
    <div className="flex flex-col gap-2">
      <p role="status">{state.kind === 'unavailable'
        ? 'Evidence is unavailable for this job in the active workspace and session.'
        : 'Evidence could not be read. Try again.'}</p>
      <button type="button" className="text-txt py-2 focus-visible:outline" onClick={() => {
        setState({ kind: 'loading' });
        setRevision(value => value + 1);
      }}>Retry</button>
    </div>
  );
  const data = state.data;
  const checks = data.artifacts.filter(artifact => artifact.check_result !== 'unavailable');
  const failures = checks.filter(artifact => artifact.check_result === 'failed');
  return (
    <div className="flex flex-col gap-3 break-words">
      {failures.length > 0 && <p role="alert" className="text-txt font-semibold">Recorded checks failed: {failures.length}</p>}
      <section aria-label="Lifecycle">
        <h4 className="text-txt font-semibold">Lifecycle</h4>
        <p>Job: {data.status}</p>
        <ul>{data.tasks.map((task, index) => <li key={task.id}>Task {index + 1}: {task.status}; task attempt counter: {task.attempt_count}</li>)}</ul>
        <p className="text-faint">Request, turn and action links unavailable.</p>
      </section>
      <section aria-label="Attempts">
        <h4 className="text-txt font-semibold">Attempts</h4>
        <p>{data.attempts.length} of {data.totals.attempts} recorded attempts shown. Invocation coverage is unverified.</p>
        {data.attempts.length === 0 && <p>No attempts recorded; this does not prove no execution occurred.</p>}
        <ul className="mt-2 flex flex-col gap-2">{data.attempts.map((attempt, index) => <li key={attempt.attempt_id} className="rounded border border-edge p-2">
          <p className="text-txt">Attempt {index + 1} · {attempt.provider ?? 'provider unknown'} / {attempt.model ?? 'model unknown'}</p>
          <p className="tabular-nums">API: {dollars(attempt.consumption.api_cost_usd.total, attempt.consumption.api_cost_usd.status)}. Plan marginal: {dollars(attempt.consumption.plan_marginal_cost_usd.total, attempt.consumption.plan_marginal_cost_usd.status)}.</p>
          <p>Outcome unavailable.</p>
          <details>
            <summary className="cursor-pointer py-1 focus-visible:outline">Attempt references</summary>
            <dl className="break-all">
              <dt>Attempt</dt><dd className="font-mono">{attempt.attempt_id}</dd>
              <dt>Run</dt><dd className="font-mono">{attempt.run_id}</dd>
              <dt>Task</dt><dd className="font-mono">{attempt.task_id}</dd>
              <dt>Adapter</dt><dd>{attempt.adapter}</dd>
              <dt>API-equivalent estimate</dt><dd>{dollars(attempt.consumption.api_equivalent_cost_usd.total)}; not spend</dd>
            </dl>
          </details>
        </li>)}</ul>
      </section>
      <section aria-label="Checks">
        <h4 className="text-txt font-semibold">Checks</h4>
        {checks.length === 0 ? <p>No check results recorded.</p> :
          <ul>{checks.map((check, index) => <li key={check.id}>{check.type} {index + 1}: {check.check_result}</li>)}</ul>}
      </section>
      <section aria-label="Artifacts">
        <h4 className="text-txt font-semibold">Artifacts</h4>
        <p>{data.artifacts.length === 0 ? 'No artifacts recorded.' : `${data.artifacts.length} recorded; contents not independently verified.`}</p>
        <ul>{data.artifacts.map((artifact, index) => <li key={artifact.id}>{artifact.type} {index + 1}{artifact.task_id === null ? ' — task link missing' : ''}</li>)}</ul>
      </section>
      <section aria-label="Cost">
        <h4 className="text-txt font-semibold">Cost</h4>
        <p className="tabular-nums">Selected delivery cost: {dollars(data.cost.selected_usd)}</p>
        <p className="text-faint">Selected task usage only; retries may add cost.</p>
        <p>All-attempt spend: unknown; invocation coverage is unverified.</p>
        <RecordedCost label="Recorded API" metric={data.cost.recorded_attempts.api_cost_usd} />
        <RecordedCost label="Recorded plan marginal" metric={data.cost.recorded_attempts.plan_marginal_cost_usd} />
        <details>
          <summary className="cursor-pointer py-1 focus-visible:outline">How costs are counted</summary>
          <p>Subtotals cover all recorded attempts, including hidden rows. Equal snapshots reconcile; conflicting values stay unknown. Each cost basis needs explicit evidence. Estimated counts are included in known counts. API-equivalent estimates are not spend. Reads are non-atomic and do not certify complete telemetry.</p>
        </details>
      </section>
      <p>Records shown: {data.tasks.length} of {data.totals.tasks} tasks; {data.artifacts.length} of {data.totals.artifacts} artifacts.</p>
      {data.truncated && <p>Showing at most 100 records per kind. Evidence is incomplete.</p>}
      <details>
        <summary className="text-txt py-2 cursor-pointer focus-visible:outline">Record details</summary>
        <dl>
          <dt>Job / state</dt><dd className="font-mono">{data.job_ref.job_id} / {data.job_ref.state_id}</dd>
          <dt>Source</dt><dd>{data.source}</dd>
          <dt>Cost source</dt><dd>{data.cost.source === 'terminal_cost_receipt' ? 'Frozen terminal receipt' : 'Unavailable'}</dd>
        </dl>
        <ul>{data.tasks.map((task, index) => <li key={task.id}>Task {index + 1}: <span className="font-mono">{task.id}</span></li>)}</ul>
        <ul>{data.artifacts.map((artifact, index) => <li key={artifact.id}>Artifact {index + 1}: <span className="font-mono">{artifact.id}</span>; task: {artifact.task_id ?? 'link missing'}</li>)}</ul>
        <ul>{data.missing.map(item => <li key={item}>{item}</li>)}</ul>
        <p className="text-faint">{data.provenance}</p>
      </details>
    </div>
  );
}

export default function JobEvidence(selection: EvidenceSelection) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  const identity = JSON.stringify([selection.jobId, selection.stateId, selection.sessionId, selection.repo, selection.source]);
  return (
    <section className="border-t border-edge pt-2 text-xs text-muted" aria-label="Job evidence">
      <button type="button" className="text-txt py-2 focus-visible:outline" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(value => !value)}>Evidence</button>
      <div id={contentId}>{open && <EvidenceContent key={identity} {...selection} />}</div>
    </section>
  );
}
