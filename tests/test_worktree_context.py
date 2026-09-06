from types import SimpleNamespace
import subprocess
import json

import pytest
from harness.api.worktrees import WorktreeServices
from harness import http_routes, worktrees


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def context(tmp_path, monkeypatch):
    repos = []
    for name in ('a', 'b'):
        repo = tmp_path / name
        repo.mkdir()
        git(repo, 'init', '-q')
        git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'initial')
        repos.append(str(repo))
    monkeypatch.setattr(worktrees, '_WORKTREES_JSON', str(tmp_path / 'settings.json'))
    cfg = SimpleNamespace(repo=repos[0])
    svc = WorktreeServices(cfg, bool)
    class Services(SimpleNamespace):
        def __getattr__(self, name):
            return lambda *a, **k: None
    services = Services(worktree_services=lambda: svc)
    handler = SimpleNamespace(_send=lambda code, payload: (code, json.loads(payload)))
    gets = {path: (lambda qs, fn=fn: fn(handler, None, qs))
            for path, fn in http_routes.build_get_routes(services).items()}
    posts = {path: (lambda body, fn=fn: fn(handler, body))
             for path, fn in http_routes.build_post_json_routes(services).items()}
    return repos, cfg, gets, posts


def test_two_repo_stale_add_is_rejected(context):
    (a, b), cfg, gets, posts = context
    code, listing = gets['/api/worktrees']({})
    assert code == 200
    cfg.repo = b
    code, result = posts['/api/worktrees/add']({'repo': a, 'branch': 'stale'})
    assert code == 409
    assert 'stale' not in git(b, 'branch', '--list')
    assert listing['repo'] == a


@pytest.mark.parametrize('route,body', [
    ('add', {'branch': 'missing'}), ('remove', {'path': '/not-owned'}),
    ('prune', {}), ('prune-edit-branches', {}), ('max', {'max': 2}),
])
def test_mutations_require_current_context(context, route, body):
    (a, b), cfg, gets, posts = context
    handler = posts['/api/worktrees/' + route]
    assert handler(body)[0] == 409
    assert handler(dict(body, repo=b))[0] == 409


def test_max_and_add_preserve_dirty_work(context):
    (a, b), cfg, gets, posts = context
    dirty = worktrees.add_worktree(a, 'dirty')
    from pathlib import Path
    sentinel = Path(dirty['path']) / 'uncommitted.txt'
    sentinel.write_text('keep me')
    assert posts['/api/worktrees/max']({'repo': a, 'max': 1})[0] == 200
    assert posts['/api/worktrees/add']({'repo': a, 'branch': 'new'})[0] == 200
    assert sentinel.read_text() == 'keep me'


def test_requested_list_rejects_other_repo(context):
    (a, b), cfg, gets, posts = context
    assert gets['/api/worktrees']({'repo': [b]})[0] == 409
    assert gets['/api/worktrees']({'repo': [a]})[1]['repo'] == a


def test_accepted_add_keeps_captured_repo(context, monkeypatch):
    (a, b), cfg, gets, posts = context
    original = worktrees.add_worktree
    def switch_then_add(repo, branch, base):
        cfg.repo = b
        return original(repo, branch, base)
    monkeypatch.setattr(worktrees, 'add_worktree', switch_then_add)
    assert posts['/api/worktrees/add']({'repo': a, 'branch': 'captured'})[0] == 200
    assert 'captured' in git(a, 'branch', '--list')
    assert 'captured' not in git(b, 'branch', '--list')


@pytest.mark.parametrize('value', [0, -1, 101, True, 2.5, None, 'invalid'])
def test_invalid_max_does_not_persist(context, value):
    (a, b), cfg, gets, posts = context
    assert posts['/api/worktrees/max']({'repo': a, 'max': value})[0] == 400
    assert worktrees.get_max_worktrees() == 25


def test_max_persistence_failure_is_reported(context, monkeypatch):
    (a, b), cfg, gets, posts = context
    monkeypatch.setattr(worktrees, 'set_max_worktrees', lambda value: None)
    assert posts['/api/worktrees/max']({'repo': a, 'max': 2})[0] == 500


def test_current_remove_and_prune(context):
    (a, b), cfg, gets, posts = context
    code, tree = posts['/api/worktrees/add']({'repo': a, 'branch': 'removable'})
    assert code == 200
    assert posts['/api/worktrees/remove']({'repo': a, 'path': tree['path']})[0] == 200
    assert posts['/api/worktrees/prune']({'repo': a})[0] == 200


def test_admin_limit_cleans_eligible_trees_and_reports_skips(context):
    from pathlib import Path
    (a, b), cfg, gets, posts = context
    dirty = Path(worktrees.add_worktree(a, 'dirty-limit')['path'])
    (dirty / 'untracked').write_text('keep')
    clean = Path(worktrees.add_worktree(a, 'clean-limit')['path'])
    code, result = posts['/api/worktrees/max']({'repo': a, 'max': 1})
    assert code == 200
    assert dirty.is_dir() and not clean.exists()
    assert result['cleanup']['count'] == 1
    code, new = posts['/api/worktrees/add']({'repo': a, 'branch': 'new-limit'})
    assert code == 200
    assert Path(new['path']).is_dir()
    assert dirty.is_dir()
    assert new['cleanup']['remaining'] == 2
    assert new['cleanup']['skipped']
