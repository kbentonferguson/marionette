import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../App";
const sessionSelection = vi.hoisted(() => ({ current: (_id: string) => {} }));

vi.mock("../lib/api", () => ({ api: {
  config: () => Promise.resolve({}), diagnostics: () => Promise.resolve({}), providers: () => Promise.resolve([{ has_key: true }]),
} }));
vi.mock("../components/LeftRail", () => ({ default: ({ onSessionChange }: { onSessionChange: (id: string) => void }) => {
  sessionSelection.current = onSessionChange;
  return <button>Session item</button>;
} }));
vi.mock("../components/Conversation", () => ({ default: () => <textarea aria-label="Chat editor" /> }));
vi.mock("../components/RightPane", () => ({ default: () => <button>Panel item</button> }));
vi.mock("../components/RightDock", () => ({ default: ({ onOpenTab }: { onOpenTab: (tab: string) => void }) => <button onClick={() => onOpenTab("review")}>Review shortcut</button> }));
vi.mock("../components/StatusBar", () => ({ default: () => null }));
vi.mock("../components/UpdateBanner", () => ({ default: () => null }));
vi.mock("../components/ProviderKeyBanner", () => ({ default: () => null }));
vi.mock("../components/KeyBootstrapBanner", () => ({ default: () => null }));
vi.mock("../components/RegistryWizard", () => ({ default: () => null }));
vi.mock("../components/OnboardingOverlay", () => ({ default: () => null }));
vi.mock("../components/CommandPalette", () => ({ default: () => null }));
vi.mock("../components/SettingsShell", () => ({ focusSettingsPage: vi.fn() }));
function resize(width: number) {
  act(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
  });
}
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("pmharness.leftW", "248");
  localStorage.setItem("pmharness.rightW", "520");
  localStorage.setItem("pmharness.leftOpen", "1");
  localStorage.setItem("pmharness.rightOpen", "1");
  localStorage.setItem("pmharness.board.openCards", '["review"]');
  resize(1280);
});
afterEach(cleanup);

it("keeps desktop preferences and chat mounted through real window resize events", async () => {
  await act(async () => { render(<App />); });
  const editor = screen.getByRole("textbox", { name: "Chat editor" });
  fireEvent.change(editor, { target: { value: "unsent draft" } });
  screen.getByRole("button", { name: "Panel item" }).focus();
  resize(600);
  expect(screen.getByRole("button", { name: "Chat", exact: true })).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Panel item" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Session item" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sessions", exact: true }));
  act(() => { sessionSelection.current("parent-session"); });
  expect(screen.getByRole("button", { name: "Session item" })).toBeVisible();
  expect(screen.queryByRole("textbox")).toBeNull();
  fireEvent.keyDown(window, { key: "j", ctrlKey: true });
  expect(screen.getByRole("button", { name: "Panel item" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Session item" })).toBeNull();
  fireEvent.keyDown(window, { key: "j", ctrlKey: true });
  expect(screen.getByRole("textbox")).toBe(editor);
  expect(editor).toHaveValue("unsent draft");
  fireEvent.click(screen.getByRole("button", { name: "Review shortcut" }));
  expect(screen.getByRole("button", { name: "Panel item" })).toBeVisible();
  act(() => { window.dispatchEvent(new CustomEvent("harness-open-file", { detail: { path: "alpha.txt" } })); });
  expect(editor).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Sessions", exact: true }));
  act(() => { sessionSelection.current("child-session"); });
  expect(editor).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Review shortcut" }));
  const focusEditor = () => editor.focus();
  window.addEventListener("harness-focus-input", focusEditor);
  fireEvent.keyDown(window, { key: "l", ctrlKey: true });
  expect(editor).toHaveFocus();
  window.removeEventListener("harness-focus-input", focusEditor);
  fireEvent.keyDown(window, { key: "b", ctrlKey: true });
  expect(screen.getByRole("button", { name: "Session item" })).toBeVisible();
  resize(1280);
  expect(screen.getByRole("button", { name: "Panel item" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Session item" })).toBeVisible();
  expect(editor).toBeVisible();
  expect(localStorage.getItem("pmharness.leftW")).toBe("248");
  expect(localStorage.getItem("pmharness.rightW")).toBe("520");
  expect(localStorage.getItem("pmharness.leftOpen")).toBe("1");
  expect(localStorage.getItem("pmharness.rightOpen")).toBe("1");
});

it.each([800, 900, 1019, 1280])("keeps Panels inline and chat accessible at %ipx", async (width) => {
  resize(width);
  await act(async () => { render(<App />); });
  const panels = screen.getByRole("complementary", { name: "Panels" });
  expect(panels).toHaveAttribute("data-presentation", "inline");
  expect(panels).not.toHaveAttribute("aria-modal");
  const editor = screen.getByRole("textbox", { name: "Chat editor" });
  expect(editor.closest("[inert]")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: "Review shortcut" })).toBeVisible();
});

it("closes phone drawers on native Escape cancellation and backdrop, restoring the trigger", async () => {
  resize(390);
  await act(async () => { render(<App />); });
  const editor = screen.getByRole("textbox", { name: "Chat editor" });
  fireEvent.change(editor, { target: { value: "phone draft" } });
  const trigger = screen.getByRole("button", { name: "Sessions", exact: true });
  trigger.focus();
  fireEvent.click(trigger);
  const drawer = screen.getByRole("dialog", { name: "Sessions" });
  expect(drawer).toHaveAttribute("data-presentation", "left");
  fireEvent(drawer, new Event("cancel", { cancelable: true }));
  expect(trigger).toHaveFocus();
  expect(editor).toBeVisible();
  fireEvent.click(trigger);
  fireEvent.click(drawer, { clientX: -1, clientY: -1 });
  expect(trigger).toHaveFocus();
  expect(editor).toHaveValue("phone draft");
  resize(1280);
  expect(screen.getByRole("button", { name: "Session item" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Panel item" })).toBeVisible();
});
