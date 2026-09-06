import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { COMPACT_SHELL_WIDTH, useResponsiveShell } from "../lib/useResponsiveShell";

function resize(width: number) {
  act(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
  });
}
afterEach(cleanup);

describe("responsive shell transitions", () => {
  it("starts narrow with chat even when both desktop panels were saved open", () => {
    resize(697);
    const { result } = renderHook(() => useResponsiveShell(true, true));
    expect(result.current).toMatchObject({ compact: true, leftOpen: false, rightOpen: false, view: "chat" });
    act(() => result.current.setLeftOpen(true));
    expect(result.current).toMatchObject({ leftOpen: true, rightOpen: false });
    act(() => result.current.setRightOpen(true));
    expect(result.current).toMatchObject({ leftOpen: false, rightOpen: true });
    act(() => result.current.setRightOpen(v => !v));
    expect(result.current.view).toBe("chat");
    resize(1280);
    expect(result.current).toMatchObject({ compact: false, leftOpen: true, rightOpen: true });
  });

  it("restores desktop choices across repeated breakpoint crossings", () => {
    resize(1280);
    const { result } = renderHook(() => useResponsiveShell(true, false));
    act(() => result.current.setLeftOpen(false));
    act(() => result.current.setRightOpen(true));
    resize(COMPACT_SHELL_WIDTH - 1);
    expect(result.current.view).toBe("chat");
    act(() => result.current.setLeftOpen(true));
    resize(697);
    expect(result.current.view).toBe("left");
    resize(COMPACT_SHELL_WIDTH);
    expect(result.current).toMatchObject({ leftOpen: false, rightOpen: true });
    resize(697);
    expect(result.current).toMatchObject({ view: "chat", leftOpen: false, rightOpen: false });
  });
});
