"""Worktree admin HTTP route bodies (peeled from ``harness.server``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class WorktreeServices:
    """Explicit deps for worktree HTTP handlers."""

    cfg: Any
    parse_bool: Callable[[Any], bool]


def _repo(body: dict, svc: WorktreeServices) -> str:
    from ..paths import same_workspace_path
    repo = svc.cfg.repo
    requested = body.get("repo")
    if not repo or not isinstance(requested, str) or not requested or not same_workspace_path(requested, repo):
        raise ValueError("Workspace changed or context missing; refresh worktrees before retrying")
    return repo


def get_worktrees(svc: WorktreeServices, requested_repo: str = "") -> tuple[int, dict]:
    """GET /api/worktrees."""
    from .. import worktrees as _wt
    repo = svc.cfg.repo
    if requested_repo:
        try:
            repo = _repo({"repo": requested_repo}, svc)
        except ValueError as e:
            return 409, {"error": str(e)}
    return 200, {
        "repo": repo,
        "worktrees": _wt.list_worktrees(repo),
        "max": _wt.get_max_worktrees(),
    }


def post_worktrees_add(body: dict, svc: WorktreeServices) -> tuple[int, dict]:
    """POST /api/worktrees/add."""
    from .. import worktrees as _wt
    try:
        repo = _repo(body, svc)
    except ValueError as e:
        return 409, {"error": str(e)}
    branch = body.get("branch", "").strip()
    base = body.get("base") or "HEAD"
    if not branch or branch.startswith("-") or (base and base.startswith("-")):
        return 400, {"error": "invalid branch or base name"}
    try:
        new_wt = _wt.add_worktree(repo, branch, base)
        cleanup = _wt.cleanup_old_worktrees(repo, _wt.get_max_worktrees(), keep_paths=[new_wt["path"]])
        return 200, {**new_wt, "cleanup": cleanup}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        return 400, {"error": f"Failed to add worktree: {str(e)}"}


def post_worktrees_remove(body: dict, svc: WorktreeServices) -> tuple[int, dict]:
    """POST /api/worktrees/remove."""
    from .. import worktrees as _wt
    try:
        repo = _repo(body, svc)
    except ValueError as e:
        return 409, {"error": str(e)}
    wt_path = body.get("path", "").strip()
    force = svc.parse_bool(body.get("force"))
    if not wt_path:
        return 400, {"error": "missing path"}
    try:
        _wt.remove_worktree(repo, wt_path, force=force)
        return 200, {"ok": True}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        return 400, {"error": f"Failed to remove worktree: {str(e)}"}


def post_worktrees_prune(body: dict, svc: WorktreeServices) -> tuple[int, dict]:
    """POST /api/worktrees/prune."""
    from .. import worktrees as _wt
    try:
        repo = _repo(body, svc)
    except ValueError as e:
        return 409, {"error": str(e)}
    try:
        _wt.prune_worktrees(repo)
        return 200, {"ok": True}
    except Exception as e:
        return 400, {"error": f"Failed to prune worktrees: {str(e)}"}


def post_worktrees_prune_edit_branches(body: dict, svc: WorktreeServices) -> tuple[int, dict]:
    """POST /api/worktrees/prune-edit-branches."""
    from .. import worktrees as _wt
    try:
        repo = _repo(body, svc)
    except ValueError as e:
        return 409, {"error": str(e)}
    try:
        result = _wt.prune_orphan_edit_branches(repo)
        return 200, {
            "ok": True,
            "deleted": result.get("deleted", []),
            "skipped": result.get("skipped", []),
            "count": int(result.get("count", 0) or 0),
        }
    except Exception as e:
        return 400, {"error": f"Failed to prune edit branches: {str(e)}"}


def post_worktrees_max(body: dict, svc: WorktreeServices) -> tuple[int, dict]:
    """POST /api/worktrees/max."""
    from .. import worktrees as _wt
    try:
        repo = _repo(body, svc)
    except ValueError as e:
        return 409, {"error": str(e)}
    try:
        raw = body.get("max", body.get("max_worktrees", 25))
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise ValueError("Invalid max value")
        max_val = int(raw)
        if not 1 <= max_val <= 100:
            raise ValueError("Invalid max value")
        _wt.set_max_worktrees(max_val)
        if _wt.get_max_worktrees() != max_val:
            return 500, {"error": "Failed to save max worktrees"}
        cleanup = _wt.cleanup_old_worktrees(repo, max_val)
        return 200, {"ok": True, "cleanup": cleanup}
    except (ValueError, TypeError):
        return 400, {"error": "Invalid max value"}
    except Exception as e:
        return 500, {"error": f"Failed to save max worktrees: {e}"}
