/** Puppetmaster dashboard deep-links hosted in the Jobs tool. */

export const JOBS_DASHBOARD_FOCUS_MIN_PX = 640;
export const JOBS_DASHBOARD_EXPAND_MIN_PX = 800;
export const REQUEST_RIGHT_MIN_WIDTH_EVENT = "harness-request-right-min-width";

export type DashboardLocate = {
  ok: boolean;
  reused?: boolean;
  host?: string;
  port?: number;
  url?: string;
  embed_url?: string;
  job_id?: string | null;
  error?: string;
  detail?: string;
};

export function buildDashboardEmbedUrl(host: string, port: number, jobId?: string | null): string {
  const params = new URLSearchParams();
  const id = (jobId || "").trim();
  if (id) params.set("job", id);
  params.set("embed", "1");
  return `http://${host}:${port}/?${params.toString()}`;
}

export function requestRightMinWidth(minPx: number): void {
  if (!(minPx > 0)) return;
  try {
    window.dispatchEvent(
      new CustomEvent(REQUEST_RIGHT_MIN_WIDTH_EVENT, { detail: { minPx } }),
    );
  } catch {
    /* ignore */
  }
}
