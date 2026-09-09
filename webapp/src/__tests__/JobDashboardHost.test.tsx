import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import JobDashboardHost from "../components/JobDashboardHost";
import { api, type Job } from "../lib/api";
import { openAgentUrlExternal } from "../lib/agentLinks";
import { JOBS_DASHBOARD_EXPAND_MIN_PX, REQUEST_RIGHT_MIN_WIDTH_EVENT } from "../lib/jobsDashboard";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: { ...actual.api, dashboard: vi.fn() } };
});

vi.mock("../lib/agentLinks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/agentLinks")>();
  return { ...actual, openAgentUrlExternal: vi.fn() };
});

const job: Job = {
  id: "job_abcdef012345",
  goal: "Review auth",
  status: "running",
  source: "harness",
  job_ref: { job_id: "job_abcdef012345", state_id: "store-A" },
};

describe("JobDashboardHost", () => {
  afterEach(() => { vi.clearAllMocks(); });

  it("embeds the located dashboard and grows the Jobs pane", async () => {
    const grow = vi.fn();
    window.addEventListener(REQUEST_RIGHT_MIN_WIDTH_EVENT, grow);
    vi.mocked(api.dashboard).mockResolvedValue({
      ok: true,
      reused: true,
      host: "127.0.0.1",
      port: 8787,
      url: "http://127.0.0.1:8787/?job=job_abcdef012345&embed=1",
      embed_url: "http://127.0.0.1:8787/?job=job_abcdef012345&embed=1",
    });
    const onClose = vi.fn();
    render(<JobDashboardHost job={job} onClose={onClose} />);
    expect(await screen.findByTitle("Puppetmaster dashboard job_abcdef012345")).toHaveAttribute(
      "src",
      "http://127.0.0.1:8787/?job=job_abcdef012345&embed=1",
    );
    expect(screen.getByText("Review auth")).toBeInTheDocument();
    expect(grow).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Expand/ }));
    const expand = grow.mock.calls.find((call) => (
      (call[0] as CustomEvent<{ minPx: number }>).detail.minPx === JOBS_DASHBOARD_EXPAND_MIN_PX
    ));
    expect(expand).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Pop out/ }));
    expect(openAgentUrlExternal).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/?job=job_abcdef012345&embed=1",
    );
    fireEvent.click(screen.getByRole("button", { name: /Close/ }));
    expect(onClose).toHaveBeenCalled();
    window.removeEventListener(REQUEST_RIGHT_MIN_WIDTH_EVENT, grow);
  });

  it("keeps Marionette chrome when locate fails", async () => {
    vi.mocked(api.dashboard).mockResolvedValue({
      ok: false,
      error: "state_dir_unavailable",
      detail: "No Puppetmaster project store for this workspace.",
    });
    render(<JobDashboardHost job={job} onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/No Puppetmaster project store/);
    expect(screen.queryByTestId("job-dashboard-frame")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pop out/ })).toBeDisabled();
  });
});
