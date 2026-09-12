import { afterEach, describe, expect, it, vi } from "vitest";
import {
  STREAM_PAINT_MS,
  cancelStreamPaint,
  pumpTypewriterFrame,
  scheduleStreamPaint,
  streamPaintHandleCount,
} from "../components/conversation/streamTypewriter";

function refs(buf: string, done = false) {
  return {
    typeBufRef: { current: buf },
    typeRafRef: { current: null as number | null },
    typeDoneRef: { current: done },
  };
}

function setVisibility(state: "hidden" | "visible"): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("streamTypewriter scheduler", () => {
  afterEach(() => {
    setVisibility("visible");
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not reschedule when the buffer is empty and the turn is not done", () => {
    const r = refs("");
    let scheduled = 0;
    pumpTypewriterFrame(r, () => undefined, () => {
      scheduled += 1;
      return 1;
    });
    expect(scheduled).toBe(0);
    expect(r.typeRafRef.current).toBeNull();
  });

  it("converts a pending rAF to a timeout when the tab hides", () => {
    vi.useFakeTimers();
    const rafIds: number[] = [];
    let nextRaf = 1;
    const rafCbs = new Map<number, FrameRequestCallback>();
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      const id = nextRaf++;
      rafIds.push(id);
      rafCbs.set(id, cb);
      return id;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => {
      rafCbs.delete(id);
    });

    setVisibility("visible");
    let fired = 0;
    const token = scheduleStreamPaint(() => {
      fired += 1;
    });
    expect(rafCbs.size).toBe(1);
    expect(streamPaintHandleCount()).toBe(1);

    setVisibility("hidden");
    expect(rafCbs.size).toBe(0);
    expect(streamPaintHandleCount()).toBe(1);

    vi.advanceTimersByTime(STREAM_PAINT_MS);
    expect(fired).toBe(1);
    expect(streamPaintHandleCount()).toBe(0);
    cancelStreamPaint(token);
  });

  it("cancelStreamPaint drops the map entry", () => {
    vi.useFakeTimers();
    setVisibility("hidden");
    const token = scheduleStreamPaint(() => undefined);
    expect(streamPaintHandleCount()).toBe(1);
    cancelStreamPaint(token);
    expect(streamPaintHandleCount()).toBe(0);
    vi.advanceTimersByTime(STREAM_PAINT_MS);
  });
});
