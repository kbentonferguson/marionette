import PanelChooser from "./PanelChooser";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Database,
  GitPullRequest,
  Globe,
  Coins,
  Network,
  PanelRight,
  PanelRightClose,
  Settings,
  SquareTerminal,
} from "lucide-react";
import { api } from "../lib/api";
import { lastSelectedProjectRoot } from "../lib/panelTransition";
import { writeSWRCache } from "../lib/useStaleWhileRevalidate";
import { countRunningTrackerJobs } from "../lib/jobClassification";
import { filterJobsByScope, JOB_SCOPE_CHANGED_EVENT, loadJobScope } from "../lib/jobScope";

/** Curated destinations for the floating tool windows — Cursor-style icon strip.
 *  Settings is pinned to the foot of the floating pill. */
const DOCK_LINKS: { id: string; tab: string; icon: ReactNode; title: string }[] = [
  {
    id: "swarm",
    tab: "swarm",
    icon: <Network size={15} strokeWidth={1.75} />,
    title: "Swarm tracker",
  },
  {
    id: "economics",
    tab: "economics",
    icon: <Coins size={15} strokeWidth={1.75} />,
    title: "Economics",
  },
  {
    id: "review",
    tab: "review",
    icon: <GitPullRequest size={15} strokeWidth={1.75} />,
    title: "Pending review / apply",
  },
  {
    id: "browser",
    tab: "browser",
    icon: <Globe size={15} strokeWidth={1.75} />,
    title: "In-app browser",
  },
  {
    id: "terminal",
    tab: "terminal",
    icon: <SquareTerminal size={15} strokeWidth={1.75} />,
    title: "Terminal (Ctrl/Cmd+`)",
  },
  {
    id: "state",
    tab: "state",
    icon: <Database size={15} strokeWidth={1.75} />,
    title: "CodeGraph, Wiki, MCP",
  },
];

