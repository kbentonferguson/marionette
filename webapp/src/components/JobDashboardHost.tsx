import { useEffect, useRef, useState } from "react";
import { ExternalLink, Maximize2, X } from "lucide-react";
import type { Job } from "../lib/api";
import { api } from "../lib/api";
import { openAgentUrlExternal } from "../lib/agentLinks";
import {
  JOBS_DASHBOARD_EXPAND_MIN_PX,
  JOBS_DASHBOARD_FOCUS_MIN_PX,
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
  const embedUrl = locate?.embed_url || locate?.url || "";

  useEffect(() => {
    requestRightMinWidth(JOBS_DASHBOARD_FOCUS_MIN_PX);
  }, [job.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setLocate(null);
    const repo = lastSelectedProjectRoot() || undefined;
    api.dashboard(job.id, repo)
      .then((payload) => {
        if (cancelled) return;
        setLocate(payload);
        if (!payload.ok || !(payload.embed_url || payload.url)) {
          setError(payload.detail || payload.error || "Dashboard unavailable.");
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
  }, [job.id]);

  const popOut = () => {
    if (embedUrl) openAgentUrlExternal(embedUrl);
  };

  return (
    <section
      data-testid="job-dashboard-host"
      data-job-id={job.id}
      aria-label={`Puppetmaster dashboard for ${title}`}
      className="flex flex-col h-full min-h-0 overflow-hidden text-txt bg-[var(--shell-chat,#0f1113)]"
    >
      <header className="shrink-0 flex items-center gap-2 px-2.5 py-1.5 border-b border-[var(--shell-panel-border)]">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[12px] font-semibold text-txt">{title}</h2>
          <p className="truncate font-mono text-[9px] text-faint">{job.id}</p>
        </div>
        <button
          type="button"
          className="px-1.5 py-0.5 text-[10.5px] text-muted hover:text-txt focus-visible:outline focus-visible:outline-accent"
          onClick={() => requestRightMinWidth(JOBS_DASHBOARD_EXPAND_MIN_PX)}
        >
          <span className="inline-flex items-center gap-1"><Maximize2 size={11} /> Expand</span>
        </button>
        <button
          type="button"
          className="px-1.5 py-0.5 text-[10.5px] text-muted hover:text-txt focus-visible:outline focus-visible:outline-accent disabled:opacity-50"
          disabled={!embedUrl}
          onClick={popOut}
        >
          <span className="inline-flex items-center gap-1"><ExternalLink size={11} /> Pop out</span>
        </button>
        <button
          type="button"
          className="px-1.5 py-0.5 text-[10.5px] text-muted hover:text-txt focus-visible:outline focus-visible:outline-accent"
          onClick={onClose}
        >
          <span className="inline-flex items-center gap-1"><X size={11} /> Close</span>
        </button>
      </header>
      <div className="relative flex-1 min-h-0 bg-[var(--shell-chat,#0f1113)]">
        {error && (
          <p role="alert" className="px-3 py-2 text-xs text-risk">
            {error} The Jobs list is still available — Close to return.
          </p>
        )}
        {loading && !embedUrl && (
          <p role="status" className="px-3 py-2 text-xs text-muted">Opening Puppetmaster dashboard…</p>
        )}
        {embedUrl && (isDesktop ? (
          // @ts-expect-error -- webview is an Electron element
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
            title={`Puppetmaster dashboard ${job.id}`}
            data-testid="job-dashboard-frame"
            className="absolute inset-0 w-full h-full border-0 bg-[var(--shell-chat,#0f1113)]"
          />
        ))}
      </div>
    </section>
  );
}
