import { Compartment, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createInFileReviewExtension } from "../components/inFileReviewExtension";
import type { PendingReview } from "../lib/api";
import { collectInFilePendingHunks } from "../lib/inFileReview";

const review: PendingReview = {
  id: "review-editor", job_id: "job-editor", objective: "review", created_at: 1,
  files: [{ path: "alpha.txt", hunks: [
    { id: "0:0", decision_id: "first#0", header: "@@ -1,2 +1,2 @@", lines: [" keep", "-old", "+new"], status: "pending" },
    { id: "0:1", decision_id: "second#0", header: "@@ -4 +4 @@", lines: ["-last", "+changed"], status: "pending" },
  ] }, { path: "beta.txt", hunks: [
    { id: "1:0", decision_id: "third#0", header: "@@ -1 +1 @@", lines: ["-other", "+changed"], status: "pending" },
  ] }],
};
const hunks = collectInFilePendingHunks([review], "alpha.txt");
let view: EditorView | undefined;
let parent: HTMLDivElement;
afterEach(() => { view?.destroy(); view = undefined; parent?.remove(); });

function mount() {
  parent = document.createElement("div");
  document.body.appendChild(parent);
  const compartment = new Compartment();
  const handlers = { onAccept: vi.fn(), onReject: vi.fn(), applyingKey: null };
  view = new EditorView({ parent, state: EditorState.create({
    doc: "keep\nold\ngap\nlast",
    extensions: [compartment.of(createInFileReviewExtension(hunks, handlers))],
  }) });
  return { editor: view, compartment, handlers };
}
function buttons(action: "accept" | "reject") {
  return parent.querySelectorAll<HTMLButtonElement>(`[data-testid="infile-hunk-${action}"]`);
}
function keys() {
  return Array.from(parent.querySelectorAll("[data-hunk-key]"), el => el.getAttribute("data-hunk-key"));
}

describe("in-file review in a real EditorView", () => {
  it("mounts block controls and routes Accept/Reject to the selected stable hunk", () => {
    const { handlers } = mount();
    expect(keys()).toEqual(hunks.map(hunk => hunk.decisionKey));
    expect(parent.querySelectorAll(".cm-infile-hunk-del")).toHaveLength(2);
    buttons("accept")[0].click();
    buttons("reject")[1].click();
    expect(handlers.onAccept).toHaveBeenCalledExactlyOnceWith(hunks[0]);
    expect(handlers.onReject).toHaveBeenCalledExactlyOnceWith(hunks[1]);
  });

  it("refreshes same-key callbacks, busy state, and removes resolved widgets on reconfiguration", () => {
    const { editor, compartment, handlers } = mount();
    const freshHunks = collectInFilePendingHunks([{ ...review, objective: "refreshed" }], "alpha.txt");
    const freshHandlers = { onAccept: vi.fn(), onReject: vi.fn(), applyingKey: null };
    editor.dispatch({ effects: compartment.reconfigure(createInFileReviewExtension(freshHunks, freshHandlers)) });
    buttons("accept")[0].click();
    buttons("reject")[1].click();
    expect(freshHandlers.onAccept).toHaveBeenCalledExactlyOnceWith(freshHunks[0]);
    expect(freshHandlers.onReject).toHaveBeenCalledExactlyOnceWith(freshHunks[1]);
    expect(handlers.onAccept).not.toHaveBeenCalled();
    expect(handlers.onReject).not.toHaveBeenCalled();
    editor.dispatch({ effects: compartment.reconfigure(createInFileReviewExtension(freshHunks, { ...freshHandlers, applyingKey: freshHunks[0].decisionKey })) });
    expect(buttons("accept")[0].textContent).toBe("Applying…");
    for (const button of [...buttons("accept"), ...buttons("reject")]) {
      expect(button.disabled).toBe(true);
      button.click();
    }
    expect(freshHandlers.onAccept).toHaveBeenCalledTimes(1);
    expect(freshHandlers.onReject).toHaveBeenCalledTimes(1);
    editor.dispatch({ effects: compartment.reconfigure(createInFileReviewExtension(freshHunks.slice(1), freshHandlers)) });
    expect(keys()).toEqual([freshHunks[1].decisionKey]);
    expect(buttons("accept")[0].disabled).toBe(false);
    editor.dispatch({ effects: compartment.reconfigure(createInFileReviewExtension([], freshHandlers)) });
    expect(keys()).toEqual([]);
    expect(parent.querySelectorAll(".cm-infile-hunk-del")).toHaveLength(0);
  });

  it("rebuilds decorations after document replacement, including shared anchors, and destroys cleanly", () => {
    const { editor, handlers } = mount();
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: "short" } });
    expect(keys()).toEqual(hunks.map(hunk => hunk.decisionKey));
    editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: "keep\nold\ngap\nlast\nextra" } });
    expect(keys()).toEqual(hunks.map(hunk => hunk.decisionKey));
    expect(parent.querySelectorAll(".cm-infile-hunk-del")).toHaveLength(2);
    buttons("reject")[1].click();
    expect(handlers.onReject).toHaveBeenCalledExactlyOnceWith(hunks[1]);
    editor.destroy();
    view = undefined;
    expect(parent.childElementCount).toBe(0);
  });
});
