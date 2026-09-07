import { useEffect, useId, useRef, useState } from "react";
import { Database, FolderTree, GitBranch, GitFork, GitPullRequest, Globe, History, Coins, Network, Plus, Settings, SquareTerminal } from "lucide-react";

const PANEL_OPTIONS = [
  { tab: "state", label: "State", icon: <Database size={12} /> },
  { tab: "swarm", label: "Swarm", icon: <Network size={12} /> },
  { tab: "economics", label: "Economics", icon: <Coins size={12} /> },
  { tab: "files", label: "Files", icon: <FolderTree size={12} /> },
  { tab: "git", label: "Git", icon: <GitBranch size={12} /> },
  { tab: "worktrees", label: "Worktrees", icon: <GitFork size={12} /> },
  { tab: "terminal", label: "Terminal", icon: <SquareTerminal size={12} /> },
  { tab: "review", label: "Review", icon: <GitPullRequest size={12} /> },
  { tab: "checkpoints", label: "History", icon: <History size={12} /> },
  { tab: "browser", label: "Browser", icon: <Globe size={12} /> },
];

function readStoredList(key: string): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

/** Shared panel catalog and selection flow; no activity polling. */
export default function PanelChooser({ onOpenTab, drawer = false }: {
  onOpenTab: (tab: string) => void;
  drawer?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open || drawer) return;
    const outside = (event: MouseEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open, drawer]);
  const stored = readStoredList("pmharness.tabOrder");
  const order = [...new Set([...stored, ...PANEL_OPTIONS.map(option => option.tab)])];
  const openCards = readStoredList("pmharness.board.openCards");
  const choose = (tab: string) => {
    setOpen(false);
    trigger.current?.focus();
    onOpenTab(tab);
  };
  return <div ref={root} className={drawer ? "panel-chooser-drawer" : "relative"}>
    <button ref={trigger} type="button" aria-label="Add panel" title="Add panel"
      aria-expanded={open} aria-controls={id} aria-haspopup={drawer ? undefined : "menu"}
      onClick={() => setOpen(value => !value)}
      className={drawer ? "px-3 flex items-center gap-2 focus-visible:outline" : "flex h-7 w-7 items-center justify-center rounded-xl text-faint hover:text-muted hover:bg-panel2/50 transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"}>
      <Plus size={15} strokeWidth={1.75} />{drawer && <span>Add panel</span>}
    </button>
    {open && <div id={id} role={drawer ? "group" : "menu"} aria-label="Add panel"
      className={drawer ? "panel-chooser-options" : "right-pane-add-menu right-[calc(100%+8px)] left-auto top-0"}>
      {order.map(tab => {
        const option = PANEL_OPTIONS.find(item => item.tab === tab);
        if (!option || openCards.includes(tab)) return null;
        return <button key={tab} type="button" role={drawer ? undefined : "menuitem"}
          aria-label={option.label} onClick={() => choose(tab)} className="right-pane-add-item">
          {option.icon}<span>{option.label}</span>
        </button>;
      })}
      <button type="button" role={drawer ? undefined : "menuitem"} onClick={() => choose("settings")} className="right-pane-add-item">
        <Settings size={12} /><span>Settings</span>
      </button>
    </div>}
  </div>;
}
