import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { JobMetadataClient, metadataSelectionKey } from '../lib/jobMetadata';
import { JobMetadataStore } from '../lib/useJobMetadata';
import { context, detail, handshake, list, response, selection, token, view } from './jobMetadata.fixtures';

let store: JobMetadataStore;
let request: ReturnType<typeof vi.fn<(path: string, init?: RequestInit) => Promise<Response>>>;

async function open() {
  store.setTarget(context);
  expect(await store.readView()).toBe('applied');
}

function partialPage(cursor: string) {
  return { outcome: 'partial' as const, revision: 20, checkpoint: 0, scanned: 51, next_cursor: cursor };
}

function metadataUrl(path: unknown): URL {
  return new URL(String(path), 'http://local');
}

beforeEach(() => {
  Reflect.deleteProperty(window, 'harnessIPC');
  request = vi.fn(async (path: string) => path === '/api/endpoint' ? response(handshake) : path.endsWith('/view') ? response(view()) : response(list()));
  vi.stubGlobal('fetch', request);
  store = new JobMetadataStore(new JobMetadataClient(1000));
});
afterEach(() => { store.dispose(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it('invalidate retains metadata streams and observations; same-generation adopt keeps traversal', async () => {
  await open();
  const cursor = token(11);
  request.mockResolvedValue(response({ ...list([]), page: partialPage(cursor) }));
  await store.advance();
  const before = store.getSnapshot();
  expect(before.streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });
  expect(before.observations).toEqual([]);

  store.invalidate();
  const mid = store.getSnapshot();
  expect(mid.view).toMatchObject({ kind: 'target', reason: 'invalidated' });
  expect(mid.streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });
  expect(mid.headers).toEqual(before.headers);
  expect(mid.pins).toEqual(before.pins);
  expect(mid.detailCache).toEqual(before.detailCache);

  request.mockResolvedValue(response(view()));
  expect(await store.readView()).toBe('applied');
  expect(store.getSnapshot().streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });
  expect(store.getSnapshot().view.kind).toBe('view');
});

it('same-target setTarget retains metadata stream traversal like invalidate', async () => {
  await open();
  const cursor = token(12);
  request.mockResolvedValue(response({ ...list([]), page: partialPage(cursor) }));
  await store.advance();
  expect(store.getSnapshot().streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });

  store.setTarget(context);
  expect(store.getSnapshot().view).toMatchObject({ kind: 'target', reason: 'not_opened' });
  expect(store.getSnapshot().streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });

  request.mockResolvedValue(response(view()));
  expect(await store.readView()).toBe('applied');
  expect(store.getSnapshot().streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });
});

