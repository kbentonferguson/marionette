import type { InputDocument, InputReceipt } from "../../lib/api";
import type { ComposerAttachedImage } from "./composerAttachmentCache";

export class InputRetryKeys {
  private pending = new Map<string, { payload: string; key: string }>();

  forPayload(session: string, payload: unknown): string {
    const encoded = JSON.stringify(payload);
    const prior = this.pending.get(session);
    if (prior?.payload === encoded) return prior.key;
    const key = crypto.randomUUID();
    this.pending.set(session, { payload: encoded, key });
    return key;
  }

  accepted(session: string, key: string): void {
    if (this.pending.get(session)?.key === key) this.pending.delete(session);
  }

  copied(session: string): void { this.pending.delete(session); }
}

export function receiptDraft(receipt: InputReceipt, session: string): {
  text: string; images: ComposerAttachedImage[]; documents: InputDocument[];
} {
  if (receipt.attachments.some(a => !a.ref.startsWith(`input:${session}:`))) {
    throw new Error("This original contains attachments from another session.");
  }
  return {
    text: receipt.original_text,
    images: receipt.attachments.filter(a => a.kind === "image").map(a => ({ path: a.ref, name: a.name, previewUrl: "" })),
    documents: receipt.attachments.filter(a => a.kind === "document").map(a => ({ ref: a.ref, name: a.name })),
  };
}

export function requireImageCapacity(existing: number, incoming: number): void {
  if (existing + incoming > 8) throw new Error("Maximum 8 images per message. Remove images from the draft before copying this original.");
}
