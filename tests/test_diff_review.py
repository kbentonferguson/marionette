import pytest
import tempfile
import shutil
import os
import subprocess
import json
import urllib.request
import urllib.error
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch, MagicMock

from harness.config import HarnessConfig
from harness.conversation import ConversationalSession
from harness.diffreview import parse_unified_diff, reconstruct_diff


@pytest.fixture
def temp_git_repo():
    dirpath = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init"], cwd=dirpath, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=dirpath, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=dirpath, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Write base files
        file1 = os.path.join(dirpath, "file1.txt")
        with open(file1, "w") as f:
            f.write("Line A\nLine B\nLine C\n")
            
        file2 = os.path.join(dirpath, "file2.txt")
        with open(file2, "w") as f:
            f.write("Alpha\nBeta\nGamma\n")
            
        subprocess.run(["git", "add", "file1.txt", "file2.txt"], cwd=dirpath, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=dirpath, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        yield dirpath
    finally:
        shutil.rmtree(dirpath, ignore_errors=True)


def test_diff_parser_and_reconstruct():
    diff_text = (
        "diff --git a/file1.txt b/file1.txt\n"
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,4 @@\n"
        " Line A\n"
        "+Line A.5\n"
        " Line B\n"
        " Line C\n"
        "diff --git a/file2.txt b/file2.txt\n"
        "--- a/file2.txt\n"
        "+++ b/file2.txt\n"
        "@@ -1,3 +1,4 @@\n"
        " Alpha\n"
        "+Delta\n"
        " Beta\n"
        " Gamma\n"
    )
    
    parsed = parse_unified_diff(diff_text)
    assert len(parsed) == 2
    assert parsed[0]["path"] == "file1.txt"
    assert parsed[1]["path"] == "file2.txt"
    
    assert len(parsed[0]["hunks"]) == 1
    assert len(parsed[1]["hunks"]) == 1
    
    hunk1_id = parsed[0]["hunks"][0]["id"]
    hunk2_id = parsed[1]["hunks"][0]["id"]
    
    # Reconstruct with only the first hunk accepted
    decisions = {hunk1_id: "accept", hunk2_id: "reject"}
    new_diff = reconstruct_diff(parsed, decisions)
    
    assert "file1.txt" in new_diff
    assert "Line A.5" in new_diff
    assert "file2.txt" not in new_diff
    assert "Delta" not in new_diff


def test_reconstruct_diff_preserves_index_headers():
    """Partial-hunk accept must keep the `index <blob>..<blob>` ancestor SHAs
    (and the diff --git / --- / +++ headers). Those blob identities are exactly
    what lets `git apply --3way` reconstruct the ancestor and do a REAL 3-way
    merge onto a moved tree. If reconstruct_diff ever drops them, the apply
    silently degrades to context-only matching -- the corruption class we
    removed the lenient tier to prevent. This locks the invariant."""
    diff_text = (
        "diff --git a/file1.txt b/file1.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,4 @@\n"
        " Line A\n"
        "+Line A.5\n"
        " Line B\n"
        " Line C\n"
        "@@ -10,2 +11,3 @@\n"
        " Line J\n"
        "+Line J.5\n"
        " Line K\n"
    )

    parsed = parse_unified_diff(diff_text)
    assert len(parsed) == 1
    assert len(parsed[0]["hunks"]) == 2

    # Accept only the first hunk, reject the second.
    hunk_a = parsed[0]["hunks"][0]["id"]
    hunk_b = parsed[0]["hunks"][1]["id"]
    rebuilt = reconstruct_diff(parsed, {hunk_a: "accept", hunk_b: "reject"})

    # The ancestor-blob line and every file header must survive verbatim.
    assert "index 1111111..2222222 100644" in rebuilt
    assert "diff --git a/file1.txt b/file1.txt" in rebuilt
    assert "--- a/file1.txt" in rebuilt
    assert "+++ b/file1.txt" in rebuilt
    # Accepted hunk present, rejected hunk gone.
    assert "Line A.5" in rebuilt
    assert "Line J.5" not in rebuilt


def test_decision_id_assigned_and_stable_under_reorder():
    from harness.diffreview import (
        assign_decision_ids,
        decision_for_hunk,
        hunk_content_fingerprint,
        parse_unified_diff,
    )

    diff_text = (
        "diff --git a/a.txt b/a.txt\n"
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1 +1 @@\n"
        "+one\n"
        "@@ -2 +2 @@\n"
        "+two\n"
        "@@ -1 +1 @@\n"
        "+one\n"
    )
    parsed = parse_unified_diff(diff_text)
    hunks = parsed[0]["hunks"]
    assert all(h.get("decision_id") for h in hunks)
    # Exact duplicate content gets distinct decision ids.
    assert hunks[0]["decision_id"] != hunks[2]["decision_id"]
    assert hunks[0]["decision_id"].rsplit("#", 1)[0] == hunks[2]["decision_id"].rsplit("#", 1)[0]
    assert hunks[0]["decision_id"].endswith("#0")
    assert hunks[2]["decision_id"].endswith("#1")

    # Opposite decisions on duplicate-content hunks.
    decisions = {
        hunks[0]["decision_id"]: "accept",
        hunks[1]["decision_id"]: "reject",
        hunks[2]["decision_id"]: "reject",
    }
    assert decision_for_hunk(decisions, hunks[0], "a.txt") == "accept"
    assert decision_for_hunk(decisions, hunks[2], "a.txt") == "reject"

    # Reordering unrelated middle hunk must not change keys for A and the dup.
    reordered = [
        {
            "path": "a.txt",
            "headers": parsed[0]["headers"],
            "hunks": [dict(hunks[0]), dict(hunks[2]), dict(hunks[1])],
        }
    ]
    # Strip decision_ids to force reassignment from content.
    for h in reordered[0]["hunks"]:
        h.pop("decision_id", None)
    assign_decision_ids(reordered)
    ids = [h["decision_id"] for h in reordered[0]["hunks"]]
    # First duplicate-content occurrence stays #0; second stays #1 regardless of
    # where the unrelated hunk sits.
    assert ids[0] == hunks[0]["decision_id"]
    assert ids[1] == hunks[2]["decision_id"]
    assert ids[2] == hunks[1]["decision_id"]

    fp = hunk_content_fingerprint("a.txt", "@@ -1 +1 @@\n", ["+one\n"])
    assert hunks[0]["decision_id"].startswith(fp)


def test_legacy_plain_id_decisions_still_resolve():
    from harness.diffreview import decision_for_hunk

    hunk = {"id": "0:0", "header": "@@", "lines": ["+x"]}
    assert decision_for_hunk({"0:0": "accept"}, hunk, "f.py") == "accept"
    assert decision_for_hunk({}, hunk, "f.py") == "reject"


def test_apply_review(temp_git_repo, tmp_path):
    active_repo = tmp_path / "active"
    subprocess.run(["git", "init", str(active_repo)], check=True)
    cfg = HarnessConfig(driver="stub-oracle-v2", state_dir=tempfile.mkdtemp())
    cfg.repo = str(active_repo)
    session = ConversationalSession(cfg)
    session._review_edits_before_apply = True
    
    # Mocking some artifacts containing a patch
    artifacts = [
        {
            "type": "patch",
            "payload": {
                "files": ["file1.txt", "file2.txt"],
                "unified_diff": (
                    "diff --git a/file1.txt b/file1.txt\n"
                    "--- a/file1.txt\n"
                    "+++ b/file1.txt\n"
                    "@@ -1,3 +1,4 @@\n"
                    " Line A\n"
                    "+Line A.5\n"
                    " Line B\n"
                    " Line C\n"
                    "diff --git a/file2.txt b/file2.txt\n"
                    "--- a/file2.txt\n"
                    "+++ b/file2.txt\n"
                    "@@ -1,3 +1,4 @@\n"
                    " Alpha\n"
                    "+Delta\n"
                    " Beta\n"
                    " Gamma\n"
                )
            }
        }
    ]
    
    original_run = subprocess.run
    def mock_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            return original_run(cmd, *args, **kwargs)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "artifacts" in cmd_str:
            mock_p = MagicMock()
            mock_p.returncode = 0
            mock_p.stdout = json.dumps(artifacts)
            return mock_p
        mock_p = MagicMock()
        mock_p.returncode = 0
        mock_p.stdout = ""
        return mock_p

    with patch("subprocess.run", side_effect=mock_run):
        # Process job which triggers review hold since review_edits_before_apply is True
        res = session._await_and_apply_job(
            "job-123", state_dir=None, objective="Test edits",
            target_repo=temp_git_repo,
        )
        assert res["held_for_review"] is True
        assert res["applied"] is False
        
        pending = res["pending_review"]
        assert pending is not None
        review_id = pending["id"]
        
        # Verify the pending review exists in session storage
        assert review_id in session._pending_reviews
        review_item = session._pending_reviews[review_id]
        assert review_item["objective"] == "Test edits"
        
        # Now let's apply the review with decisions: accept first hunk, reject second
        hunk1_id = review_item["files"][0]["hunks"][0]["id"]
        hunk2_id = review_item["files"][1]["hunks"][0]["id"]
        
        decisions = {hunk1_id: "accept", hunk2_id: "reject"}
        apply_res = session.apply_review(review_id, decisions)
        
        assert apply_res["ok"] is True
        assert "file1.txt" in apply_res["applied_files"]
        assert hunk2_id in apply_res["rejected_hunks"]
        
        # Check that it took a checkpoint
        assert apply_res["checkpoint_id"] is not None
        
        # Confirm file1 was modified but file2 was not
        with open(os.path.join(temp_git_repo, "file1.txt")) as f:
            content1 = f.read()
        assert "Line A.5" in content1
        
        with open(os.path.join(temp_git_repo, "file2.txt")) as f:
            content2 = f.read()
        assert "Delta" not in content2
        assert not (active_repo / "file1.txt").exists()
        
        # Verify the pending review was cleared
        assert review_id not in session._pending_reviews


def test_apply_review_keeps_pending_on_failure(temp_git_repo):
    """Failed apply must leave the review queued so the user can retry/reject."""
    cfg = HarnessConfig(driver="stub-oracle-v2", state_dir=tempfile.mkdtemp())
    cfg.repo = temp_git_repo
    session = ConversationalSession(cfg)

    diff_text = (
        "diff --git a/file1.txt b/file1.txt\n"
        "--- a/file1.txt\n"
        "+++ b/file1.txt\n"
        "@@ -1,3 +1,4 @@\n"
        " Line A\n"
        "+Line A.5\n"
        " Line B\n"
        " Line C\n"
    )
    parsed = parse_unified_diff(diff_text)
    review_id = "rev-fail-keep"
    session._pending_reviews[review_id] = {
        "id": review_id,
        "job_id": "job-fail",
        "objective": "keep on fail",
        "files": parsed,
        "created_at": 0,
    }

    hunk_id = parsed[0]["hunks"][0]["id"]
    with patch.object(
        session,
        "_apply_worker_patch",
        return_value=(False, [], "patch did not apply cleanly"),
    ):
        res = session.apply_review(review_id, {hunk_id: "accept"})

    assert res["ok"] is False
    assert "Failed to apply" in res["message"]
    assert review_id in session._pending_reviews
    assert "Failed to apply" in session._pending_reviews[review_id].get("error", "")

    # A later successful apply still clears the review.
    with patch.object(
        session,
        "_apply_worker_patch",
        return_value=(True, ["file1.txt"], "ok"),
    ):
        session._last_checkpoint_id = "cp-retry"
        ok = session.apply_review(review_id, {hunk_id: "accept"})
    assert ok["ok"] is True
    assert review_id not in session._pending_reviews


def test_review_edits_before_apply_off_by_default(temp_git_repo):
    cfg = HarnessConfig(driver="stub-oracle-v2", state_dir=tempfile.mkdtemp())
    cfg.repo = temp_git_repo
    session = ConversationalSession(cfg)
    
    # Off by default
    assert session._review_edits_before_apply is False
    
    artifacts = [
        {
            "type": "patch",
            "payload": {
                "files": ["file1.txt"],
                "unified_diff": (
                    "diff --git a/file1.txt b/file1.txt\n"
                    "--- a/file1.txt\n"
                    "+++ b/file1.txt\n"
                    "@@ -1,3 +1,4 @@\n"
                    " Line A\n"
                    "+Line A.5\n"
                    " Line B\n"
                    " Line C\n"
                )
            }
        }
    ]
    
    original_run = subprocess.run
    def mock_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            return original_run(cmd, *args, **kwargs)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "artifacts" in cmd_str:
            mock_p = MagicMock()
            mock_p.returncode = 0
            mock_p.stdout = json.dumps(artifacts)
            return mock_p
        mock_p = MagicMock()
        mock_p.returncode = 0
        mock_p.stdout = ""
        return mock_p

    with patch("subprocess.run", side_effect=mock_run):
        # This should auto-apply
        res = session._await_and_apply_job("job-456", state_dir=None, objective="Test edits")
        assert res["applied"] is True
        assert res.get("held_for_review") is not True


def _server():
    import harness.server as srv
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, srv


def _get(port, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {}, method="GET")
    return urllib.request.urlopen(req, timeout=10)


def _post(port, path, body, headers):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=10)


