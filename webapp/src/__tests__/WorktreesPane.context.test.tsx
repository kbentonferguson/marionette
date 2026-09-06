import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import WorktreesPane from '../components/WorktreesPane';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: {
  getWorktrees: vi.fn(), addWorktree: vi.fn(), removeWorktree: vi.fn(),
  pruneWorktrees: vi.fn(), setWorktreeMax: vi.fn(),
}}));
vi.mock('../lib/useOperationalDiagnostic', () => ({ usePanelNotice: (text: string) => text }));
const listing = (repo: string) => ({ repo, max: 25, worktrees: [{ path: repo, branch: repo, head: '', is_main: true, locked: false }] });
beforeEach(() => { vi.resetAllMocks(); });
afterEach(cleanup);
it('ignores a late old list after a project switch', async () => {
  let old: (value: ReturnType<typeof listing>) => void = () => {};
  vi.mocked(api.getWorktrees).mockImplementationOnce(() => new Promise(resolve => { old = resolve; })).mockResolvedValue(listing('/b'));
  render(<WorktreesPane />);
  await act(async () => { window.dispatchEvent(new CustomEvent('harness-project-selected', { detail: '/b' })); });
  expect(screen.getByText('/b', { selector: 'span.truncate' })).toBeInTheDocument();
  await act(async () => { old(listing('/a')); });
  expect(screen.queryByText('/a', { selector: 'span.truncate' })).toBeNull();
});
it('rolls back max and reports errors, preventing duplicate actions', async () => {
  vi.mocked(api.getWorktrees).mockResolvedValue(listing('/a'));
  let reject: (reason: Error) => void = () => {};
  vi.mocked(api.setWorktreeMax).mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
  render(<WorktreesPane />);
  await act(async () => {});
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '2' } });
  expect(screen.getByRole('spinbutton')).toBeDisabled();
  await act(async () => { reject(new Error('save failed')); });
  expect(screen.getByRole('spinbutton')).toHaveValue(25);
  expect(screen.getByText('save failed')).toBeInTheDocument();
});
it('discards an old mutation completion after a session change', async () => {
  vi.mocked(api.getWorktrees).mockResolvedValueOnce(listing('/a')).mockResolvedValue(listing('/b'));
  let done: (value: { ok: boolean }) => void = () => {};
  vi.mocked(api.pruneWorktrees).mockImplementation(() => new Promise(resolve => { done = resolve; }));
  render(<WorktreesPane />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Prune Worktrees' }));
  await act(async () => { window.dispatchEvent(new CustomEvent('harness-session-changed')); });
  await act(async () => { done({ ok: true }); });
  expect(screen.queryByText('Worktrees pruned successfully')).toBeNull();
  expect(api.pruneWorktrees).toHaveBeenCalledWith('/a');
});
it('does not show a late old load error in the new workspace', async () => {
  let fail: (error: Error) => void = () => {};
  vi.mocked(api.getWorktrees).mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; })).mockResolvedValue(listing('/b'));
  render(<WorktreesPane />);
  await act(async () => { window.dispatchEvent(new CustomEvent('harness-project-selected', { detail: '/b' })); });
  await act(async () => { fail(new Error('obsolete load error')); });
  expect(screen.queryByText('obsolete load error')).toBeNull();
  expect(api.getWorktrees).toHaveBeenCalledWith('/b');
});
it('sends one add with the loaded identity and refreshes after success', async () => {
  vi.mocked(api.getWorktrees).mockResolvedValue(listing('/a'));
  let finish: (value: Awaited<ReturnType<typeof api.addWorktree>>) => void = () => {};
  vi.mocked(api.addWorktree).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  render(<WorktreesPane />);
  await act(async () => {});
  fireEvent.change(screen.getByRole('textbox', { name: 'Branch name' }), { target: { value: 'feature' } });
  expect(screen.getByRole('textbox', { name: 'Base commit-ish' })).toHaveValue('HEAD');
  const add = screen.getByRole('button', { name: 'Add Worktree' });
  fireEvent.click(add);
  fireEvent.click(add);
  expect(api.addWorktree).toHaveBeenCalledTimes(1);
  expect(api.addWorktree).toHaveBeenCalledWith('feature', 'HEAD', '/a');
  await act(async () => { finish({ path: '/a/feature', branch: 'feature', head: '', locked: false, is_main: false }); });
  expect(screen.getByText('Worktree added successfully')).toBeInTheDocument();
  expect(api.getWorktrees).toHaveBeenLastCalledWith('/a');
});
it('offers retry after a load failure without claiming an empty repository', async () => {
  vi.mocked(api.getWorktrees).mockRejectedValueOnce(new Error('load failed')).mockResolvedValue(listing('/a'));
  render(<WorktreesPane />);
  await act(async () => {});
  expect(screen.queryByText('No active worktrees found.')).toBeNull();
  expect(screen.getByRole('button', { name: 'Add Worktree' })).toBeDisabled();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retry' })); });
  expect(screen.getByRole('button', { name: 'Add Worktree' })).not.toBeDisabled();
});

it('explains the soft limit and reports protected cleanup targets', async () => {
  vi.mocked(api.getWorktrees).mockResolvedValue(listing('/a'));
  vi.mocked(api.setWorktreeMax).mockResolvedValue({ ok: true, cleanup: {
    removed: ['/a/clean'], count: 1, remaining: 2,
    skipped: [{ path: '/a/dirty', reason: 'Tracked, untracked, or ignored changes' }],
  } });
  render(<WorktreesPane />);
  await act(async () => {});
  expect(screen.getByText(/count may exceed the limit/)).toBeInTheDocument();
  await act(async () => { fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '1' } }); });
  expect(screen.getByRole('status')).toHaveTextContent('removed 1 clean worktree(s)');
  expect(screen.getByRole('status')).toHaveTextContent('/a/dirty (Tracked, untracked, or ignored changes)');
});
