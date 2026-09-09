import { useState } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { MetadataInspection } from "../components/MetadataJobs";
import { isPmDashboardJob } from "../lib/jobClassification";
import { metadataJobs, useSharedJobMetadata } from "../lib/jobMetadataContext";

/** Click Inspect for a PM job without selecting the Jobs row
 *  (row click hosts the dashboard and replaces the list). */
export function inspectHarnessJob(source: string, id: string) {
  const root = screen.getByTestId(`inspect-${source}-${id}`);
  const btn = within(root).queryByRole("button", { name: "Inspect tasks and artifacts" });
  if (btn) fireEvent.click(btn);
  return root;
}

/** Compact PM inspection beside the Jobs strip so worker/artifact tests
 *  keep a surface after PM rows embed the dashboard instead of expanding. */
export function JobsInspectHarness({ children }: { children?: React.ReactNode }) {
  const { state } = useSharedJobMetadata();
  const [revealed, setRevealed] = useState<string[]>([]);
  return (
    <>
      {children}
      {metadataJobs(state).filter(isPmDashboardJob).map((job) => {
        const key = job.metadata_key ?? `${job.source}-${job.id}`;
        return (
          <div key={key} data-testid={`inspect-${job.source}-${job.id}`} data-inspect-source={job.source}>
            <MetadataInspection
              job={job}
              compact
              revealed={revealed.includes(key)}
              onReveal={() => setRevealed((prev) => (prev.includes(key) ? prev : [...prev, key]))}
            />
          </div>
        );
      })}
    </>
  );
}