export default function RightDock({
  onOpenTab,
  onExpand,
  onCollapse,
  panelsOpen = true,
}: {
  onOpenTab: (tab: string) => void;
  onExpand: () => void;
  onCollapse: () => void;
  panelsOpen?: boolean;
}) {
  const [reviewCount, setReviewCount] = useState(0);
  // Live swarm activity dot: the collapsed pill must show running jobs just
  // like the expanded tracker tab does, or background swarms go invisible.
  const [swarmRunning, setSwarmRunning] = useState(0);
  const [swarmRepo, setSwarmRepo] = useState<string | undefined>(
    () => lastSelectedProjectRoot() || undefined,
  );
  const [activitySessionId, setActivitySessionId] = useState("");
  const [scopeEpoch, setScopeEpoch] = useState(0);
  const activityEpoch = useRef(0);

  useEffect(() => {
    const onSession = (e: Event) => {
      const id = String((e as CustomEvent<{ sessionId?: string | null }>).detail?.sessionId || "");
      activityEpoch.current += 1;
      setScopeEpoch((n) => n + 1);
      setActivitySessionId(id);
    };
    const onScope = () => {
      activityEpoch.current += 1;
      setScopeEpoch((n) => n + 1);
    };
    window.addEventListener("harness-session-changed", onSession);
    window.addEventListener(JOB_SCOPE_CHANGED_EVENT, onScope);
    return () => {
      window.removeEventListener("harness-session-changed", onSession);
      window.removeEventListener(JOB_SCOPE_CHANGED_EVENT, onScope);
    };
  }, []);

  useEffect(() => {
    const onProject = (e: Event) => {
      const path = (e as CustomEvent<string>).detail;
      if (typeof path === "string") {
        activityEpoch.current += 1;
        setScopeEpoch((n) => n + 1);
        setSwarmRepo(path || undefined);
      }
    };
    window.addEventListener("harness-project-selected", onProject);
    return () => window.removeEventListener("harness-project-selected", onProject);
  }, []);

  useEffect(() => {
    let active = true;
    let request = 0;
    const epoch = activityEpoch.current;
    const load = () => {
      const generation = ++request;
      const current = () => active && epoch === activityEpoch.current && generation === request;
      api.getReviews()
        .then((rows) => {
          if (current()) setReviewCount(Array.isArray(rows) ? rows.length : 0);
        })
        .catch(() => {});
      api.swarmLive(swarmRepo)
        .then((data) => {
          if (!current()) return;
          // Parity with RightPane: seed SwarmPane's SWR cache from the dock poll
          // so expanding into the tracker after a collapsed session is warm too.
          writeSWRCache(`swarm:${swarmRepo || "__default__"}`, data);
          const jobs = Array.isArray(data?.jobs) ? data.jobs : [];
          setSwarmRunning(
            countRunningTrackerJobs(
              filterJobsByScope(jobs, loadJobScope(), activitySessionId),
            ),
          );
        })
        .catch(() => {
          /* keep last known; dot is best-effort */
        });
    };
    load();
    const t = setInterval(load, 5000);
    window.addEventListener("harness-reviews-refresh", load);
    return () => {
      active = false;
      clearInterval(t);
      window.removeEventListener("harness-reviews-refresh", load);
    };
  }, [swarmRepo, activitySessionId, scopeEpoch]);

  return (
    <aside
      className="relative shrink-0 self-start mx-4 mt-14 mb-10 flex flex-col items-center select-none"
      aria-label="Floating panel shortcuts"
    >
      {/* Same --shell-panel glass as the left rail: slightly darker keep so
          icons stay readable, no extra backdrop-blur island. */}
      <div
        data-testid="floating-dock-pill"
        className="pointer-events-auto flex flex-col items-center gap-0.5 rounded-2xl px-1 py-1.5 shell-inset-glass"
      >
        <button
          type="button"
          onClick={panelsOpen ? onCollapse : onExpand}
          title={panelsOpen ? "Hide panels (Ctrl/Cmd+J)" : "Show panels (Ctrl/Cmd+J)"}
          aria-label={panelsOpen ? "Hide panels" : "Show panels"}
          {...(panelsOpen ? { "data-testid": "panel-collapse-btn" } : {})}
          className="flex h-7 w-7 items-center justify-center rounded-xl text-faint hover:text-muted hover:bg-panel2/50 transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
        >
          {panelsOpen ? (
            <PanelRightClose size={15} strokeWidth={1.75} />
          ) : (
            <PanelRight size={15} strokeWidth={1.75} />
          )}
        </button>

        <span className="my-0.5 h-px w-4 bg-edge/50" aria-hidden />

        <PanelChooser onOpenTab={onOpenTab} />

        {DOCK_LINKS.map((link) => (
          <button
            key={link.id}
            type="button"
            onClick={() => onOpenTab(link.tab)}
            title={link.title}
            aria-label={link.title}
            className="relative flex h-7 w-7 items-center justify-center rounded-xl text-faint hover:text-muted hover:bg-panel2/50 transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
          >
            {link.icon}
            {link.id === "swarm" && swarmRunning > 0 && (
              <span
                title={`${swarmRunning} swarm job${swarmRunning === 1 ? "" : "s"} running`}
                className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-accent animate-pulse"
              />
            )}
            {link.id === "review" && reviewCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[0.875rem] h-3.5 px-0.5 rounded-full bg-accent text-panel text-[8px] font-bold flex items-center justify-center border border-panel">
                {reviewCount > 9 ? "9+" : reviewCount}
              </span>
            )}
          </button>
        ))}

        <button
          type="button"
          onClick={() => onOpenTab("settings")}
          title="Settings (Ctrl/Cmd+Shift+J)"
          aria-label="Settings"
          className="flex h-7 w-7 items-center justify-center rounded-xl text-faint hover:text-muted hover:bg-panel2/50 transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
        >
          <Settings size={15} strokeWidth={1.75} />
        </button>
      </div>
    </aside>
  );
}
