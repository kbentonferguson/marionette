import { afterEach, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { getActiveDiagnostic, resetDiagnosticBus } from "../lib/operationalDiagnosticBus";

const handshake = JSON.stringify({ok:true,protocol_version:1,endpoint_id:"test-endpoint",boot_id:"test-boot",capabilities:["endpoint_fence_v1"]});

afterEach(() => { vi.unstubAllGlobals(); resetDiagnosticBus(); });

it.each([400, 409])("keeps schedule validation and fork conflicts local (%i)", async status => {
  vi.stubGlobal("fetch", async path => path === "/api/endpoint" ? new Response(handshake,{status:200}) : new Response('{"error":"Refresh the saved values"}', { status }));
  for (const request of [
    () => api.updateSchedule("schedule-a", { timezone: "Mars/Olympus", revision: 2 }),
    () => api.runScheduleNow("schedule-a", 2),
    () => api.forkSession({ session_id: "session-a", event_id: 2, revision: "old", request_id: "retry-a" }),
    () => api.approveCommand({ sessionId: "session-a", workspaceRoot: "/project", commandHash: "hash", actionId: "old-action", approvalId: "old-approval" }),
  ]) {
    await expect(request()).rejects.toMatchObject({ status, message: "Refresh the saved values" });
    expect(getActiveDiagnostic()).toBeNull();
  }
});

it("keeps real schedule service failures visible", async () => {
  vi.stubGlobal("fetch", async path => path === "/api/endpoint" ? new Response(handshake,{status:200}) : new Response('{"error":"Storage unavailable"}', { status: 500 }));
  await expect(api.updateSchedule("schedule-a", { revision: 2 })).rejects.toMatchObject({ status: 500 });
  expect(getActiveDiagnostic()?.severity).toBe("error");
});
