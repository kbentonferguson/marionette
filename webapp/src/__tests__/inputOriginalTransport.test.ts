import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../lib/api';
import { getActiveDiagnostic, resetDiagnosticBus } from '../lib/operationalDiagnosticBus';
import { withDesktopEndpointDiscovery, withEndpointDiscovery } from './endpointFixture';

afterEach(() => { vi.unstubAllGlobals(); Reflect.deleteProperty(window, 'harnessIPC'); resetDiagnosticBus(); });
const submission = { original_text: '  literal @terminal:zsh:1\n\t', session_id: 'A', documents: [{ ref: 'input:A:doc', name: 'document.txt' }], retry_key: 'retry', input_id: 'exact', handoff_token: 'once' };
for (const mode of ['browser', 'native']) describe(mode, () => {
  const writes: { path: string; body: unknown }[] = [];
  const streams: string[] = [];
  function setup(status = 200, body: unknown = { ok: true }) {
    writes.length = 0; streams.length = 0;
    if (mode === 'browser') vi.stubGlobal('fetch', withEndpointDiscovery(async (input, options) => {
      const path = String(input);
      if (options?.method === 'POST') {
        writes.push({ path, body: JSON.parse(String(options.body)) });
        return Response.json(path.includes('/stash') ? { id: 'stashed' } : body, { status });
      }
      streams.push(path);
      return status === 200 ? new Response('data: {"kind":"done"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } }) : Response.json(body, { status });
    }));
    else Object.defineProperty(window, 'harnessIPC', { configurable: true, value: {
      endpointHeaders: true,
      requestJSON: withDesktopEndpointDiscovery(async (_method, path, requestBody) => {
        writes.push({ path, body: requestBody });
        return { kind: 'response', status, text: JSON.stringify(path.includes('/stash') ? { id: 'stashed' } : body), correlationId: '' };
      }),
      stream(path: string, _event: unknown, done: () => void, error: (e: unknown) => void) {
        streams.push(path);
        queueMicrotask(() => status === 200 ? done() : error({ status, body, ...typeof body === 'object' ? body : {} }));
        return () => {};
      },
    } });
  }
  it('sends explicit retained documents and stable admission identity on queue and steer', async () => {
    setup(); await api.queueAdd('  exact  ', ['input:A:image'], 'A', submission);
    await api.steerSession('  exact  ', ['input:A:image'], 'follow_up', { sessionId: 'A', ...submission });
    expect(writes[0].body).toMatchObject({ text: '  exact  ', images: ['input:A:image'], session_id: 'A', ...submission });
    expect(writes[1].body).toMatchObject({ text: '  exact  ', original_text: submission.original_text, documents: submission.documents, retry_key: 'retry', session_id: 'A' });
    await api.queueHandoff('exact', 'A'); expect(writes[2].body).toEqual({ handoff: 'exact', session_id: 'A' });
  });
  it.each(['chat', 'auto'])('%s carries one-use identity, documents and exact whitespace through short and stashed streams', async kind => {
    setup();
    for (const message of ['  exact\ntext  ', ' '.repeat(4500) + 'end']) {
      await new Promise<void>((resolve, reject) => kind === 'chat'
        ? api.chat(message, () => {}, resolve, reject, false, ['input:A:image'], submission)
        : api.auto(message, () => {}, resolve, reject, ['input:A:image'], submission));
      const query = new URL(streams.at(-1) || '', 'http://local').searchParams;
      expect(query.get('session_id')).toBe('A'); expect(query.get('input_id')).toBe('exact'); expect(query.get('handoff_token')).toBe('once'); expect(query.get('retry_key')).toBe('retry');
      if (message.length > 4000) {
        expect(writes.at(-1)?.body).toMatchObject({ message, ...submission });
        expect(query.get('documents')).toBeNull();
        expect(query.get('original_text')).toBeNull();
      } else {
        expect(query.get('original_text')).toBe(submission.original_text);
        expect(JSON.parse(query.get('documents') || 'null')).toEqual(submission.documents);
        expect(query.get(kind === 'chat' ? 'message' : 'objective')).toBe(message);
      }
    }
  });
  it.each(['chat', 'auto'])('%s stashes a large original even when delivery is short', async kind => {
    setup();
    const input = { ...submission, original_text: '  literal @terminal:zsh:1\n'.repeat(600) };
    await new Promise<void>((resolve, reject) => kind === 'chat'
      ? api.chat('small delivery', () => {}, resolve, reject, false, [], input)
      : api.auto('small delivery', () => {}, resolve, reject, [], input));
    expect(writes.at(-1)?.body).toEqual({ message: 'small delivery', images: [], ...input });
    const query = new URL(streams.at(-1) || '', 'http://local').searchParams;
    expect(query.get('mid')).toBe('stashed');
    expect(query.get('original_text')).toBeNull();
    expect(query.get('session_id')).toBe('A');
  });
  it.each(['chat', 'auto'])('%s preserves an explicit empty original', async kind => {
    setup();
    const input = { ...submission, original_text: '' };
    await new Promise<void>((resolve, reject) => kind === 'chat'
      ? api.chat('', () => {}, resolve, reject, false, ['input:A:image'], input)
      : api.auto('', () => {}, resolve, reject, ['input:A:image'], input));
    const query = new URL(streams.at(-1) || '', 'http://local').searchParams;
    expect(query.has('original_text')).toBe(true);
    expect(query.get('original_text')).toBe('');
  });
  it('keeps structured input failures local in JSON and streams but publishes unknown server errors', async () => {
    setup(503, { ok: false, code: 'input_commit_uncertain', error: 'Keep draft and inspect originals.' });
    await expect(api.queueAdd('draft', [], 'A', submission)).rejects.toMatchObject({ code: 'input_commit_uncertain' });
    expect(getActiveDiagnostic()).toBeNull();
    await new Promise<void>(resolve => api.chat('draft', () => {}, undefined, () => resolve(), false, [], submission));
    expect(getActiveDiagnostic()).toBeNull();
    setup(503, { error: 'Unexpected server failure', code: 'backend_unavailable' });
    await expect(api.queueAdd('draft', [], 'A')).rejects.toThrow(); expect(getActiveDiagnostic()?.severity).toBe('error');
  });
});
