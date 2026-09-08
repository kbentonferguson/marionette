import type { ExpertArtifact, ExpertMetadata } from './expertMetadata';

export function isExpertFailure(artifact: ExpertArtifact): boolean {
  return artifact.check_result === 'failed' || !!artifact.failure?.trim()
    || /^(failed|blocked|error|degraded)$/i.test(artifact.result?.trim() ?? '')
    || artifact.type.toLowerCase() === 'error';
}
export function isExpertCheck(artifact: ExpertArtifact): boolean {
  return /^(verification|gate|check|test)$/i.test(artifact.type);
}
export function expertTaskFailures(expert: ExpertMetadata, taskId: string): ExpertArtifact[] {
  if (expert.kind === 'unavailable' || !expert.tasks.some(task => task.id === taskId)) return [];
  return expert.artifacts.filter(a => a.task_id === taskId && isExpertFailure(a)).sort((a, b) => {
    const score = (a: ExpertArtifact) => (a.detail ? 4 : 0) + (a.failure ? 2 : 0) + (a.headline ? 1 : 0);
    return score(b) - score(a);
  });
}
export function expertTaskOutcome(expert: ExpertMetadata, taskId: string): ExpertMetadata['quality'] {
  if (expert.kind === 'unavailable' || !expert.tasks.some(task => task.id === taskId)) return 'unverified';
  if (expertTaskFailures(expert, taskId).length) return 'degraded';
  const checks = expert.artifacts.filter(a => a.task_id === taskId && isExpertCheck(a));
  return expert.coverage.artifacts === 'complete' && checks.length > 0
    && checks.every(a => a.check_result === 'passed') ? 'ok' : 'unverified';
}
export function expertJobQuality(expert: ExpertMetadata): ExpertMetadata['quality'] {
  if (expert.kind === 'unavailable') return 'unverified';
  if (expert.quality === 'degraded' || expert.artifacts.some(isExpertFailure)) return 'degraded';
  const checks = expert.artifacts.filter(isExpertCheck);
  return expert.kind === 'available' && expert.coverage.tasks === 'complete'
    && expert.coverage.artifacts === 'complete' && checks.length > 0
    && checks.every(a => a.check_result === 'passed')
    && expert.tasks.every(task => expertTaskOutcome(expert, task.id) === 'ok') ? 'ok' : 'unverified';
}
export function expertCheckCounts(expert: ExpertMetadata) {
  const checks = expert.kind === 'unavailable' ? [] : expert.artifacts.filter(isExpertCheck);
  return { passed: checks.filter(a => a.check_result === 'passed' && !isExpertFailure(a)).length,
    failed: checks.filter(isExpertFailure).length,
    unverified: checks.filter(a => a.check_result === 'unavailable' && !isExpertFailure(a)).length };
}
export function expertFindingGroups(expert: ExpertMetadata): { key: string; artifacts: ExpertArtifact[] }[] {
  const groups = new Map<string, ExpertArtifact[]>();
  if (expert.kind === 'unavailable') return [];
  for (const artifact of expert.artifacts) {
    if (artifact.type.toUpperCase() === 'ROUTING') continue;
    const key = JSON.stringify([artifact.type.toUpperCase(), artifact.headline]);
    const group = groups.get(key);
    if (group) group.push(artifact); else groups.set(key, [artifact]);
  }
  const rank = (rows: ExpertArtifact[]) => rows.some(isExpertFailure) ? 0
    : rows.some(a => /^(risk|bug)$/i.test(a.type)) ? 1 : rows.some(isExpertCheck) ? 3 : 2;
  return [...groups].map(([key, artifacts]) => ({ key, artifacts })).sort((a, b) => rank(a.artifacts) - rank(b.artifacts));
}
export function expertPromptEcho(headline: string): boolean {
  return headline.trim().length >= 200 || /^(Role\s*:|Goal\s*:|Return\s+only\b)/i.test(headline.trim())
    || /^(you are|your task|implement|analyze|review the|audit|inspect|find all)\b/i.test(headline.trim());
}