it('liveOnly continues a partial metadata stream cursor across invalidate+readView', async () => {
  await open();
  const cursor = token(13);
  request.mockImplementation(async (path: string) => {
    if (path === '/api/endpoint') return response(handshake);
    if (String(path).endsWith('/view')) return response(view());
    const status = metadataUrl(path).searchParams.get('status');
    if (status === 'running') {
      return response({
        ...list([]),
        store: { source: 'harness', state_id: 'store-A' },
        mode: 'snapshot',
        page: partialPage(cursor),
      });
    }
    if (status === null) {
      return response({
        ...list([]),
        store: { source: 'harness', state_id: 'store-A' },
        mode: metadataUrl(path).searchParams.get('mode') ?? 'snapshot',
      });
    }
    return response({
      ...list([]),
      store: { source: 'harness', state_id: 'store-A' },
      mode: 'snapshot',
      page: { outcome: 'unavailable', revision: 0, scanned: 0, checkpoint: 0, next_cursor: null },
    });
  });

  for (let i = 0; i < 24; i++) {
    await store.advance();
    const streams = store.getSnapshot().streams;
    const running = streams.find(s => s.stream.status === 'running');
    const otherActiveOpen = streams.some(s => s.stream.status !== null && s.stream.status !== 'running' && s.state !== 'unavailable');
    if (running?.state === 'partial' && !otherActiveOpen) break;
  }
  expect(store.getSnapshot().streams.find(s => s.stream.status === 'running')).toMatchObject({
    state: 'partial',
    traversal: { cursor },
  });

  store.invalidate();
  request.mockImplementation(async (path: string) => {
    if (path === '/api/endpoint') return response(handshake);
    if (String(path).endsWith('/view')) return response(view());
    const status = metadataUrl(path).searchParams.get('status');
    if (status === 'running') {
      return response({
        ...list([]),
        store: { source: 'harness', state_id: 'store-A' },
        mode: 'snapshot',
        page: partialPage(token(99)),
      });
    }
    return response({
      ...list([]),
      store: { source: 'harness', state_id: 'store-A' },
      mode: metadataUrl(path).searchParams.get('mode') ?? 'snapshot',
      page: { outcome: 'unavailable', revision: 0, scanned: 0, checkpoint: 0, next_cursor: null },
    });
  });
  expect(await store.readView()).toBe('applied');
  expect(store.getSnapshot().streams.find(s => s.stream.status === 'running')).toMatchObject({
    state: 'partial',
    traversal: { cursor },
  });

  request.mockClear();
  expect(await store.advance(false, { liveOnly: true })).toBe('applied');
  const continued = request.mock.calls
    .map(([path]) => metadataUrl(path))
    .find(url => url.pathname === '/api/jobs/metadata' && url.searchParams.get('status') === 'running');
  expect(continued).toBeTruthy();
  expect(continued?.searchParams.get('cursor')).toBe(cursor);
});

it('changed metadata view_generation after view_changed rebuilds traversal from page 1', async () => {
  await open();
  const cursor = token(14);
  request.mockResolvedValue(response({ ...list([]), page: partialPage(cursor) }));
  await store.advance();
  expect(store.getSnapshot().streams[0]).toMatchObject({ state: 'partial', traversal: { cursor } });

  request.mockResolvedValue(response({ code: 'view_changed' }, 409));
  expect(await store.advance()).toBe('failed');
  expect(store.getSnapshot().view).toMatchObject({ kind: 'target', reason: 'view_changed' });

  request.mockResolvedValue(response(view('generation-2')));
  expect(await store.readView()).toBe('applied');
  expect(store.getSnapshot().streams[0]).toMatchObject({
    state: 'ready',
    traversal: { mode: 'snapshot', after_revision: 0, cursor: null },
  });
});

it('hydrateDetail keeps the last hydrated observation visibly stale across a transient unavailable read', async () => {
  await open();
  const good = detail();
  request.mockImplementation(async (path: string) => path.endsWith('/view') ? response(view()) : path.includes('/detail') ? response(good) : response(list()));
  expect(await store.hydrateDetail(selection())).toBe('applied');
  const key = metadataSelectionKey(selection());
  expect(store.getSnapshot().detailCache[key]).toMatchObject({ freshness: 'observed', error: null });

  const locked = { ...good, lifecycle: null,
    tasks: { page: { outcome: 'unavailable', revision: 0, scanned: 0, checkpoint: 0, next_cursor: null }, rows: [] },
    artifacts: { page: { outcome: 'unavailable', revision: 0, scanned: 0, checkpoint: 0, next_cursor: null }, rows: [] },
    display: { kind: 'unavailable', reason: 'read_snapshot_unavailable' }, task_count: null, artifact_count: null,
    history: { kind: 'unavailable', reason: 'read_snapshot_unavailable' }, cost: { kind: 'unavailable', reason: 'read_snapshot_unavailable' },
    missing: ['history', 'cost', 'read_snapshot_unavailable'] };
  request.mockImplementation(async (path: string) => path.endsWith('/view') ? response(view()) : path.includes('/detail') ? response(locked) : response(list()));
  expect(await store.hydrateDetail(selection())).toBe('applied');
  const entry = store.getSnapshot().detailCache[key];
  expect(entry).toMatchObject({ freshness: 'stale', error: null });
  expect(entry.observation?.tasks.rows).toHaveLength(1);
  expect(entry.observation?.lifecycle).toBe('running');
});
