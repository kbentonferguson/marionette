import { describe, expect, it } from "vitest";
import { transcriptResponseToItems } from "../components/conversation/transcriptItems";

describe("history-only prefix seeded by backend hydration", () => {
  const history = [
    { role: "system", content: "private system instructions" },
    { role: "user", content: "Review the patch" },
    { role: "assistant", content: "The patch is ready.", phase: "final_answer" },
  ];
  const prefix = [
    { type: "message", role: "user", text: "Review the patch" },
    { type: "message", role: "assistant", text: "The patch is ready.", phase: "final_answer" },
  ];

  it("retains the original visible prefix exactly once after the first approval and reload", () => {
    const before = transcriptResponseToItems({ history });
    const payload = {
      history,
      display: [...prefix, {
        type: "command_approval", command_hash: "a".repeat(64),
        command: "echo approval", action_id: "approval", status: "pending",
      }],
    };
    const reloaded = transcriptResponseToItems(JSON.parse(JSON.stringify(payload)));
    expect(reloaded.filter(item => item.kind === "msg")).toEqual(before);
    expect(reloaded.filter(item => item.kind === "command_approval")).toHaveLength(1);
    expect(reloaded).toHaveLength(3);
  });

  it("keeps seeded prefix once when the next turn creates display messages", () => {
    const items = transcriptResponseToItems({ history, display: [
      ...prefix,
      { type: "message", role: "user", text: "Continue" },
      { type: "message", role: "assistant", text: "Completed the next step." },
    ] });
    expect(items).toHaveLength(4);
    expect(items.filter(item => item.kind === "msg" && item.msg.text === "Review the patch")).toHaveLength(1);
  });
});