def test_reviews_endpoints_403_without_token():
    httpd, port, srv = _server()
    try:
        # GET reviews without token -> 403
        try:
            _get(port, "/api/reviews")
            assert False, "GET should have returned 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403
            
        # POST apply without token -> 403
        try:
            _post(port, "/api/reviews/apply", {"id": "rev-123", "decisions": {}}, {})
            assert False, "POST apply should have returned 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # POST dismiss without token -> 403
        try:
            _post(port, "/api/reviews/dismiss", {"id": "rev-123"}, {})
            assert False, "POST dismiss should have returned 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_scoped_review_api_preserves_sibling_file(temp_git_repo, tmp_path, monkeypatch, decision):
    from pathlib import Path
    from harness.api.reviews import ReviewServices, post_reviews_apply, get_reviews

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    cfg = HarnessConfig(driver="stub-oracle-v2", state_dir=str(tmp_path / "state"))
    cfg.repo = temp_git_repo
    session = ConversationalSession(cfg)
    files = parse_unified_diff(
        "diff --git a/file1.txt b/file1.txt\n--- a/file1.txt\n+++ b/file1.txt\n"
        "@@ -1,3 +1,4 @@\n Line A\n+Added\n Line B\n Line C\n"
        "diff --git a/file2.txt b/file2.txt\n--- a/file2.txt\n+++ b/file2.txt\n"
        "@@ -1,3 +1,4 @@\n Alpha\n+Extra\n Beta\n Gamma\n"
    )
    session._pending_reviews["scoped"] = {
        "id": "scoped", "job_id": "", "target_repo": temp_git_repo,
        "objective": "two files", "created_at": 123, "files": files,
    }
    svc = ReviewServices(cfg, lambda: session, lambda *a: None, lambda s: s)
    a_id = files[0]["hunks"][0]["decision_id"]
    b_id = files[1]["hunks"][0]["decision_id"]
    code, result = post_reviews_apply({
        "id": "scoped", "scope": "selected", "decisions": {a_id: decision},
    }, svc)
    assert code == 200 and result["ok"], result
    assert (Path(temp_git_repo) / "file2.txt").read_text() == "Alpha\nBeta\nGamma\n"
    assert ("Added" in (Path(temp_git_repo) / "file1.txt").read_text()) == (decision == "accept")
    pending = get_reviews(svc)[1]
    assert len(pending) == 1, "selected action consumed untouched sibling file"
    assert pending[0]["id"] == "scoped"
    assert pending[0]["created_at"] == 123
    assert pending[0]["files"][0]["hunks"][0]["decision_id"] == b_id
    assert pending[0]["files"][0]["hunks"][0]["status"] == "pending"
    code, result = post_reviews_apply({"id": "scoped", "decisions": {b_id: "accept"}}, svc)
    assert result["ok"], result
    assert "Extra" in (Path(temp_git_repo) / "file2.txt").read_text()
    assert get_reviews(svc)[1] == []


