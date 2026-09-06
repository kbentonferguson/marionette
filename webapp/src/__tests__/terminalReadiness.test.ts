import { describe, expect, it } from "vitest";
import { decodeTerminalStreamEvent, terminalBareOnDoneAction, terminalEventIsCurrent, terminalObservationLabel } from "../components/terminalStreamPolicy";

describe('terminal observation evidence', () => {
  it('does not turn stream errors into process exits', () => {
    expect(decodeTerminalStreamEvent({kind: 'exit', reason: 'stream_error'}).kind).toBe('stream_error');
    expect(decodeTerminalStreamEvent({kind: 'exit', reason: 'missing_session'}).kind).toBe('missing_session');
  });
  it('keeps a delayed startup alive across a stream drop', () => {
    expect(terminalBareOnDoneAction({disposed: false, sawExit: false, hasSession: true, sawOutput: false, autoRecovered: false})).toBe('reattach');
  });
  it('rejects events from a replaced process or attachment', () => {
    expect(terminalEventIsCurrent({id:'old'}, 'new', true)).toBe(false);
    expect(terminalEventIsCurrent({id:'new'}, 'new', false)).toBe(false);
    expect(terminalEventIsCurrent({id:'new'}, 'new', true)).toBe(true);
  });
  it('distinguishes output, unknown and stale without claiming readiness', () => {
    expect(terminalObservationLabel('active_output', 1000, 1500)).toBe('active output');
    expect(terminalObservationLabel('active_output', 1000, 2500)).toBe('unknown');
    expect(terminalObservationLabel('unknown', 1000, 7000)).toBe('observation stale');
    expect(terminalObservationLabel('exited', 1000, 7000)).toBe('exited');
  });
});
