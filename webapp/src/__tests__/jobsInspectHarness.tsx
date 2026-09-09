import { useState } from "react";
import { MetadataInspection } from "../components/MetadataJobs";
import { isPmDashboardJob } from "../lib/jobClassification";
import { metadataJobs, useSharedJobMetadata } from "../lib/jobMetadataContext";

/** Mount compact PM inspection beside the Jobs strip so existing worker/artifact
 *  tests keep a surface after PM rows embed the dashboard instead of expanding. */
export function JobsInspectHarness({ children }: { children?: React.ReactNode }) {
  const { state } = useSharedJobMetadata();
  const [revealed, setRevealed] = useState<string[]>([]);
  return (
    <>
      {children}
      {metadataJobs(state).filter(isPmDashboardJob).map((job) => {
        const key = job.metadata_key ?? job.id;
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
