import { expect } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { MetadataInspection } from "../components/MetadataJobs";
import { metadataJobs, useSharedJobMetadata } from "../lib/jobMetadataContext";

function rowToggle(root: HTMLElement) {
  return within(root).queryAllByRole("button").find((btn) => (
    btn.getAttribute("aria-expanded") != null && (btn.getAttribute("aria-label") || "").includes(" · ")
  ));
}

/** Expand the compact Jobs row. Tracker no longer has an Inspect dump overlay. */
export function inspectHarnessJob(source: string, id: string) {
  const root = screen.getByTestId(`inspect-${source}-${id}`);
  const toggle = rowToggle(root);
  if (toggle && toggle.getAttribute("aria-expanded") === "false") fireEvent.click(toggle);
  const dump = screen.queryByTestId(`dump-${source}-${id}`);
  const inspect = dump
    ? within(dump).queryByRole("button", { name: /Inspect (tasks and artifacts|actions)/ })
    : screen.queryAllByRole("button", { name: /Inspect (tasks and artifacts|actions)/ })[0];
  if (inspect) fireEvent.click(inspect);
  return root;
}

/** Open the test-only dump inspector. Compact tracker no longer hosts these tabs. */
export function openDumpInspector(source?: string, id?: string) {
  const dump = source && id ? screen.queryByTestId(`dump-${source}-${id}`) : null;
  const inspect = dump
    ? within(dump).getByRole("button", { name: /Inspect (tasks and artifacts|actions)/ })
    : screen.getAllByRole("button", { name: /Inspect (tasks and artifacts|actions)/ })[0];
  fireEvent.click(inspect);
  return inspect;
}

export function expectNoDashboardHost() {
  expect(screen.queryByTestId("job-dashboard-host")).not.toBeInTheDocument();
}

/** Non-compact dump for tests that still assert inspector tabs. Compact tracker no longer hosts it. */
export function AllJobsInspectionDump() {
  const { state } = useSharedJobMetadata();
  return <>{metadataJobs(state).map((job) => (
    <div key={job.metadata_key ?? job.id} data-testid={`dump-${job.source}-${job.id}`}>
      <MetadataInspection job={job} deferAutoRead />
    </div>
  ))}</>;
}

/** Test wrapper: compact tracker plus dump inspector for suites that still assert tabs. */
export function JobsInspectHarness({ children }: { children?: React.ReactNode }) {
  return <>{children}<AllJobsInspectionDump /></>;
}
