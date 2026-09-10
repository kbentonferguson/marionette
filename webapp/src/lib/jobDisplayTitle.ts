/** Human job titles for Jobs chrome. Never paint raw provenance JSON. */

export type JobTitleSource = {
  goal?: string | null;
  label?: string | null;
  role?: string | null;
  job_kind?: string | null;
  id?: string | null;
};

function oneLine(value: unknown): string {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function humanizeStamp(value: unknown): string {
  return oneLine(value).replaceAll("_", " ");
}

/** True when the string is (or is wrapped as) a JSON object/array dump. */
export function looksLikeRawJobJson(value: unknown): boolean {
  const text = oneLine(value);
  if (!text) return false;
  const start = text[0];
  const end = text[text.length - 1];
  if (!((start === "{" && end === "}") || (start === "[" && end === "]"))) return false;
  try {
    const parsed = JSON.parse(text) as unknown;
    return parsed !== null && typeof parsed === "object";
  } catch {
    return false;
  }
}

function usableTitle(value: unknown): string {
  const text = oneLine(value);
  if (!text || looksLikeRawJobJson(text)) return "";
  return text;
}

/**
 * Prefer goal / label. Skip provenance JSON blobs. Fall back to a
 * humanized role/kind, then a short "Job" — never the raw dump.
 */
export function jobDisplayTitle(job: JobTitleSource, fallback = "Job"): string {
  const fromLabel = usableTitle(job.label);
  if (fromLabel) return fromLabel;
  const fromGoal = usableTitle(job.goal);
  if (fromGoal) return fromGoal;
  const fromRole = usableTitle(humanizeStamp(job.role));
  if (fromRole) return fromRole;
  const fromKind = usableTitle(humanizeStamp(job.job_kind));
  if (fromKind) return fromKind;
  return fallback;
}
