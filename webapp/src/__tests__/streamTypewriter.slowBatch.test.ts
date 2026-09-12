import { describe, expect, it } from "vitest";
import { pumpTypewriterFrame } from "../components/conversation/streamTypewriter";

function refs(buf: string) {
  return {
    typeBufRef: { current: buf },
    typeRafRef: { current: null as number | null },
    typeDoneRef: { current: false },
  };
}

describe("streamTypewriter slow-model batching", () => {
  it("paints a large burst as a catch-up slice, not the whole buffer", () => {
    const burst = "token ".repeat(40);
    const r = refs(burst);
    const painted: string[] = [];
    pumpTypewriterFrame(r, (chunk) => painted.push(chunk), () => {
      return 1;
    });
    expect(painted).toHaveLength(1);
    expect(painted[0].length).toBeGreaterThan(0);
    expect(painted[0].length).toBeLessThan(burst.length);
    expect(r.typeBufRef.current).toBe(burst.slice(painted[0].length));
  });
});
