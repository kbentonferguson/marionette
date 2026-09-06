/** Scoped artifact gather after transcript hydration. */
import type { Job } from "../../lib/api";
import { fetchJobArtifacts, selectJobRef } from "../../lib/jobArtifacts";
import { collectDisplayArtifacts, mergeUniqueArtifacts, type SessionArtifact } from "./sessionHydrate";

export function gatherSessionArtifacts(opts: {
  display: unknown;
  jobIds: string[] | undefined;
  jobs?: Job[];
  repo?: string;
  sessionId?: string;
  stillCurrent: () => boolean;
}): SessionArtifact[] | Promise<SessionArtifact[]> {
  if (!opts.stillCurrent()) return [];
  const displayArtifacts = collectDisplayArtifacts(opts.display);
  if (!opts.jobIds?.length) return mergeUniqueArtifacts(displayArtifacts, []);
  const unavailable = (id: string): SessionArtifact[] => [{
    type: "note", headline: `Artifact preview unavailable for ${id} in the active workspace and session. Reopen the session to retry.`,
  }];
  // Resolve all selections before starting requests; id-only transcript records
  // are insufficient when the live snapshot contains colliding job ids.
  const selections = opts.jobIds.map(id => {
    const candidates = (opts.jobs || []).filter(job => job.id === id);
    return { id, selection: candidates.length === 1
      ? selectJobRef(candidates[0], opts.repo || "", opts.sessionId || "") : null };
  });
  return Promise.all(selections.map(async ({ id, selection }) => {
    if (!selection) return unavailable(id);
    try { return await fetchJobArtifacts(selection); }
    catch { return unavailable(id); }
  })).then(rows => opts.stillCurrent()
    ? mergeUniqueArtifacts(displayArtifacts, rows.flat()) : []);
}
