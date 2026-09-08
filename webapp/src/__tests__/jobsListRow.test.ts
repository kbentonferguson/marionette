import { describe, expect, it } from "vitest";
import { isJobsListRow } from "../lib/jobMetadataContext";
import { isSwarmTrackerJob, isSwarmTrackerListRow } from "../lib/jobClassification";

describe("Jobs list and Swarm Tracker row filters", () => {
  it("hides command rows from the Jobs panel", () => {
    expect(isJobsListRow({ job_kind: "run_command", id: "local-cmd-1" })).toBe(false);
    expect(isJobsListRow({ job_kind: "run_command_batch", id: "local-cmdbatch-1" })).toBe(false);
    expect(isJobsListRow({ job_kind: "provider" })).toBe(false);
    expect(isJobsListRow({ job_kind: "run_swarm", id: "job_abc" })).toBe(true);
    expect(isJobsListRow({ job_kind: "run_implement", id: "local-impl-1" })).toBe(true);
  });

  it("hides command and wave-parent rows from Swarm Tracker", () => {
    expect(isSwarmTrackerJob({ job_kind: "run_command", id: "local-cmd-1" })).toBe(false);
    expect(isSwarmTrackerJob({ job_kind: "parallel_wave", id: "local-wave-1" })).toBe(false);
    expect(isSwarmTrackerJob({ job_kind: "run_swarm", id: "job_abc" })).toBe(true);
    expect(isSwarmTrackerJob({ job_kind: "provider", id: "local-cedfbf8c", adapter: "agentic" })).toBe(true);
    expect(isSwarmTrackerListRow({ job_kind: "provider", id: "local-cedfbf8c", adapter: "agentic" })).toBe(false);
    expect(isSwarmTrackerListRow({ job_kind: "run_implement", id: "local-impl-1" })).toBe(true);
  });
});
