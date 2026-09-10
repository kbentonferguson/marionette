/**
 * Jobs rail is a viewport over Puppetmaster (`?job=&embed=1`).
 * Marionette adapters locate and embed that dashboard — they are transports,
 * not a second native tracker.
 */

export const JOBS_RAIL_VIEWPORT = "puppetmaster-embed" as const;

export const JOBS_DASHBOARD_FOCUS_MIN_PX = 640;
export const JOBS_DASHBOARD_EXPAND_MIN_PX = 800;
export const REQUEST_RIGHT_MIN_WIDTH_EVENT = "harness-request-right-min-width";
export const JOBS_DASHBOARD_CHROME_EVENT = "harness-jobs-dashboard-chrome";

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

/** Alias: the Jobs rail hosts only this PM embed, never a dual native tracker. */
export function jobsRailViewportUrl(
  host: string,
  port: number,
  jobId?: string | null,
): string {
  return buildDashboardEmbedUrl(host, port, jobId);
}

export function jobsRailIsPuppetmasterViewport(): true {
  return true;
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

/** Hide the Jobs card drag/close bar so the host chrome is the only Marionette strip. */
export function notifyJobsDashboardChrome(focused: boolean): void {
  try {
    window.dispatchEvent(
      new CustomEvent(JOBS_DASHBOARD_CHROME_EVENT, { detail: { focused } }),
    );
  } catch {
    /* ignore */
  }
}
