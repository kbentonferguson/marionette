import { useState } from 'react';
import type { ReactNode } from 'react';
import type { ExpertArtifact, ExpertMetadata, ExpertTask } from '../lib/expertMetadata';
import { expertTaskOutcome, expertTaskFailures } from '../lib/expertOutcomeFacts';
import type { MetadataTask } from '../lib/jobMetadata';
import { expertWorkerModel, expertWorkerSlot, resolveExpertRouting } from '../lib/expertRoutingFacts';
import WorkerInstruction from './WorkerInstruction';

export type ExpertWorkerUsageProps = { task: ExpertTask; route?: ExpertArtifact };
export type ExpertWorkersProps = { expert: ExpertMetadata; tasks: MetadataTask[]; headerModel?: string;
  renderUsage?: (props: ExpertWorkerUsageProps) => ReactNode };
const wrap = 'min-w-0 break-words [overflow-wrap:anywhere]';
const dollars = (value: number) => `$${value.toLocaleString(undefined, { maximumFractionDigits: 8 })}`;

export function ExpertWorkerUsage({ task, route }: ExpertWorkerUsageProps) {
  const [expanded, setExpanded] = useState(false);
  const usage = task.usage;
  const measured = usage.estimated === false && ['provider', 'provider_reported', 'provider_attested', 'measured', 'actual'].includes(usage.cost_provenance ?? '');
  const plan = /plan.billed|subscription/i.test(route?.detail ?? '');
  const cost = usage.est_cost_usd === null ? null : usage.est_cost_usd === 0 && plan && !measured
    ? 'Plan-billed; provider cost unknown' : `${measured ? 'Measured' : usage.estimated === true ? 'Estimated' : 'Reported'} cost: ${dollars(usage.est_cost_usd)}`;
  return <div className={wrap}><button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="min-h-11">Worker usage</button>
    {expanded && <div><p>Input tokens: {usage.tokens_in?.toLocaleString() ?? 'unknown'} · Output tokens: {usage.tokens_out?.toLocaleString() ?? 'unknown'}</p>
      <p>{cost ?? 'Cost unknown'}</p>{usage.cost_provenance && <p>Source: {usage.cost_provenance}</p>}</div>}
  </div>;
}
function RouteFacts({ route }: { route: ExpertArtifact }) {
  return <div className={wrap}>
    {route.policy && <p>Policy: {route.policy}</p>}{route.provider && <p>Provider: {route.provider}</p>}
    {route.adapter && <p>Routing adapter: {route.adapter}</p>}{route.detail && <p>{route.detail}</p>}
    {route.est_cost_usd !== null && <p>Route forecast: {dollars(route.est_cost_usd)} (estimate)</p>}
    {route.rejected.length > 0 && <div><p>Rejected alternatives</p>{route.rejected.map((item, index) => <p key={index}>{item.model}: {item.reason}</p>)}</div>}
  </div>;
}
function Worker({ expert, task, reference, route, renderUsage }: {
  expert: ExpertMetadata; task: ExpertTask; reference: MetadataTask; route?: ExpertArtifact;
  renderUsage?: ExpertWorkersProps['renderUsage'];
}) {
  const [expanded, setExpanded] = useState(false);
  const quality = expertTaskOutcome(expert, task.id), model = expertWorkerModel(task, route);
  const slot = expertWorkerSlot(task, reference.status, route);
  const failures = expertTaskFailures(expert, task.id);
  return <div data-task-id={task.id} data-quality={failures.length ? 'degraded' : quality} className="min-w-0 border-b border-edge py-1">
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}
      className="min-h-11 w-full text-left grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
      <span className={wrap}>{task.role || task.id}<span className="block text-muted">{reference.status ?? 'unknown'} · {failures.length ? 'degraded' : quality}</span></span>
      <span data-worker-model-slot aria-label={model ? `Model: ${model}` : slot} title={model ? `Model: ${model}` : slot} className={wrap}>{slot}</span>
    </button>
    {expanded && <div className={wrap}><p>Task {task.id} · Adapter: {task.adapter || 'unknown'}</p>
      <WorkerInstruction key={task.id} text={task.instruction} truncated={task.instruction_truncated} />
      {route && <RouteFacts route={route} />}
      {renderUsage ? renderUsage({ task, route }) : <ExpertWorkerUsage task={task} route={route} />}
      {failures.map(artifact => <div key={artifact.id}><p>{artifact.headline}</p>{artifact.failure && <p>{artifact.failure}</p>}{artifact.detail && <p className="whitespace-pre-wrap">{artifact.detail}</p>}</div>)}
    </div>}
  </div>;
}
function UnmatchedRoutes({ routes }: { routes: ExpertArtifact[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!routes.length) return null;
  return <div className={wrap}><button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="min-h-11 text-left break-words [overflow-wrap:anywhere]">
    Unmatched routing · {routes.length === 1 ? routes[0].model || '1 route' : `${routes.length} routes`} · no matching worker
  </button>{expanded && routes.map(route => <div key={route.id}><p>{route.model}</p><RouteFacts route={route} /></div>)}</div>;
}
export function ExpertWorkers({ expert, tasks, headerModel, renderUsage }: ExpertWorkersProps) {
  const { routingForTask, unmatched } = resolveExpertRouting(expert, headerModel);
  return <div className="min-w-0"><p>Workers ({tasks.length})</p>
    {expert.reason && <p>{expert.reason}</p>}
    {tasks.map(reference => {
      const task = expert.tasks.find(item => item.id === reference.id);
      return task ? <Worker key={task.id} expert={expert} task={task} reference={reference} route={routingForTask.get(task.id)} renderUsage={renderUsage} />
        : <p key={reference.id}>{reference.id} · {reference.status} · Current identity unavailable</p>;
    })}
    <UnmatchedRoutes routes={unmatched} />
  </div>;
}
