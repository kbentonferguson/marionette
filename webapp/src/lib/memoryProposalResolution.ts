/** Persist Save/Skip so session switch + SSE replay cannot resurrect the card. */

const PREFIX = "pmharness.memoryResolved.v1:";

let activeSessionId = "";

export function setActiveMemoryProposalSession(sessionId: string): void {
  activeSessionId = String(sessionId || "").trim();
}

export function getActiveMemoryProposalSession(): string {
  return activeSessionId;
}

function keyFor(sessionId: string): string {
  return PREFIX + String(sessionId || "").trim();
}

function readIds(sessionId: string): string[] {
  const sid = String(sessionId || "").trim();
  if (!sid) return [];
  try {
    const raw = sessionStorage.getItem(keyFor(sid));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === "string" && !!id.trim()).slice(-200);
  } catch {
    return [];
  }
}

function writeIds(sessionId: string, ids: string[]): void {
  const sid = String(sessionId || "").trim();
  if (!sid) return;
  try {
    sessionStorage.setItem(keyFor(sid), JSON.stringify(ids.slice(-200)));
  } catch {
    /* optional persistence */
  }
}

export function rememberResolvedMemoryProposal(sessionId: string, id: string): void {
  const proposalId = String(id || "").trim();
  if (!proposalId) return;
  const next = [...readIds(sessionId).filter((item) => item !== proposalId), proposalId];
  writeIds(sessionId, next);
}

export function forgetResolvedMemoryProposal(sessionId: string, id: string): void {
  const proposalId = String(id || "").trim();
  writeIds(sessionId, readIds(sessionId).filter((item) => item !== proposalId));
}

export function isResolvedMemoryProposal(sessionId: string, id: string): boolean {
  const proposalId = String(id || "").trim();
  if (!proposalId) return false;
  return readIds(sessionId).includes(proposalId);
}
