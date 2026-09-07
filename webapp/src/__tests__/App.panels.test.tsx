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
vi.mock("../components/RightDock", () => ({ default: ({ onOpenTab }: { onOpenTab: (tab: string) => void }) => <button onClick={() => onOpenTab("review")}>Review shortcut</button> }));
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

it.each([400, 639])("manages cards inside the %ipx drawer and retains state through resizing", async width => {
  resize(1019);
  await act(async () => { render(<App />); });
  const editor = screen.getByRole("textbox", { name: "Chat editor" });
  fireEvent.change(editor, { target: { value: "unsent desktop draft" } });
  const stateCard = screen.getByRole("region", { name: "State panel" });
  resize(width);
  const trigger = screen.getByRole("button", { name: "Panels", exact: true });
  trigger.focus();
  fireEvent.click(trigger);
  const drawer = screen.getByRole("dialog", { name: "Panels" });
  const inside = within(drawer);
  expect(editor.closest("[inert]")).not.toBeNull();
  expect(inside.getByRole("region", { name: "State panel" })).toBe(stateCard);
  const add = (name: string) => {
    fireEvent.click(inside.getByRole("button", { name: "Add panel" }));
    fireEvent.click(within(inside.getByRole("group", { name: "Add panel" })).getByRole("button", { name, exact: true }));
  };
  add("Files");
  add("Economics");
  expect(inside.getAllByRole("region")).toHaveLength(3);
  const closeFiles = inside.getByRole("button", { name: "Close Files panel" });
  closeFiles.focus();
  fireEvent.click(closeFiles);
  await waitFor(() => expect(stateCard).toHaveFocus());
  expect(inside.queryByRole("region", { name: "Files panel" })).toBeNull();
  expect(drawer).toHaveAttribute("open");
  add("Files");
  expect(inside.getByRole("region", { name: "Files panel" })).toBeVisible();
  add("Settings");
  expect(drawer).not.toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
  expect(drawer).toHaveAttribute("open");
  const storedCards = localStorage.getItem("pmharness.board.openCards");
  fireEvent(drawer, new Event("cancel", { cancelable: true }));
  expect(trigger).toHaveFocus();
  resize(640);
  expect(screen.getByRole("complementary", { name: "Panels" })).not.toHaveAttribute("aria-modal");
  resize(800);
  expect(editor.closest("[inert]")).toBeNull();
  resize(1280);
  expect(screen.getByRole("textbox")).toBe(editor);
  expect(editor).toHaveValue("unsent desktop draft");
  expect(screen.getByRole("region", { name: "State panel" })).toBe(stateCard);
  expect(localStorage.getItem("pmharness.board.openCards")).toBe(storedCards);
  expect(localStorage.getItem("pmharness.leftW")).toBe("248");
  expect(localStorage.getItem("pmharness.rightW")).toBe("520");
  expect(localStorage.getItem("pmharness.leftOpen")).toBe("1");
  expect(localStorage.getItem("pmharness.rightOpen")).toBe("1");
});

it("exposes Add panel inside an open narrow drawer", async () => {
  resize(400);
  await act(async () => { render(<App />); });
  fireEvent.click(screen.getByRole("button", { name: "Panels", exact: true }));
  const drawer = screen.getByRole("dialog", { name: "Panels" });
  fireEvent.click(within(drawer).getByRole("button", { name: "Add panel" }));
  expect(within(drawer).getByRole("button", { name: "Economics", exact: true })).toBeVisible();
});
