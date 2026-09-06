import type { QueueRecovery } from "../../lib/api";

export default function QueueRecoveryNotice({ entries, onCopy }: {
  entries: QueueRecovery[];
  onCopy?: (text: string) => void;
}) {
  return <>{entries.map((entry) => (
    <details key={entry.path} className="mb-2 text-xs">
      <summary>{entry.kind === "legacy" ? "Unassigned legacy prompts" : "Prompt queue needs recovery"}</summary>
      <p>Original file retained. This content will not run automatically. Review it before sending.</p>
      <p>{entry.path}</p>
      {entry.content === null ? <p>File could not be read. Restore read access to inspect it.</p> : <>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap">{entry.content}</pre>
        <button type="button" disabled={!onCopy} onClick={() => onCopy?.(entry.content ?? "")}>Copy to composer for review</button>
      </>}
    </details>
  ))}</>;
}
