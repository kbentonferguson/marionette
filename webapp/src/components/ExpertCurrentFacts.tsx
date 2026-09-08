import { ExpertWorkers as Workers } from './ExpertWorkerDetails';
import type { ExpertWorkersProps } from './ExpertWorkerDetails';
import { ExpertWorkerUsage } from './ExpertUsageDetails';
export { ExpertCost, ExpertWorkerUsage } from './ExpertUsageDetails';
export { ExpertFindings } from './ExpertEvidenceDetails';
export function ExpertWorkers(props: ExpertWorkersProps) {
  return <Workers {...props} renderUsage={({ task, route }) => <ExpertWorkerUsage usage={task.usage} planBilled={/plan.billed|subscription/i.test(route?.detail ?? '')} />} />;
}
