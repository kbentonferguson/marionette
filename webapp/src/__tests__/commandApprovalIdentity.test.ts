import { withEndpointDiscovery } from "./endpointFixture";
import { describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { appendCommandApproval, sameCommandApproval, updateCommandApproval } from "../components/conversation/streamApply";
import { mergeTranscriptItems, transcriptResponseToItems } from "../components/conversation/transcriptItems";

const payload = {
  id: "action-1", action_id: "action-1", approval_protocol: 1,
  approval_id: "approval-old", command_hash: "a".repeat(64),
  command: "git push --force", session_id: "s", workspace_root: "/repo",
};

describe("approval identity fencing", () => {
  it("replaces a same-hash card and ignores delayed old decisions", () => {
    const initial = appendCommandApproval([], payload);
    const old = initial[0];
    if (old.kind !== "command_approval") throw new Error("missing card");
    const waiting = updateCommandApproval(initial, old, { status: "approving" });
    const current = appendCommandApproval(waiting, { ...payload, approval_id: "approval-new" });
    expect(current).toHaveLength(1);
    expect(current[0]).toMatchObject({ approvalId: "approval-new", status: "pending" });
    expect(sameCommandApproval(current[0], old)).toBe(false);
    expect(updateCommandApproval(current, old, { status: "approved" })).toEqual(current);
    expect(updateCommandApproval(current, old, { status: "error", error: "late rejection" })).toEqual(current);
  });

  it("replaces a hydrated same-hash card without inheriting its decision", () => {
    const old = appendCommandApproval([], payload);
    const fresh = transcriptResponseToItems({ display: [{ type: "command_approval", ...payload,
      approval_id: "approval-new", status: "pending" }] });
    expect(mergeTranscriptItems(old, fresh)).toMatchObject([{ approvalId: "approval-new", actionId: "action-1", status: "pending" }]);
  });
});

it("hydrates fresh approval identity even when extra local tool cards win", () => {
  const local = appendCommandApproval([], payload);
  const remote = transcriptResponseToItems({ display: [{ type: "command_approval", ...payload,
    approval_id: "approval-new", status: "pending" }] });
  const merged = mergeTranscriptItems([
    ...local,
    { kind: "card", card: { id: "extra", kind: "run_command", goal: "extra", running: true } },
  ], remote);
  expect(merged.find((item) => item.kind === "command_approval")).toMatchObject({ approvalId: "approval-new", status: "pending" });
});


it.each([
  ["approve", api.approveCommand],
  ["reject", api.rejectCommand],
  ["approve-amendment", api.approveCommandAmendment],
])("sends the exact displayed identity to %s", async (route, decide) => {
  const fetchRequest = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", withEndpointDiscovery(fetchRequest));
  try {
    await decide({ sessionId: "s", workspaceRoot: "/repo", commandHash: payload.command_hash,
      actionId: "action-1", approvalId: "approval-new" });
    expect(fetchRequest).toHaveBeenCalledWith(`/api/commands/${route}`, expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ session_id: "s", workspace_root: "/repo", command_hash: payload.command_hash,
        approval_protocol: 1, expected_action_id: "action-1", expected_approval_id: "approval-new" }),
    }));
  } finally {
    vi.unstubAllGlobals();
  }
});
