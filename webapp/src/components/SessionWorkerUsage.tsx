import { useEffect, useState } from 'react';
import { useSharedJobMetadata } from '../lib/jobMetadataContext';
import { sessionWorkerUsage } from '../lib/sessionWorkerUsage';
import { expertDollars } from '../lib/expertEconomicsFacts';

export function SessionWorkerUsage() {
  const { state } = useSharedJobMetadata();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) setNow(Date.now()); }, 1000);
    return () => clearInterval(timer);
  }, []);
  const usage = sessionWorkerUsage(state, Math.max(now, ...Object.values(state.headers).map(h => h.refreshedAt)));
  return <div aria-label="Session worker usage" className="min-w-0 px-2 text-xs text-muted break-words [overflow-wrap:anywhere]">
    <p>Session PM workers · {usage.kind === 'complete' ? 'complete known-store coverage' : 'partial coverage'}</p>
    {usage.kind === 'partial' ? <p>{usage.reason}. Headers retry automatically.</p> : <>
      <p>{usage.jobs} jobs · {usage.workers} workers · {usage.tokens === null ? 'Tokens unknown' : `${usage.tokens.toLocaleString('en-US')} tokens`} · {usage.cost === null ? 'Cost unknown' : expertDollars(usage.cost)}</p>
      {usage.measured !== null && <span>Measured {expertDollars(usage.measured)} </span>}
      {usage.estimated !== null && <span>Estimated {expertDollars(usage.estimated)} </span>}
      {usage.routing !== null && <p>Estimated routing savings {expertDollars(usage.routing)}</p>}
      {usage.cache !== null && <p>Estimated cache savings {expertDollars(usage.cache)}</p>}
      {usage.compaction !== null && <p>Estimated compaction savings {expertDollars(usage.compaction)}</p>}
    </>}
    <p>Native, pilot and legacy unowned usage excluded. Known session membership and current worker headers only.</p>
  </div>;
}
