import { withEndpointDiscovery, withDesktopEndpointDiscovery } from "./endpointFixture";
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../lib/api';
import { getJSON } from '../lib/transport';
import { getActiveDiagnostic, resetDiagnosticBus } from '../lib/operationalDiagnosticBus';
import { useOperationalDiagnostic } from '../lib/useOperationalDiagnostic';
import ConversationHeader from '../components/conversation/ConversationHeader';

function Header({ sessionId }: { sessionId: string }) {
  const diag = useOperationalDiagnostic({ sessionId });
  return <ConversationHeader pillStatus={diag?.severity === 'error' ? 'error' : 'idle'}
    detail={diag?.summary} correlationId={diag?.correlationId}
    recoveryAction={diag ? { label: 'Retry', onClick() {} } : undefined} />;
}
afterEach(() => { cleanup(); resetDiagnosticBus(); vi.unstubAllGlobals(); Reflect.deleteProperty(window, 'harnessIPC'); });
const ready = (session_id: string) => ({ available: true, session_id, total: 15, limit: 100, categories: [] });
for (const mode of ['web', 'desktop']) describe(mode, () => {
  function respond(status: number, body: unknown, wait = Promise.resolve()) {
    const handler = vi.fn(async (..._args: unknown[]) => {
      await wait;
      return { kind: 'response' as const, status, text: JSON.stringify(body), correlationId: 'usage-trace' };
    });
    if (mode === 'web') vi.stubGlobal('fetch', withEndpointDiscovery(async (...args: Parameters<typeof fetch>) => {
      const response = await handler(...args);
      return new Response(response.text, { status, headers: { 'X-Correlation-Id': response.correlationId } });
    }));
    else Object.defineProperty(window, 'harnessIPC', { configurable: true, value: { endpointHeaders: true, requestJSON: withDesktopEndpointDiscovery(handler) } });
    return handler;
  }
  it('returns unavailable without fabricated meters, then the real ready payload', async () => {
    const unavailable = { available: false, session_id: 'A', reason: 'building' };
    respond(200, unavailable);
    expect(await api.getContextUsage('A')).toEqual(unavailable);
    expect(getActiveDiagnostic()).toBeNull();
    respond(200, ready('A'));
    expect(await api.getContextUsage('A')).toEqual(ready('A'));
    expect(getActiveDiagnostic()).toBeNull();
  });
  it('scopes a late failure to the requested session, then clears its successful retry', async () => {
    let release = () => {};
    const held = new Promise<void>(resolve => { release = resolve; });
    const request = respond(500, { error: 'real usage failure' }, held);
    const view = render(<Header sessionId="A" />);
    const pending = api.getContextUsage('A');
    await waitFor(() => expect(request).toHaveBeenCalledOnce());
    view.rerender(<Header sessionId="B" />);
    await act(async () => { release(); await expect(pending).rejects.toMatchObject({ status: 500 }); });
    expect(JSON.stringify(request.mock.calls)).toContain('/api/context/usage?session_id=A');
    expect(getActiveDiagnostic()).toMatchObject({ sessionId: 'A', operation: 'context_usage' });
    expect(screen.queryByText('Error')).toBeNull();
    view.rerender(<Header sessionId="A" />);
    expect(screen.getByText('Error')).toBeTruthy();
    respond(200, ready('A'));
    await act(async () => { await api.getContextUsage('A'); });
    expect(getActiveDiagnostic()).toBeNull();
    expect(screen.queryByText('Retry')).toBeNull();
  });
  it('preserves genuine failure on unavailable, malformed, or other-session responses', async () => {
    respond(500, { error: 'real failure' });
    await expect(api.getContextUsage('A')).rejects.toThrow();
    const prior = getActiveDiagnostic();
    for (const body of [ { available: false, reason: 'building', session_id: 'A' }, { available: true, session_id: 'A' }, ready('B') ]) {
      respond(200, body);
      await api.getContextUsage('A');
      expect(getActiveDiagnostic()).toBe(prior);
    }
    respond(200, ready('B'));
    await api.getContextUsage('B');
    expect(getActiveDiagnostic()).toBe(prior);
  });
  it('does not clear a newer failure or an unrelated endpoint failure', async () => {
    respond(500, { error: 'first' });
    await expect(api.getContextUsage('A')).rejects.toThrow();
    let release = () => {};
    const held = new Promise<void>(resolve => { release = resolve; });
    const request = respond(200, ready('A'), held);
    const pending = api.getContextUsage('A');
    await waitFor(() => expect(request).toHaveBeenCalledOnce());
    respond(500, { error: 'newer' });
    await expect(api.getContextUsage('A')).rejects.toThrow();
    const newer = getActiveDiagnostic();
    release(); await pending;
    expect(getActiveDiagnostic()).toBe(newer);
    await expect(getJSON('/api/session/state?session_id=A')).rejects.toThrow();
    const other = getActiveDiagnostic();
    respond(200, ready('A'));
    await api.getContextUsage('A');
    expect(getActiveDiagnostic()).toBe(other);
  });
});
