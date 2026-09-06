import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import TerminalPane from '../components/TerminalPane';

const harness = vi.hoisted(() => ({
  streams: [] as Array<{ data: (raw: unknown) => void; done: () => void; error: () => void }>,
  nextId: 0,
  paths: [] as string[],
  output: vi.fn(),
  write: vi.fn(),
}));
vi.mock('../lib/transport', () => ({
  postJSON: (path: string, body: unknown) => path.endsWith('/create')
    ? Promise.resolve({ id: `pty${++harness.nextId}` })
    : path.endsWith('/write') ? harness.write(body) : Promise.resolve({ok:true}),
  stream: (_path: string, data: (raw: unknown) => void, done: () => void, error: () => void) => {
    harness.paths.push(_path);
    harness.streams.push({data, done, error});
    return () => {};
  },
}));
vi.mock('@xterm/xterm', () => ({ Terminal: class {
  cols = 80; rows = 24;
  loadAddon() {} open() {} write(data: unknown) { harness.output(data); } writeln() {} dispose() {}
  registerLinkProvider() { return {dispose() {}}; }
  onSelectionChange() { return {dispose() {}}; }
  onData() {} onResize() {}
} }));
vi.mock('@xterm/addon-fit', () => ({FitAddon: class { fit() {} }}));
vi.mock('@xterm/addon-web-links', () => ({WebLinksAddon: class {}}));
vi.mock('../components/terminalDims', () => ({hostHasLayout: () => true, safePtyDims: () => ({cols:80, rows:24})}));

beforeEach(() => {
  vi.useFakeTimers();
  harness.streams.length = 0;
  harness.nextId = 0;
  harness.paths.length = 0;
  harness.output.mockClear();
  harness.write.mockReset();
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('ignores late exit and error callbacks after replacement', async () => {
  await act(async () => { render(<TerminalPane />); });
  const old = harness.streams[0];
  await act(async () => { fireEvent.click(screen.getByTitle(/Restart terminal/)); });
  act(() => {
    old.data({kind:'exit', reason:'process_exit', id:'pty1'});
    old.error();
    old.done();
    harness.streams[1].data({kind:'data', id:'pty2', b64:'aGk=', offset:2});
  });
  expect(screen.getByText(/Terminal -- active output/)).toBeInTheDocument();
});

it('reports missing acknowledgements and rejected input without claiming execution', async () => {
  await act(async () => { render(<TerminalPane />); });
  harness.write.mockImplementation(() => new Promise(() => {}));
  act(() => { window.dispatchEvent(new CustomEvent('harness-run-command', {detail:{command:'echo test'}})); });
  expect(screen.getByText(/input pending/)).toBeInTheDocument();
  act(() => { vi.advanceTimersByTime(5000); });
  expect(screen.getByText(/input unconfirmed/)).toBeInTheDocument();
  harness.write.mockRejectedValue(new Error('rejected'));
  await act(async () => { window.dispatchEvent(new CustomEvent('harness-run-command', {detail:{command:'echo test'}})); });
  expect(screen.getByText(/input failed or unconfirmed/)).toBeInTheDocument();
});

it('reattaches the same quiet PTY and rejects callbacks from the old attachment', async () => {
  await act(async () => { render(<TerminalPane />); });
  const old = harness.streams[0];
  act(() => { old.done(); vi.advanceTimersByTime(1000); });
  expect(harness.nextId).toBe(1);
  expect(harness.streams).toHaveLength(2);
  act(() => {
    harness.streams[1].data({kind:'observation', id:'pty1', state:'unknown'});
    old.data({kind:'exit', id:'pty1', reason:'process_exit'});
    old.error();
  });
  expect(screen.getByText(/Terminal -- unknown/)).toBeInTheDocument();
  act(() => { vi.advanceTimersByTime(5500); });
  expect(screen.getByText(/observation stale/)).toBeInTheDocument();
});

it('shows concise acceptance with an accessible explanation and exact input identity', async () => {
  await act(async () => { render(<TerminalPane />); });
  harness.write.mockImplementation((body) => Promise.resolve({ ...body, ok: true, accepted_bytes: new TextEncoder().encode(body.data).length }));
  await act(async () => { window.dispatchEvent(new CustomEvent('harness-run-command', {detail:{command:'echo €'}})); });
  expect(screen.getByText(/Input accepted/)).toHaveAccessibleName(/only bytes accepted by the PTY, not command execution or completion/);
  expect(screen.queryByText(/execution unknown/)).not.toBeInTheDocument();
  harness.write.mockImplementation((body) => Promise.resolve({ ...body, submission_id: 'wrong', ok: true, accepted_bytes: new TextEncoder().encode(body.data).length }));
  await act(async () => { window.dispatchEvent(new CustomEvent('harness-run-command', {detail:{command:'echo €'}})); });
  expect(screen.getByText(/input not confirmed/)).toBeInTheDocument();
});

it('accepts explicit cursor resets and reconnects without replaying already delivered bytes', async () => {
  await act(async () => { render(<TerminalPane />); });
  act(() => {
    harness.streams[0].data({kind:'data', id:'pty1', b64:'eA==', offset:900000});
    harness.streams[0].data({kind:'gap', id:'pty1', offset:600000, reason:'cursor_ahead'});
    harness.streams[0].data({kind:'data', id:'pty1', b64:'4oKs', offset:600003});
    harness.streams[0].done();
    vi.advanceTimersByTime(1000);
  });
  expect(harness.paths[1]).toContain('offset=600003');
  expect(harness.output).toHaveBeenCalledWith(new Uint8Array([226,130,172]));
  expect(harness.output).toHaveBeenCalledWith(expect.stringContaining('cursor reset'));
});

it('uses observation deadlines without a polling interval and pauses them for agent mirrors', async () => {
  const interval = vi.spyOn(window, 'setInterval');
  await act(async () => { render(<TerminalPane />); });
  act(() => { harness.streams[0].data({kind:'data', id:'pty1', b64:'eA==', offset:1}); });
  expect(screen.getByText(/active output/)).toBeInTheDocument();
  act(() => { vi.advanceTimersByTime(1000); });
  expect(screen.getByText(/Terminal -- unknown/)).toBeInTheDocument();
  act(() => { window.dispatchEvent(new CustomEvent('harness-open-agent-terminal', {detail:{id:'agent1', command:'echo test'}})); });
  const timers = vi.getTimerCount();
  act(() => { vi.advanceTimersByTime(10000); });
  expect(vi.getTimerCount()).toBe(timers);
  expect(interval).not.toHaveBeenCalled();
  interval.mockRestore();
});

it('pauses observation deadlines when the document is hidden and refreshes on return', async () => {
  await act(async () => { render(<TerminalPane />); });
  act(() => { harness.streams[0].data({kind:'data', id:'pty1', b64:'eA==', offset:1}); });
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  act(() => { document.dispatchEvent(new Event('visibilitychange')); });
  expect(vi.getTimerCount()).toBe(0);
  act(() => { vi.advanceTimersByTime(10000); });
  hidden.mockReturnValue(false);
  act(() => { document.dispatchEvent(new Event('visibilitychange')); });
  expect(screen.getByText(/observation stale/)).toBeInTheDocument();
  hidden.mockRestore();
});
