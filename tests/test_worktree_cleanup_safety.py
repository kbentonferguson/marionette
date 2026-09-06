from pathlib import Path
import subprocess

import pytest
from harness import worktrees


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-qb', 'main')
    git(root, 'config', 'user.name', 'Test')
    git(root, 'config', 'user.email', 'test@example.invalid')
    (root / 'tracked').write_text('original')
    (root / '.gitignore').write_text('ignored\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'initial')
    return str(root)


def run_cleanup(repo, mode):
    if mode == 'limit':
        return worktrees.cleanup_old_worktrees(repo, 0)
    if mode == 'boot':
        return worktrees.reap_stale_managed_worktrees(repo)
    return worktrees.prune_orphan_edit_branches(repo)


@pytest.mark.parametrize('mode', ['limit', 'boot', 'branches'])
@pytest.mark.parametrize('protected', ['tracked', 'untracked', 'ignored', 'locked'])
def test_automatic_cleanup_preserves_protected_trees(repo, mode, protected):
    branch = 'release/v0.9.123' if mode == 'branches' else 'pmedit-protected'
    tree = Path(worktrees.add_worktree(repo, branch)['path'])
    if protected == 'locked':
        git(repo, 'worktree', 'lock', str(tree))
    else:
        (tree / protected).write_text('keep me')
    result = run_cleanup(repo, mode)
    assert tree.is_dir()
    if protected != 'locked':
        assert (tree / protected).read_text() == 'keep me'
    assert branch in git(repo, 'branch', '--format=%(refname:short)').splitlines()
    assert result['count'] == 0
    assert any(Path(item['path']) == tree and item['reason'] for item in result['skipped'])
    assert Path(repo, 'tracked').read_text() == 'original'


@pytest.mark.parametrize('mode', ['limit', 'boot', 'branches'])
def test_automatic_cleanup_still_removes_clean_trees(repo, mode):
    branch = 'release/v0.9.124' if mode == 'branches' else 'pmedit-clean'
    tree = Path(worktrees.add_worktree(repo, branch)['path'])
    result = run_cleanup(repo, mode)
    assert not tree.exists()
    assert result['count'] == 1
    assert Path(repo, 'tracked').exists()


def test_branch_prune_cannot_bypass_managed_directory(repo, tmp_path):
    tree = tmp_path / 'outside'
    git(repo, 'worktree', 'add', '-b', 'release/v0.9.125', str(tree))
    result = worktrees.prune_orphan_edit_branches(repo)
    assert tree.is_dir()
    assert result['count'] == 0
    assert result['skipped']


def test_limit_continues_past_dirty_oldest_and_keeps_registered_worker(repo):
    dirty = Path(worktrees.add_worktree(repo, 'pmedit-dirty')['path'])
    (dirty / 'untracked').write_text('keep')
    live = Path(worktrees.add_worktree(repo, 'pmedit-live')['path'])
    clean = Path(worktrees.add_worktree(repo, 'pmedit-clean')['path'])
    worktrees.register_worktree_process(str(live), 424242, kind='worker')
    try:
        result = worktrees.cleanup_old_worktrees(repo, 1)
        assert dirty.exists() and live.exists() and not clean.exists()
        assert result['count'] == 1
        assert result['remaining'] == 2
        assert len(result['skipped']) == 2
    finally:
        worktrees.clear_managed_process_registry_for_tests()


def test_explicit_force_removal_remains_available(repo):
    tree = Path(worktrees.add_worktree(repo, 'explicit')['path'])
    (tree / 'tracked').write_text('discard explicitly')
    with pytest.raises(RuntimeError):
        worktrees.remove_worktree(repo, str(tree))
    worktrees.remove_worktree(repo, str(tree), force=True)
    assert not tree.exists()


@pytest.mark.parametrize('changed', ['tracked', 'untracked', 'ignored', 'locked'])
def test_nonforce_removal_rechecks_changes_after_candidate_selection(repo, monkeypatch, changed):
    tree = Path(worktrees.add_worktree(repo, 'pmedit-raced')['path'])
    remove = worktrees.remove_worktree
    def race(repo, path, force=False):
        assert force is False
        if changed == 'locked':
            git(repo, 'worktree', 'lock', path)
        else:
            (Path(path) / changed).write_text('arrived late')
        return remove(repo, path, force=force)
    monkeypatch.setattr(worktrees, 'remove_worktree', race)
    result = worktrees.cleanup_old_worktrees(repo, 0)
    assert tree.exists()
    assert result['count'] == 0
    assert result['skipped']


def test_git_nonforce_rejects_main_worktree(repo):
    result = subprocess.run(['git', '-C', repo, 'worktree', 'remove', repo], capture_output=True)
    assert result.returncode != 0
    assert Path(repo, 'tracked').exists()


@pytest.mark.parametrize('protected', ['tracked', 'untracked', 'locked'])
def test_raw_git_nonforce_refuses_protected_linked_tree(repo, protected):
    tree = Path(worktrees.add_worktree(repo, 'raw-git')['path'])
    if protected == 'locked':
        git(repo, 'worktree', 'lock', str(tree))
    else:
        (tree / protected).write_text('keep')
    result = subprocess.run(['git', '-C', repo, 'worktree', 'remove', str(tree)], capture_output=True)
    assert result.returncode != 0
    assert tree.exists()


def unique_commit(repo, branch):
    git(repo, 'checkout', '-qb', branch)
    Path(repo, 'tracked').write_text(branch)
    git(repo, 'commit', '-qam', 'unique work')
    tip = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', 'main')
    return tip


@pytest.mark.parametrize('branch', ['pmedit-unique', 'pmworker-unique',
                                    'feature-gone', 'release/v0.9.999',
                                    'dest', 'absorb/unique'])
def test_branch_prune_preserves_unmerged_commits(repo, branch):
    tip = unique_commit(repo, branch)
    if branch == 'feature-gone':
        git(repo, 'config', 'branch.feature-gone.remote', '.')
        git(repo, 'config', 'branch.feature-gone.merge', 'refs/heads/missing')
    result = worktrees.prune_orphan_edit_branches(repo)
    assert git(repo, 'rev-parse', 'refs/heads/' + branch) == tip
    assert result['count'] == 0
    assert any(item['branch'] == branch and 'retained' in item['reason']
               for item in result['skipped'])


def test_branch_prune_preserves_two_orphans_with_same_unique_commit(repo):
    tip = unique_commit(repo, 'pmedit-one')
    git(repo, 'branch', 'pmworker-two', tip)
    result = worktrees.prune_orphan_edit_branches(repo)
    assert result['count'] == 0
    for branch in ['pmedit-one', 'pmworker-two']:
        assert git(repo, 'rev-parse', branch) == tip
    assert len(result['skipped']) == 2


def test_branch_prune_preserves_unmerged_release_tree_before_removal(repo):
    branch = 'release/v0.9.998'
    tip = unique_commit(repo, branch)
    tree = Path(worktrees.add_worktree(repo, branch)['path'])
    result = worktrees.prune_orphan_edit_branches(repo)
    assert tree.is_dir()
    assert git(repo, 'rev-parse', branch) == tip
    assert result['count'] == 0
    assert result['skipped'][0]['path'] == str(tree)


@pytest.mark.parametrize('anchor', ['main', 'feature-durable'])
def test_branch_prune_removes_commits_retained_by_durable_branch(repo, anchor):
    tip = unique_commit(repo, 'pmedit-merged')
    if anchor == 'main':
        git(repo, 'merge', '--ff-only', 'pmedit-merged')
    else:
        git(repo, 'branch', anchor, tip)
    result = worktrees.prune_orphan_edit_branches(repo)
    assert result['deleted'] == ['pmedit-merged']
    assert git(repo, 'rev-parse', anchor) == tip


def test_explicit_branch_discard_still_deletes_unmerged_branch(repo):
    unique_commit(repo, 'pmedit-discard')
    worktrees.delete_branch(repo, 'pmedit-discard', raise_on_error=True)
    assert 'pmedit-discard' not in git(repo, 'branch', '--format=%(refname:short)').splitlines()


def test_branch_prune_rechecks_commits_before_deletion(repo, monkeypatch):
    branch = 'pmedit-raced-tip'
    git(repo, 'branch', branch)
    original_git = worktrees._git

    def advance_before_delete(root, *args, **kwargs):
        if 'branch' in args and '-d' in args:
            git(repo, 'checkout', '-q', branch)
            Path(repo, 'tracked').write_text('arrived after ancestry check')
            git(repo, 'commit', '-qam', 'late commit')
            git(repo, 'checkout', '-q', 'main')
        return original_git(root, *args, **kwargs)

    monkeypatch.setattr(worktrees, '_git', advance_before_delete)
    result = worktrees.prune_orphan_edit_branches(repo)
    assert result['count'] == 0
    assert branch in git(repo, 'branch', '--format=%(refname:short)').splitlines()
    assert result['skipped']


def test_current_prunable_branch_is_not_durable_retention(repo):
    tip = unique_commit(repo, 'pmedit-orphan')
    git(repo, 'checkout', '-qb', 'pmworker-current', tip)
    result = worktrees.prune_orphan_edit_branches(repo)
    assert result['count'] == 0
    assert git(repo, 'rev-parse', 'pmedit-orphan') == tip
