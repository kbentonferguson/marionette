import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import LeftRail from "../components/LeftRail";
import { clearSWRCache } from "../lib/useStaleWhileRevalidate";

vi.mock("../lib/api", () => ({
  api: {
    getWorkspace: vi.fn().mockResolvedValue({
      repo: "/workspace",
      branch: "main",
      is_git: true,
      head_unborn: false,
      codegraph_status: "ready",
      recents: [],
      home: "/home",
    }),
    workspaces: vi.fn().mockResolvedValue([
      { name: "main", active: true, dirty: false },
    ]),
    sessions: vi.fn().mockResolvedValue([
      { id: "session-1", title: "Current", active: true, repo: "/workspace" },
    ]),
    pruneEditBranches: vi.fn(),
    jobs: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock("../lib/usePolling", () => ({ usePolling: vi.fn() }));
vi.mock("../lib/useOperationalDiagnostic", () => ({
  useOperationalDiagnostic: () => null,
}));


beforeEach(() => {
  localStorage.clear();
  clearSWRCache();
  vi.mocked(api.pruneEditBranches).mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const pruneButton = () => screen.getByTitle("Prune unused edit/worker and leftover release branches");

it("captures and displays the repository before confirmation, with one pending dispatch", async () => {
  vi.mocked(api.pruneEditBranches).mockImplementation(() => new Promise(() => {}));
  render(<LeftRail jobsRefresh={0} />);
  await waitFor(() => expect(api.workspaces).toHaveBeenCalled());
  await screen.findByRole("button", { name: "main", exact: true }, { timeout: 5000 });
  act(() => { fireEvent.click(pruneButton()); fireEvent.click(pruneButton()); });
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("/workspace"));
  expect(api.pruneEditBranches).toHaveBeenCalledExactlyOnceWith("/workspace");
});

it.each(["success", "failure"])("suppresses late %s after workspace scope changes", async (outcome) => {
  let finish: (value: Awaited<ReturnType<typeof api.pruneEditBranches>>) => void = () => {};
  let fail: (error: Error) => void = () => {};
  vi.mocked(api.pruneEditBranches).mockImplementation(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
  const toast = vi.fn();
  window.addEventListener("harness-toast", toast);
  render(<LeftRail jobsRefresh={0} />);
  await waitFor(() => expect(api.workspaces).toHaveBeenCalled());
  await screen.findByRole("button", { name: "main", exact: true }, { timeout: 5000 });
  fireEvent.click(pruneButton());
  const calls = vi.mocked(api.workspaces).mock.calls.length;
  await act(async () => {
    window.dispatchEvent(new CustomEvent("harness-project-selected", { detail: "/other" }));
    if (outcome === "success") finish({ ok: true, count: 1, deleted: ["pmedit-old"] });
    else fail(new Error("old repo failed"));
  });
  expect(toast).not.toHaveBeenCalled();
  expect(api.workspaces).toHaveBeenCalledTimes(calls);
  window.removeEventListener("harness-toast", toast);
});

it("cancels when scope changes while confirmation is open", async () => {
  vi.mocked(window.confirm).mockImplementation(() => {
    window.dispatchEvent(new CustomEvent("harness-project-selected", { detail: "/other" }));
    return true;
  });
  render(<LeftRail jobsRefresh={0} />);
  await waitFor(() => expect(api.workspaces).toHaveBeenCalled());
  await screen.findByRole("button", { name: "main", exact: true }, { timeout: 5000 });
  fireEvent.click(pruneButton());
  expect(api.pruneEditBranches).not.toHaveBeenCalled();
});

it("reports protected targets after pruning", async () => {
  vi.mocked(api.pruneEditBranches).mockResolvedValue({
    ok: true, count: 0, deleted: [], skipped: [{ path: "/workspace/tree", reason: "Locked worktree" },
      { branch: "pmedit-unique", path: "", reason: "Commits not retained by a non-prunable local branch" }],
  });
  const toast = vi.fn();
  window.addEventListener("harness-toast", toast);
  render(<LeftRail jobsRefresh={0} />);
  await waitFor(() => expect(api.workspaces).toHaveBeenCalled());
  await screen.findByRole("button", { name: "main", exact: true }, { timeout: 5000 });
  await act(async () => { fireEvent.click(pruneButton()); });
  await waitFor(() => expect(api.pruneEditBranches).toHaveBeenCalledWith("/workspace"));
  await waitFor(() => {
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ detail: expect.stringContaining("/workspace/tree (Locked worktree)") }));
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ detail: expect.stringContaining("pmedit-unique (Commits not retained") }));
  });
  window.removeEventListener("harness-toast", toast);
});
