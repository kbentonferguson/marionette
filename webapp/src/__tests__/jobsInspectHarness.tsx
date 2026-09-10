import { expect } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";

function rowToggle(root: HTMLElement) {
  return within(root).queryAllByRole("button").find((btn) => (
    btn.getAttribute("aria-expanded") != null && (btn.getAttribute("aria-label") || "").includes(" · ")
  ));
}

/** Expand the compact Jobs row and (for PM jobs) load selected artifacts. */
export function inspectHarnessJob(source: string, id: string) {
  const root = screen.getByTestId(`inspect-${source}-${id}`);
  const toggle = rowToggle(root);
  if (toggle && toggle.getAttribute("aria-expanded") === "false") fireEvent.click(toggle);
  const btn = within(root).getByRole("button", { name: "Inspect tasks and artifacts" });
  fireEvent.click(btn);
  return root;
}

export function expectNoDashboardHost() {
  expect(screen.queryByTestId("job-dashboard-host")).not.toBeInTheDocument();
}

/** Compatibility wrapper: inspection now lives on the Jobs row itself. */
export function JobsInspectHarness({ children }: { children?: React.ReactNode }) {
  return <>{children}</>;
}
