import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InputReceipt } from "../lib/api";
import InputReceipts from "../components/conversation/InputReceipts";

const original: InputReceipt = {
  id: "original-a",
  original_text: "  Keep the original spacing.\nSecond line.  ",
  attachments: [{ ref: "input:A:digest", kind: "document", name: "notes.txt", byte_length: 12, sha256: "digest" }],
  model: "pilot",
  payload_digest: "payload",
  created_at: 1,
  status: "uncertain",
  reason: "interrupted",
  held: true,
};

describe("retained input inspection", () => {
  it("copies the exact original and retained attachment metadata only after a click", () => {
    const onCopy = vi.fn();
    render(<InputReceipts receipts={[original]} onCopy={onCopy} />);
    fireEvent.click(screen.getByText("Saved inputs · 1 · 1 held for review"));
    fireEvent.click(screen.getByText(/Delivery uncertain · held for review/));
    expect(screen.getByText("This input will not run automatically.")).toBeTruthy();
    expect(screen.getByText(/SHA-256: digest/)).toBeTruthy();
    expect(onCopy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Copy original to draft" }));
    expect(onCopy).toHaveBeenCalledExactlyOnceWith(original);
  });

  it("distinguishes history publication from completed execution", () => {
    render(<InputReceipts receipts={[{ ...original, status: "injected", held: false }]} onCopy={vi.fn()} />);
    expect(screen.getByText(/This does not confirm that the model or tools completed/)).toBeTruthy();
    expect(screen.queryByText(/held for review/)).toBeNull();
  });
});
