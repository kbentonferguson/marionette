import { describe, expect, it } from "vitest";
import { jobDisplayTitle, looksLikeRawJobJson } from "../lib/jobDisplayTitle";

const provenance = JSON.stringify({
  cost_provenance: "provider",
  adapter: "agentic",
  role: "implement",
});

describe("jobDisplayTitle", () => {
  it("prefers a human goal or label", () => {
    expect(jobDisplayTitle({ goal: "Review auth", id: "job_abcdef012345" })).toBe("Review auth");
    expect(jobDisplayTitle({ label: "Native implement", goal: "Review auth" })).toBe("Native implement");
  });

  it("hides raw provenance JSON and falls back to role or kind", () => {
    expect(looksLikeRawJobJson(provenance)).toBe(true);
    expect(jobDisplayTitle({ goal: provenance, role: "implement" })).toBe("implement");
    expect(jobDisplayTitle({ goal: provenance, job_kind: "run_swarm" })).toBe("run swarm");
    expect(jobDisplayTitle({ goal: provenance, id: "job_abcdef012345" })).toBe("Job");
  });

  it("does not treat ordinary sentences as JSON", () => {
    expect(looksLikeRawJobJson("Review {auth} flow")).toBe(false);
    expect(jobDisplayTitle({ goal: "Review {auth} flow" })).toBe("Review {auth} flow");
  });
});
