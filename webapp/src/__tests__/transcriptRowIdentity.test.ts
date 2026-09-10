import { describe, expect, it } from "vitest";
import { stableItemKey, type Item } from "../components/TranscriptList";
import { transcriptResponseToItems } from "../components/conversation/transcriptItems";
import {
  allocateOptimisticInputId,
  durableMessageId,
  messageBlockId,
  optimisticUserEchoMsg,
  ordinalMessageId,
  stampTranscriptMessageIds,
  transcriptBlockRowId,
  withLiveMessageId,
} from "../components/conversation/transcriptRowIdentity";

describe("transcriptRowIdentity", () => {
  it("uses input_id as the optimistic echo and persist id", () => {
    const inputId = "aabbccddeeff00112233445566778899";
    const echo = optimisticUserEchoMsg({ text: "hello", id: inputId });
    const live: Item[] = [{ kind: "msg", msg: echo }];
    const hydrated = transcriptResponseToItems({
      display: [{ type: "message", role: "user", text: "hello", input_id: inputId }],
      session_id: "sess-1",
    }, "sess-1");
    expect(hydrated[0]).toMatchObject({ kind: "msg", msg: { id: inputId, text: "hello" } });
    expect(stableItemKey(live[0]!, 0)).toBe(stableItemKey(hydrated[0]!, 0));
    expect(stableItemKey(live[0]!, 0)).toBe(transcriptBlockRowId(inputId, "body"));
  });

  it("stamps ordinal ids so live assistant rows match cold hydrate", () => {
    const live = stampTranscriptMessageIds([
      { kind: "msg", msg: { role: "user", text: "q" } },
      { kind: "msg", msg: { role: "assistant", text: "a" } },
    ], "sess-1");
    const hydrated = transcriptResponseToItems({
      display: [
        { type: "message", role: "user", text: "q" },
        { type: "message", role: "assistant", text: "a" },
      ],
    }, "sess-1");
    expect(live[1]?.kind === "msg" && live[1].msg.id).toBe(ordinalMessageId("sess-1", "assistant", 0));
    expect(stableItemKey(live[1]!, 1)).toBe(stableItemKey(hydrated[1]!, 1));
    expect(stableItemKey(live[1]!, 1)).toBe(
      transcriptBlockRowId(ordinalMessageId("sess-1", "assistant", 0), "body"),
    );
  });

  it("namespaces ids by session so a cold swap cannot reuse the prior row", () => {
    const a = stampTranscriptMessageIds(
      [{ kind: "msg", msg: { role: "user", text: "same" } }],
      "sess-a",
    );
    const b = stampTranscriptMessageIds(
      [{ kind: "msg", msg: { role: "user", text: "same" } }],
      "sess-b",
    );
    expect(stableItemKey(a[0]!, 0)).not.toBe(stableItemKey(b[0]!, 0));
  });

  it("keeps worker/progress blocks on distinct ids under the same message", () => {
    expect(messageBlockId({ workerStream: true })).toBe("worker");
    expect(messageBlockId({ channel: "progress" })).toBe("progress");
    const msg = withLiveMessageId([], {
      role: "assistant",
      text: "…",
      workerStream: true,
    }, "sess-1");
    expect(transcriptBlockRowId(msg.id || "", messageBlockId(msg))).toMatch(/#worker$/);
  });

  it("prefers explicit / input ids over ordinals", () => {
    expect(durableMessageId({
      explicitId: "kept",
      inputId: "ignored",
      sessionId: "s",
      role: "user",
      ordinal: 3,
    })).toBe("kept");
    expect(allocateOptimisticInputId().length).toBeGreaterThan(8);
  });
});