@pytest.fixture
def scoped_review(temp_git_repo, tmp_path, monkeypatch):
    from pathlib import Path
    from harness.api.reviews import ReviewServices, post_reviews_apply

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    repo = Path(temp_git_repo)
    base = "".join(f"line {i}\n" for i in range(30))
    target = repo / "multi.txt"
    target.write_text(base)
    subprocess.run(["git", "add", "multi.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "multi"], cwd=repo, check=True, capture_output=True)
    target.write_text(base.replace("line 2\n", "line 2\ninserted\n").replace("line 25\n", "changed\n"))
    diff = subprocess.run(["git", "diff"], cwd=repo, check=True, capture_output=True, text=True).stdout
    target.write_text(base)
    cfg = HarnessConfig(driver="stub-oracle-v2", state_dir=str(tmp_path / "state"))
    cfg.repo = str(repo)
    session = ConversationalSession(cfg)
    files = parse_unified_diff(diff)
    assert len(files[0]["hunks"]) == 2
    session._pending_reviews["r"] = {
        "id": "r", "job_id": "", "target_repo": str(repo), "files": files,
    }
    svc = ReviewServices(cfg, lambda: session, lambda *a: None, lambda s: s)

    def apply(decisions, scope="selected"):
        return post_reviews_apply({"id": "r", "scope": scope, "decisions": decisions}, svc)[1]

    return session, files, target, base, apply


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("first", [0, 1])
@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_scoped_review_sequential_hunks(scoped_review, first, decision, legacy):
    session, files, target, base, apply = scoped_review
    hunks = files[0]["hunks"]
    if legacy:
        from harness.diffreview import resolve_hunk_decision_id
        for h in hunks:
            h.pop("decision_id")
        counts = {}
        ids = [resolve_hunk_decision_id(h, "multi.txt", counts) for h in hunks]
    else:
        ids = [h["decision_id"] for h in hunks]
    selected_id = ids[first]
    remaining_id = ids[1 - first]
    assert apply({selected_id: decision})["ok"]
    remaining = session._pending_reviews["r"]["files"][0]["hunks"]
    assert len(remaining) == 1
    assert remaining[0]["decision_id"] == remaining_id
    if first == 0 and decision == "accept":
        old_start = int(hunks[1]["header"].split("-")[1].split(",")[0])
        assert remaining[0]["header"].startswith(f"@@ -{old_start + 1},")
    assert not apply({selected_id: "accept"})["ok"], "stale click must not consume pending sibling"
    assert apply({remaining_id: "accept"})["ok"]
    expected = base
    if first != 0 or decision == "accept":
        expected = expected.replace("line 2\n", "line 2\ninserted\n")
    if first != 1 or decision == "accept":
        expected = expected.replace("line 25\n", "changed\n")
    assert target.read_text() == expected
    assert "r" not in session._pending_reviews


def test_scoped_review_failure_preserves_all_then_retry(scoped_review):
    session, files, target, base, apply = scoped_review
    first, second = [h["decision_id"] for h in files[0]["hunks"]]
    drift = base.replace("line 25\n", "user edit\n")
    target.write_text(drift)
    result = apply({first: "reject", second: "accept"})
    assert not result["ok"]
    assert target.read_text() == drift
    assert len(session._pending_reviews["r"]["files"][0]["hunks"]) == 2
    assert session._pending_reviews["r"]["error"]
    target.write_text(base)
    assert apply({second: "accept"})["ok"]
    assert "error" not in session._pending_reviews["r"]
    assert apply({first: "reject"})["ok"]
    assert target.read_text() == base.replace("line 25\n", "changed\n")


@pytest.mark.parametrize("decisions", [{}, {"missing": "accept"}, {"0:0": "reject"}])
def test_scoped_review_rejects_invalid_selection(scoped_review, decisions):
    session, files, target, base, apply = scoped_review
    assert not apply(decisions)["ok"]
    assert target.read_text() == base
    assert session._pending_reviews["r"]["files"] == files


def test_scoped_review_rejects_invalid_value_and_scope(scoped_review):
    session, files, target, base, apply = scoped_review
    did = files[0]["hunks"][0]["decision_id"]
    assert not apply({did: "pending"})["ok"]
    assert apply({did: "accept"}, "typo")["error"] == "Invalid review scope"
    assert target.read_text() == base
