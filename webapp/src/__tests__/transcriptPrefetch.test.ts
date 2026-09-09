import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import {
  clearTranscriptCache,
  peekTranscriptCache,
  writeTranscriptCache,
} from "../components/conversation/transcriptCache";
import {
  prefetchSessionTranscript,
  prefetchSessionTranscripts,
} from "../components/conversation/transcriptPrefetch";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: { ...actual.api, sessionTranscript: vi.fn() } };
});

beforeEach(() => {
  clearTranscriptCache();
  vi.clearAllMocks();
});

describe("prefetchSessionTranscript", () => {
  it("fills a cold cache from sessionTranscript", async () => {
    vi.mocked(api.sessionTranscript).mockResolvedValue({
      display: [{ type: "msg", role: "user", text: "hi" }],
    });
    await expect(prefetchSessionTranscript("sess-a")).resolves.toBe(true);
    expect(peekTranscriptCache("sess-a")?.length).toBeGreaterThan(0);
    expect(api.sessionTranscript).toHaveBeenCalledWith("sess-a");
  });

  it("no-ops on warm hit", async () => {
    writeTranscriptCache("sess-b", [
      { kind: "msg", msg: { role: "user", text: "cached" } },
    ] as any);
    await expect(prefetchSessionTranscript("sess-b")).resolves.toBe(false);
    expect(api.sessionTranscript).not.toHaveBeenCalled();
  });
});

describe("prefetchSessionTranscripts", () => {
  it("bounds work and skips warm ids", async () => {
    writeTranscriptCache("warm", [
      { kind: "msg", msg: { role: "user", text: "x" } },
    ] as any);
    vi.mocked(api.sessionTranscript).mockResolvedValue({
      display: [{ type: "msg", role: "user", text: "n" }],
    });
    await prefetchSessionTranscripts(["warm", "c1", "c2", "c3"], 2);
    expect(api.sessionTranscript).toHaveBeenCalledTimes(2);
  });
});
