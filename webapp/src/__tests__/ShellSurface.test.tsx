import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ShellSurface from "../components/ShellSurface";

it("dismisses only the innermost dialog on Escape", () => {
  const closeSessions = vi.fn();
  const closeFork = vi.fn();
  render(<ShellSurface visible presentation="left" label="Sessions" onClose={closeSessions}>
    <ShellSurface visible presentation="modal" label="Fork session" onClose={closeFork}>
      <button>Choose boundary</button>
    </ShellSurface>
  </ShellSurface>);
  fireEvent(screen.getByRole("dialog", { name: "Fork session", exact: true }), new Event("cancel", { cancelable: true }));
  expect(closeFork).toHaveBeenCalledOnce();
  expect(closeSessions).not.toHaveBeenCalled();
});
