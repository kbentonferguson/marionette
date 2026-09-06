/** Deterministic decisions for terminal stream lifecycle frames. */
export type TerminalBareOnDoneAction = "noop" | "mark_exited" | "reattach";
export type TerminalStreamEvent =
  | { kind: "gap"; offset: number; reason: "trimmed" | "cursor_ahead" | "invalid_cursor" }
  | { kind: "observation"; offset?: number }
  | { kind: "data"; b64: string; offset?: number }
  | { kind: "process_exit"; offset?: number; error?: string }
  | { kind: "missing_session"; offset?: number; error?: string }
  | { kind: "stream_error"; offset?: number; error?: string }
  | { kind: "legacy_exit"; offset?: number; error?: string }
  | { kind: "unknown"; offset?: number };

const MAX_NOTICE = 240;

/** Decode both the old kind:exit frame and the new explicit PTY lifecycle frames. */
export function decodeTerminalStreamEvent(value: unknown): TerminalStreamEvent {
  if (!value || typeof value !== "object") return { kind: "unknown" };
  const raw = value as Record<string, unknown>;
  const kind = typeof raw.kind === "string" ? raw.kind : "";
  const offset = typeof raw.offset === "number" && Number.isSafeInteger(raw.offset) && raw.offset >= 0 ? raw.offset : undefined;
  const error = typeof raw.error === "string" ? raw.error : undefined;
  if (kind === "gap" && offset !== undefined && (raw.reason === "trimmed" || raw.reason === "cursor_ahead" || raw.reason === "invalid_cursor")) return { kind, offset, reason: raw.reason };
  if (kind === "observation" && raw.state === "unknown") return { kind, offset };
  if (kind === "exit" && (raw.reason === "stream_error" || raw.reason === "missing_session" || raw.reason === "process_exit")) {
    return { kind: raw.reason, offset, error };
  }
  if (kind === "data" && typeof raw.b64 === "string") return { kind, b64: raw.b64, offset };
  if (kind === "process_exit" || kind === "exit") return { kind: kind === "exit" ? "legacy_exit" : kind, offset, error };
  if (kind === "missing_session") return { kind, offset, error };
  if (kind === "stream_error") return { kind, offset, error };
  return { kind: "unknown", offset };
}

/** Only backend-redacted text is displayed, and never without a hard bound. */
export function terminalNotice(error?: string): string {
  if (!error) return "";
  return error.slice(0, MAX_NOTICE);
}

export function terminalMissingSessionAction(alreadyRecovered: boolean): "auto_recover" | "mark_exited" {
  return alreadyRecovered ? "mark_exited" : "auto_recover";
}

export function terminalStreamPath(sid: string, startOffset = 0): string {
  const offset = Number.isFinite(startOffset) ? Math.max(0, Math.floor(startOffset)) : 0;
  const params = new URLSearchParams({ id: sid });
  if (offset > 0) params.set("offset", String(offset));
  return `/api/terminal/stream?${params.toString()}`;
}

export function terminalBareOnDoneAction(opts: {
  disposed: boolean; sawExit: boolean; hasSession: boolean; sawOutput: boolean; autoRecovered: boolean;
}): TerminalBareOnDoneAction {
  if (opts.disposed) return "noop";
  if (opts.sawExit) return "mark_exited";
  if (!opts.hasSession) return "mark_exited";
  return "reattach";
}

export type TerminalObservation = "unknown" | "active_output" | "stale" | "exited";

export function terminalObservationLabel(state: TerminalObservation, observedAt: number, now: number): string {
  if (state === "exited") return "exited";
  if (state === "stale" || now - observedAt > 5000) return "observation stale";
  if (state === "active_output" && now - observedAt < 1000) return "active output";
  return "unknown";
}

export function terminalEventIsCurrent(raw: unknown, sid: string, attachmentCurrent: boolean): boolean {
  if (!attachmentCurrent || !raw || typeof raw !== "object") return false;
  return !("id" in raw) || raw.id === sid;
}
