import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import RightPane from "../components/RightPane";
import { resetSettingsOverlay } from "../lib/settingsOverlay";

const activity = vi.hoisted(() => ({ poll: vi.fn() }));

vi.mock("../lib/api", () => ({ api: {
  getReviews: vi.fn().mockResolvedValue([]),
  swarmLive: vi.fn().mockResolvedValue({ jobs: [] }),
} }));
vi.mock("../components/StatePane", () => ({ default: () => null }));
vi.mock("../components/BrowserPane", () => ({ default: () => null }));
vi.mock("../components/FileTree", () => ({ default: () => null }));
vi.mock("../components/SourceControl", () => ({ default: () => null }));
vi.mock("../components/WorktreesPane", () => ({ default: () => null }));
vi.mock("../components/SettingsShell", () => ({ default: () => null }));
vi.mock("../components/TerminalPane", () => ({ default: () => null }));
vi.mock("../components/CheckpointsPane", () => ({ default: () => null }));
vi.mock("../components/DiffReviewPane", () => ({ default: () => null }));
vi.mock("../components/SwarmPane", () => ({ default: () => null }));
vi.mock("../components/EconomicsPane", () => ({
  default: function EconomicsProbe() {
    const [scope, setScope] = useState("repo");
    useEffect(() => {
      const timer = setInterval(activity.poll, 1000);
      return () => clearInterval(timer);
    }, []);
    return <input aria-label="Economics scope draft" value={scope}
      onChange={event => setScope(event.target.value)} />;
  },
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  localStorage.clear();
  resetSettingsOverlay();
  localStorage.setItem("pmharness.board.openCards", JSON.stringify(["economics"]));
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("pauses retained card effects while hidden and resumes without losing its draft", async () => {
  const props = { artifacts: [], onOpenWizard: vi.fn() };
  const view = render(<RightPane {...props} visible />);
  const input = screen.getByRole("textbox", { name: "Economics scope draft" });
  fireEvent.change(input, { target: { value: "session" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(activity.poll).toHaveBeenCalledTimes(1);

  view.rerender(<RightPane {...props} visible={false} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(activity.poll).toHaveBeenCalledTimes(1);

  view.rerender(<RightPane {...props} visible />);
  expect(screen.getByRole("textbox", { name: "Economics scope draft" })).toBe(input);
  expect(input).toHaveValue("session");
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(activity.poll).toHaveBeenCalledTimes(2);
});
