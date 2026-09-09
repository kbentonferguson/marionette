import { useEffect, useRef, useState } from "react";
import { ExternalLink, Maximize2, X } from "lucide-react";
import type { Job } from "../lib/api";
import { api } from "../lib/api";
import { dashboardJobId } from "../lib/jobClassification";
import { openAgentUrlExternal } from "../lib/agentLinks";
import {
  JOBS_DASHBOARD_EXPAND_MIN_PX,
  JOBS_DASHBOARD_FOCUS_MIN_PX,
  notifyJobsDashboardChrome,
  requestRightMinWidth,
  type DashboardLocate,
} from "../lib/jobsDashboard";
import { lastSelectedProjectRoot } from "../lib/panelTransition";

export default function JobDashboardHost({
  job,
  onClose,
}: {
  job: Job;
  onClose: () => void;
}) {
  const isDesktop = !!(window as { harnessIPC?: unknown }).harnessIPC;
  const webviewRef = useRef<HTMLElement | null>(null);
  const [locate, setLocate] = useState<DashboardLocate | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const title = (job.goal || "").trim() || job.id;
  const embedId = dashboardJobId(job);
  const embedUrl = locate?.embed_url || locate?.url || "";
  const showId = embedId && embedId !== title;

  useEffect(() => {
    requestRightMinWidth(JOBS_DASHBOARD_FOCUS_MIN_PX);
    notifyJobsDashboardChrome(true);
    return () => notifyJobsDashboardChrome(false);
  }, [embedId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setLocate(null);
    if (!embedId.startsWith("job_")) {
      setError(
        "Durable Puppetmaster job id is not ready for this hire yet (need job_…). Close and reopen once the store assigns one.",
      );
      setLoading(false);
      return;
    }
    const repo = lastSelectedProjectRoot() || undefined;
    const locateDashboard = api.dashboard;
    if (typeof locateDashboard !== "function") {
      setError("Dashboard unavailable.");
      setLoading(false);
      return;
    }
    locateDashboard(embedId, repo)
      .then((payload) => {
        if (cancelled) return;
        setLocate(payload);
        if (!payload.ok || !(payload.embed_url || payload.url)) {
          const stderr = typeof (payload as { stderr?: unknown }).stderr === "string"
            ? String((payload as { stderr?: string }).stderr).trim()
            : "";
          const base = payload.detail || payload.error || "Dashboard unavailable.";
          setError(stderr ? `${base}: ${stderr.slice(0, 280)}` : base);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Dashboard unavailable.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [embedId]);

  const popOut = () => {
    if (embedUrl) openAgentUrlExternal(embedUrl);
  };

  return (
    <section
      data-testid="job-dashboard-host"
      data-job-id={job.id}
      data-dashboard-job-id={embedId}
      data-chrome="compact"
      aria-label={`Puppetmaster dashboard for ${title}`}
      className="job-dashboard-host flex flex-col h-full min-h-0 overflow-hidden text-txt"
    >
      <header className="job-dashboard-chrome" data-testid="job-dashboard-chrome">
        <div className="min-w-0 flex-1 flex items-baseline gap-1.5">
          <h2 className="truncate text-[11px] font-semibold leading-none tracking-tight text-txt" title={title}>
            {title}
          </h2>
          {showId && (
            <span className="truncate font-mono text-[9px] leading-none text-faint" title={embedId}>
              {embedId}
            </span>
          )}
        </div>
        <div className="flex items-center shrink-0">
          <button
            type="button"
            className="right-pane-icon-btn"
            aria-label="Expand"
            title="Expand"
            onClick={() => requestRightMinWidth(JOBS_DASHBOARD_EXPAND_MIN_PX)}
          >
            <Maximize2 size={12} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            className="right-pane-icon-btn"
            aria-label="Pop out"
            title="Pop out"
            disabled={!embedUrl}
            onClick={popOut}
          >
            <ExternalLink size={12} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            className="right-pane-icon-btn"
            aria-label="Close"
            title="Close"
            onClick={onClose}
          >
            <X size={12} strokeWidth={1.75} />
          </button>
        </div>
      </header>
      <div className="relative flex-1 min-h-0 bg-[var(--shell-chat,#0f1113)]">
        {error && (
          <p role="alert" className="px-2.5 py-2 text-[11px] leading-snug text-risk">
            {error} The Jobs list is still available — Close to return.
          </p>
        )}
        {loading && !embedUrl && (
          <p role="status" className="px-2.5 py-2 text-[11px] text-muted">Opening Puppetmaster dashboard…</p>
        )}
        {embedUrl && (isDesktop ? (
          <webview
            ref={webviewRef}
            src={embedUrl}
            data-testid="job-dashboard-webview"
            className="absolute inset-0 w-full h-full border-0"
            style={{ backgroundColor: "#0f1113" }}
          />
        ) : (
          <iframe
            src={embedUrl}
            title={`Puppetmaster dashboard ${embedId}`}
            data-testid="job-dashboard-frame"
            className="absolute inset-0 w-full h-full border-0 bg-[var(--shell-chat,#0f1113)]"
          />
        ))}
      </div>
    </section>
  );
}
