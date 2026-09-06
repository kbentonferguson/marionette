"""Analysis benchmark scoring + the unindexed-repo guard (the bug the bench caught)."""
import pytest
pytestmark = pytest.mark.swarm
from pmharness import bridge


def test_unindexed_repo_warns(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "norepo"; repo.mkdir()
    monkeypatch.delenv("HARNESS_REQUIRE_CODEGRAPH", raising=False)
    bridge._warn_if_unindexed(str(repo))
    err = capsys.readouterr().err
    assert "no .codegraph index" in err and "BLIND" in err


def test_unindexed_repo_hard_fails_when_required(monkeypatch, tmp_path):
    repo = tmp_path / "norepo"; repo.mkdir()
    monkeypatch.setenv("HARNESS_REQUIRE_CODEGRAPH", "1")
    with pytest.raises(RuntimeError):
        bridge._warn_if_unindexed(str(repo))


def test_indexed_repo_no_warning(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"; (repo / ".codegraph").mkdir(parents=True)
    bridge._warn_if_unindexed(str(repo))
    assert capsys.readouterr().err == ""
