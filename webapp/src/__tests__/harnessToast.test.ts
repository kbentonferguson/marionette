import { describe, expect, it } from "vitest";
import { toastDurationMs } from "../lib/harnessToast";

describe("toastDurationMs", () => {
  it("keeps error copy readable", () => {
    expect(toastDurationMs("Configured pilot DeepSeek is unavailable — using Luna.")).toBe(12000);
    expect(toastDurationMs("Model switch failed -- try again")).toBe(12000);
  });

  it("keeps routine notices short", () => {
    expect(toastDurationMs("Path copied")).toBe(4000);
  });
});
