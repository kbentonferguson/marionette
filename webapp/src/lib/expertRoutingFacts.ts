import type { ExpertArtifact, ExpertHeader, ExpertMetadata, ExpertTask } from './expertMetadata';
import { displayModelId, isEngineOnlyModelId, modelIdsEqual, stripEnginePrefixes } from './modelIdentity';

export function expertRouteRank(route: ExpertArtifact): number {
  return route.created_by === 'router-escalation' ? 3 : route.created_by === 'router-fallback' ? 2 : route.created_by === 'router' ? 1 : 0;
}
const normalized = (value: string | null) => (value ?? '').trim().toLowerCase();
function laterRoute(candidate: ExpertArtifact, previous: ExpertArtifact): boolean {
  const rank = expertRouteRank(candidate) - expertRouteRank(previous);
  if (rank) return rank > 0;
  const nextTime = Date.parse(candidate.created_at ?? ''), previousTime = Date.parse(previous.created_at ?? '');
  return Number.isFinite(nextTime) && Number.isFinite(previousTime) && nextTime !== previousTime ? nextTime > previousTime : true;
}
function selectRoute(routes: Map<string, ExpertArtifact>, key: string, route: ExpertArtifact) {
  const previous = routes.get(key);
  if (!previous || laterRoute(route, previous)) routes.set(key, route);
}

export function isExpertEngineStamp(value: string): boolean {
  return isEngineOnlyModelId(value) || /^(codex|cursor|claude|claude-code|default|auto)$/i.test(stripEnginePrefixes(value));
}

export function expertWorkerModel(task: ExpertTask, route?: ExpertArtifact): string | null {
  for (const candidate of [route?.model, task.model, task.adapter]) {
    if (candidate?.trim() && !isExpertEngineStamp(candidate)) return displayModelId(candidate);
  }
  return null;
}

/** Only current selected facts enter this resolver; explicit task ownership is never reassigned. */
export function resolveExpertRouting(expert: ExpertMetadata, headerModel?: string): {
  routingForTask: Map<string, ExpertArtifact>; unmatched: ExpertArtifact[];
} {
  const routingForTask = new Map<string, ExpertArtifact>();
  const residual = new Map<string, ExpertArtifact>();
  for (const route of expert.artifacts) {
    if (route.type.toUpperCase() !== 'ROUTING') continue;
    const role = normalized(route.role);
    const matches = route.task_id
      ? expert.tasks.filter(task => task.id === route.task_id)
      : role && expert.coverage.tasks === 'complete'
        ? expert.tasks.filter(task => normalized(task.role) === role) : [];
    if (matches.length === 1) selectRoute(routingForTask, matches[0].id, route);
    else {
      const key = route.task_id ? `task:${route.task_id}` : role ? `role:${role}` : `model:${normalized(stripEnginePrefixes(route.model ?? ''))}`;
      selectRoute(residual, key, route);
    }
  }
  const remaining = expert.tasks.filter(task => !routingForTask.has(task.id));
  const unscoped = [...residual.entries()].filter(([, route]) => !route.task_id && !normalized(route.role));
  // One remaining worker and one unscoped decision group is the only safe residual association.
  if (expert.coverage.tasks === 'complete' && remaining.length === 1 && unscoped.length === 1) {
    const [key, route] = unscoped[0];
    routingForTask.set(remaining[0].id, route);
    residual.delete(key);
  }
  const unmatched = [...residual.values()].filter(route => {
    if (!headerModel || !route.model || !modelIdsEqual(headerModel, route.model)) return true;
    return route.policy === 'explicit_pin' || expertRouteRank(route) > 1 || route.rejected.length > 0;
  });
  return { routingForTask, unmatched };
}

export function expertWorkerSlot(task: ExpertTask, status: string | null, route?: ExpertArtifact): string {
  const model = expertWorkerModel(task, route);
  if (model) return model;
  return /^(running|in_progress|queued|pending|registered|started|stitching)$/i.test(status ?? '') && !route?.model?.trim()
    ? 'routing…' : 'No model recorded';
}

/** A zero-worker job may own an explicitly unscoped final routing decision. */
export function expertJobModel(expert: ExpertMetadata): string | null {
  if (expert.kind === 'unavailable' || expert.coverage.tasks !== 'complete' || expert.tasks.length) return null;
  let final: ExpertArtifact | undefined;
  for (const route of expert.artifacts) {
    if (route.type.toUpperCase() !== 'ROUTING' || route.task_id || route.role?.trim() || !route.model || isExpertEngineStamp(route.model)) continue;
    if (!final || laterRoute(route, final)) final = route;
  }
  return final?.model ? displayModelId(final.model) : null;
}

export function expertHeaderModel(header: ExpertHeader | null | undefined): string | null {
  return header?.model && header.model_provenance && header.model_provenance !== 'unknown' && !isExpertEngineStamp(header.model)
    ? displayModelId(header.model) : null;
}
