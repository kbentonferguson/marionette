import { describe, expect, it, vi, afterEach } from "vitest";
import {
  buildDashboardEmbedUrl,
  JOBS_DASHBOARD_EXPAND_MIN_PX,
  JOBS_DASHBOARD_FOCUS_MIN_PX,
  REQUEST_RIGHT_MIN_WIDTH_EVENT,
  requestRightMinWidth,
} from "../lib/jobsDashboard";

describe("jobsDashboard URLs", () => {
  it("always asks for embed=1 and keeps the job query", () => {
    expect(buildDashboardEmbedUrl("127.0.0.1", 8787, "job_abcdef012345")).toBe(
      "http://127.0.0.1:8787/?job=job_abcdef012345&embed=1",
    );
    expect(buildDashboardEmbedUrl("127.0.0.1", 8790)).toBe("http://127.0.0.1:8790/?embed=1");
  });
});

describe("requestRightMinWidth", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("asks the shell to grow the Jobs pane for a focused dashboard", () => {
    const spy = vi.spyOn(window, "dispatchEvent");
    requestRightMinWidth(JOBS_DASHBOARD_FOCUS_MIN_PX);
    const event = spy.mock.calls[0]?.[0] as CustomEvent<{ minPx: number }>;
    expect(event.type).toBe(REQUEST_RIGHT_MIN_WIDTH_EVENT);
    expect(event.detail.minPx).toBe(JOBS_DASHBOARD_FOCUS_MIN_PX);
    expect(JOBS_DASHBOARD_EXPAND_MIN_PX).toBeGreaterThan(JOBS_DASHBOARD_FOCUS_MIN_PX);
  });
});
