import type { ExpertMetadata } from '../lib/expertMetadata';
import { expertCheckCounts, expertFindingGroups, expertJobQuality, expertPromptEcho, isExpertFailure } from '../lib/expertOutcomeFacts';

export function ExpertFindings({ expert }: { expert: ExpertMetadata }) {
  const groups = expertFindingGroups(expert);
  const counts = expertCheckCounts(expert);
  const quality = expertJobQuality(expert);
  return <section aria-label="Current evidence" className="min-w-0 space-y-2 text-sm">
    <p className={quality === 'degraded' ? 'text-warn' : quality === 'ok' ? 'text-good' : 'text-muted'}>Evidence quality: {quality === 'ok' ? 'trustworthy' : quality}.</p>
    <p>Recorded checks passed: {counts.passed}</p><p>Recorded checks failed: {counts.failed}</p>
    {counts.unverified > 0 && <p>Recorded checks unverified: {counts.unverified}</p>}
    <p>Task coverage: {expert.coverage.tasks}; evidence coverage: {expert.coverage.artifacts}. Lifecycle is separate from evidence quality.</p>
    {(expert.kind !== 'available' || expert.coverage.artifacts !== 'complete' || expert.coverage.tasks !== 'complete') && <p role="status">Incomplete evidence coverage; additional evidence may be missing.{expert.reason ? ` ${expert.reason}` : ''}</p>}
    <details open className="min-w-0">
      <summary className="min-h-11 cursor-pointer focus-visible:outline focus-visible:outline-accent">Findings ({groups.length})</summary>
      {groups.length === 0 && <p>{expert.kind === 'available' && expert.coverage.artifacts === 'complete' ? 'No findings recorded.' : 'No findings loaded.'}</p>}
      {groups.map(({ key, artifacts }) => <details key={key} data-artifact-ids={artifacts.map(a => a.id).join(' ')} data-finding-id={artifacts[0]?.id}
        className="min-w-0 rounded border border-edge p-2">
        <summary className="min-h-11 cursor-pointer whitespace-pre-wrap break-words [overflow-wrap:anywhere] focus-visible:outline focus-visible:outline-accent">
          {artifacts[0]?.headline || artifacts[0]?.type}{artifacts.length > 1 && <span className="text-muted"> x{artifacts.length}</span>}
          {artifacts.some(a => a.type.toUpperCase() === 'FINDING' && expertPromptEcho(a.headline)) && <span className="text-warn"> looks like prompt echo</span>}
        </summary>
        {artifacts.map(a => <div key={a.id} className="max-h-72 overflow-auto whitespace-pre-wrap break-words [overflow-wrap:anywhere] border-t border-edge py-2">
          <p>{a.type} / {a.id} · {a.task_id === null ? 'Job-level evidence' : `Task ${a.task_id}`}</p>
          <p className={isExpertFailure(a) ? 'text-warn' : 'text-muted'}>Check: {a.check_result}</p>
          {a.result && <p>Result: {a.result}</p>}{a.failure && <p>Failure: {a.failure}</p>}
          {a.detail && <p>{a.detail}</p>}{a.confidence !== null && <p>Confidence: {Math.round(a.confidence * 100)}%</p>}
        </div>)}
      </details>)}
    </details>
  </section>;
}
