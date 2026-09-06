import { withEndpointDiscovery } from "./endpointFixture";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type PendingReview } from "../lib/api";
import { applyInFileHunkDecision } from "../lib/inFileReview";

const review: PendingReview = {
  id: "review", job_id: "job", objective: "scope", created_at: 1,
  files: ["a.txt", "b.txt"].map((path) => ({
    path,
    hunks: [{ id: path, decision_id: path, header: "@@ -1 +1 @@",
      lines: ["-before", "+after"], status: "pending" }],
  })),
};

afterEach(() => vi.unstubAllGlobals());

describe("in-file decisions through API transport", () => {
  it.each(["accept", "reject"] as const)("serializes selected scope for %s", async (decision) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", withEndpointDiscovery(fetchMock));
    await applyInFileHunkDecision(review, "a.txt", decision);
    expect(fetchMock).toHaveBeenCalledWith("/api/reviews/apply", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ id: "review", decisions: { "a.txt": decision }, scope: "selected" }),
    }));
  });

  it("keeps explicit whole-review scope for the review pane", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", withEndpointDiscovery(fetchMock));
    await api.applyReview("review", { "a.txt": "accept", "b.txt": "reject" });
    expect(fetchMock).toHaveBeenCalledWith("/api/reviews/apply", expect.objectContaining({
      body: JSON.stringify({ id: "review", decisions: { "a.txt": "accept", "b.txt": "reject" }, scope: "review" }),
    }));
  });
});
