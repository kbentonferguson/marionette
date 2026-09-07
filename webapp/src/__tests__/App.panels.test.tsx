import { act, cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../App";
import { createPortal } from "react-dom";
import { resetSettingsOverlay } from "../lib/settingsOverlay";
const sessionSelection = vi.hoisted(() => ({ current: (_id: string) => {} }));

vi.mock("../lib/api", () => ({ api: {
  config: () => Promise.resolve({}), diagnostics: () => Promise.resolve({}), providers: () => Promise.resolve([{ has_key: true }]), getReviews: () => Promise.resolve([]), swarmLive: () => Promise.resolve({jobs: []}),
} }));
vi.mock("../components/LeftRail", () => ({ default: ({ onSessionChange }: { onSessionChange: (id: string) => void }) => {
  sessionSelection.current = onSessionChange;
  return <button>Session item</button>;
} }));
vi.mock("../components/Conversation", () => ({ default: () => <textarea aria-label="Chat editor" /> }));
vi.mock("../components/StatusBar", () => ({ default: () => null }));
vi.mock("../components/UpdateBanner", () => ({ default: () => null }));
vi.mock("../components/ProviderKeyBanner", () => ({ default: () => null }));
vi.mock("../components/KeyBootstrapBanner", () => ({ default: () => null }));
vi.mock("../components/RegistryWizard", () => ({ default: () => null }));
vi.mock("../components/OnboardingOverlay", () => ({ default: () => null }));
vi.mock("../components/CommandPalette", () => ({ default: () => null }));
vi.mock("../components/SettingsShell", () => ({ focusSettingsPage: vi.fn(), default: ({ onClose }: { onClose: () => void }) => createPortal(<button onClick={onClose}>Close settings</button>, document.body) }));
vi.mock("../components/StatePane", () => ({ default: () => <div /> }));
vi.mock("../components/BrowserPane", () => ({ default: () => <div /> }));
vi.mock("../components/FileTree", () => ({ default: () => <div /> }));
vi.mock("../components/SourceControl", () => ({ default: () => <div /> }));
vi.mock("../components/WorktreesPane", () => ({ default: () => <div /> }));
vi.mock("../components/TerminalPane", () => ({ default: () => <div /> }));
vi.mock("../components/CheckpointsPane", () => ({ default: () => <div /> }));
vi.mock("../components/DiffReviewPane", () => ({ default: () => <div /> }));
vi.mock("../components/SwarmPane", () => ({ default: () => <div /> }));
vi.mock("../components/EconomicsPane", () => ({ default: () => <div /> }));
function resize(width: number) {
  act(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
  });
}
beforeEach(() => {
  resetSettingsOverlay();
  localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  localStorage.setItem("pmharness.leftW", "248");
  localStorage.setItem("pmharness.rightW", "520");
  localStorage.setItem("pmharness.leftOpen", "1");
  localStorage.setItem("pmharness.rightOpen", "1");
  localStorage.setItem("pmharness.board.openCards", '["state"]');
});
afterEach(cleanup);


it.each([360, 640, 1024])("keeps desktop panel management and Settings reachable at %ipx", async width => {
  resize(width);
  await act(async () => { render(<App />); });
  const editor = screen.getByRole("textbox", { name: "Chat editor" });
  fireEvent.change(editor, { target: { value: "unsent desktop draft" } });
  const stateCard = screen.getByRole("region", { name: "State panel" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(editor.closest("[inert]")).toBeNull();
  const add = (name: string) => {
    fireEvent.click(screen.getByRole("button", { name: "Add panel" }));
    fireEvent.click(within(screen.getByRole("menu", { name: "Add panel" })).getByRole("menuitem", { name, exact: true }));
  };
  add("Files");
  add("Economics");
  expect(screen.getAllByRole("region")).toHaveLength(3);
  expect(screen.queryByText("Move panel")).toBeNull();
  expect(screen.queryByText("Shorter")).toBeNull();
  expect(screen.queryByText("Taller")).toBeNull();
  const closeFiles = screen.getByRole("button", { name: "Close Files panel" });
  closeFiles.focus();
  fireEvent.click(closeFiles);
  await waitFor(() => expect(stateCard).toHaveFocus());
  expect(screen.queryByRole("region", { name: "Files panel" })).toBeNull();
  const storedCards = localStorage.getItem("pmharness.board.openCards");
  add("Settings");
  fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
  expect(screen.getByRole("region", { name: "State panel" })).toBe(stateCard);
  fireEvent.click(screen.getByRole("button", { name: "Hide panels" }));
  expect(screen.queryByRole("region", { name: "State panel" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  expect(screen.getByRole("button", { name: "Close settings" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
  expect(screen.queryByRole("region", { name: "State panel" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Show panels" }));
  resize(1280);
  expect(screen.getByRole("textbox")).toBe(editor);
  expect(editor).toHaveValue("unsent desktop draft");
  expect(localStorage.getItem("pmharness.board.openCards")).toBe(storedCards);
});
