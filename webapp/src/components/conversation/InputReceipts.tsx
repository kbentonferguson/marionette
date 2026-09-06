import { ImageResource } from "./ImageResource";
import { imagePath } from "../../lib/transport";
import type { InputReceipt } from "../../lib/api";

const statusLabels = {
  accepted: "Saved",
  delivering: "Delivery started",
  injected: "Recorded in conversation",
  dropped: "Removed from delivery",
  uncertain: "Delivery uncertain",
} satisfies Record<InputReceipt["status"], string>;

export default function InputReceipts({ receipts, onCopy, sessionId }: {
  receipts: InputReceipt[];
  sessionId?: string;
  onCopy: (receipt: InputReceipt) => void;
}) {
  if (receipts.length === 0) return null;
  const heldCount = receipts.filter((receipt) => receipt.held && receipt.status !== "injected").length;
  return (
    <details className="mb-2 overflow-hidden rounded-xl border border-edge bg-panel2/40 text-xs leading-relaxed text-muted">
      <summary className="min-h-11 cursor-pointer px-3 py-2.5 font-medium text-txt focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent">
        Saved inputs · {receipts.length}{heldCount > 0 ? ` · ${heldCount} held for review` : ""}
      </summary>
      <div className="px-3 pb-3">
        <p className="mb-2 text-muted">
          Originals remain available after removal or interrupted delivery. Copying fills your draft; sending it is a new submission.
        </p>
        {[...receipts].reverse().map((receipt) => (
          <details key={receipt.id} className="border-t border-edge py-2">
            <summary className="min-h-11 cursor-pointer break-words py-2.5 text-txt focus-visible:outline-2 focus-visible:outline-accent">
              {statusLabels[receipt.status]}{receipt.held && receipt.status !== "injected" ? " · held for review" : ""}
              {" — "}{receipt.original_text.slice(0, 100) || "Attachments"}
            </summary>
            {receipt.status === "injected" && <p className="mt-2 text-muted">Recorded in local history. This does not confirm that the model or tools completed.</p>}
            {receipt.held && receipt.status !== "injected" && <p className="mt-2 text-muted">This input will not run automatically.</p>}
            <pre className="my-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-edge bg-panel px-3 py-2 font-[inherit] text-txt">{receipt.original_text}</pre>
            {receipt.attachments.map((attachment, index) => (
              <div key={`${attachment.ref}:${index}`} className="mb-2 break-words">
                {attachment.kind === "image" && sessionId && attachment.ref.startsWith(`input:${sessionId}:`) && <ImageResource src={imagePath(attachment.ref)} alt={attachment.name} loading="lazy" className="mb-2 aspect-square h-20 w-20 rounded-lg border border-edge bg-panel object-contain" />}
                <span>{attachment.name} · {attachment.byte_length.toLocaleString()} bytes</span>
                <details className="text-muted"><summary className="cursor-pointer py-1 text-faint hover:text-muted focus-visible:outline-2 focus-visible:outline-accent">Verify attachment</summary><p className="break-all">SHA-256: {attachment.sha256}</p></details>
              </div>
            ))}
            <button type="button" className="mt-2 inline-flex min-h-11 items-center rounded-lg border border-edge2 bg-panel px-3 text-txt hover:bg-panel2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" onClick={() => onCopy(receipt)}>
              Copy original to draft
            </button>
          </details>
        ))}
      </div>
    </details>
  );
}
