/**
 * Typewriter pump helpers for streaming assistant deltas.
 * Conversation owns the timer handle; this module owns the per-tick math.
 *
 * Hermes measured 33ms as the floor that batches ~2 tokens per React
 * commit at typical 60 tok/s without visible lag (30 fps of text growth).
 * They use a timer, not rAF: Chromium parks rAF on hidden/minimized
 * renderers, so a finished answer sits queued until refocus. Visible
 * paints use rAF; hidden tabs keep the timeout fallback.
 */

import { typewriterCharsPerFrame } from "./streamBubbles";

/** Hidden-tab fallback only. Visible paints use rAF so ticks land on vsync. */
export const STREAM_PAINT_MS = 33;

type PaintHandle = { kind: "raf" | "timeout"; id: number };
const paintHandles = new Map<number, PaintHandle>();
let nextPaintToken = 1;

export function scheduleStreamPaint(cb: () => void): number {
  const token = nextPaintToken++;
  const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
  if (hidden || typeof requestAnimationFrame !== "function") {
    const id = window.setTimeout(() => {
      paintHandles.delete(token);
      cb();
    }, STREAM_PAINT_MS);
    paintHandles.set(token, { kind: "timeout", id });
    return token;
  }
  const id = requestAnimationFrame(() => {
    paintHandles.delete(token);
    cb();
  });
  paintHandles.set(token, { kind: "raf", id });
  return token;
}

export function cancelStreamPaint(id: number): void {
  const handle = paintHandles.get(id);
  if (!handle) return;
  paintHandles.delete(id);
  if (handle.kind === "raf") cancelAnimationFrame(handle.id);
  else clearTimeout(handle.id);
}

export type TypewriterRefs = {
  typeBufRef: { current: string };
  typeRafRef: { current: number | null };
  typeDoneRef: { current: boolean };
};

/** Reveal one live/done policy chunk from the buffer into React state. */
function takeTypewriterChunk(
  refs: TypewriterRefs,
  appendStreamingText: (chunk: string) => void,
): void {
  const buf = refs.typeBufRef.current;
  if (!buf) return;
  const perFrame = typewriterCharsPerFrame(buf.length, refs.typeDoneRef.current);
  if (perFrame <= 0) return;
  const take = buf.slice(0, perFrame);
  refs.typeBufRef.current = buf.slice(perFrame);
  appendStreamingText(take);
}

function scheduleTypewriterPump(
  refs: TypewriterRefs,
  appendStreamingText: (chunk: string) => void,
  schedule: (cb: () => void) => number,
): void {
  refs.typeRafRef.current = schedule(() =>
    pumpTypewriterFrame(refs, appendStreamingText, schedule),
  );
}

/** One animation frame: reveal backlog chars and schedule the next pump. */
export function pumpTypewriterFrame(
  refs: TypewriterRefs,
  appendStreamingText: (chunk: string) => void,
  schedule: (cb: () => void) => number,
): void {
  refs.typeRafRef.current = null;
  const buf = refs.typeBufRef.current;
  if (!buf) {
    if (!refs.typeDoneRef.current) {
      scheduleTypewriterPump(refs, appendStreamingText, schedule);
    }
    return;
  }
  takeTypewriterChunk(refs, appendStreamingText);
  if (refs.typeBufRef.current || !refs.typeDoneRef.current) {
    scheduleTypewriterPump(refs, appendStreamingText, schedule);
  }
}

export function startTypewriterLoop(
  refs: TypewriterRefs,
  appendStreamingText: (chunk: string) => void,
  schedule: (cb: () => void) => number,
): void {
  refs.typeDoneRef.current = false;
  if (refs.typeRafRef.current != null) {
    return;
  }
  if (refs.typeBufRef.current) {
    takeTypewriterChunk(refs, appendStreamingText);
  }
  scheduleTypewriterPump(refs, appendStreamingText, schedule);
}

export function flushTypewriterBuffer(
  refs: TypewriterRefs,
  appendStreamingText: (chunk: string) => void,
  cancel: (id: number) => void,
): void {
  refs.typeDoneRef.current = true;
  if (refs.typeBufRef.current) {
    appendStreamingText(refs.typeBufRef.current);
    refs.typeBufRef.current = "";
  }
  if (refs.typeRafRef.current != null) {
    cancel(refs.typeRafRef.current);
    refs.typeRafRef.current = null;
  }
}

/** Cancel the loop without flushing (session switch — hydrate owns the text). */
export function cancelTypewriterWithoutFlush(
  refs: TypewriterRefs,
  cancel: (id: number) => void,
): void {
  if (refs.typeRafRef.current != null) {
    cancel(refs.typeRafRef.current);
    refs.typeRafRef.current = null;
  }
  refs.typeBufRef.current = "";
  refs.typeDoneRef.current = false;
}
