"""Harness E2E: the product Session drives real Puppetmaster offline via the
stub driver. Proves the loop end to end with zero keys before any GUI."""
import tempfile

import pytest

from test_offline_demo_seam import offline_demo

from harness.config import HarnessConfig
from harness.session import Session

pytestmark = pytest.mark.usefixtures("offline_demo")


def _stub_session():
    cfg = HarnessConfig(driver="stub-oracle-v2", reach="openrouter",
                        budget=3, worker_mode="inline",
                        state_dir=tempfile.mkdtemp(prefix="harness-t-"))
    return Session(cfg)


def test_session_drives_real_pm_and_terminates():
    s = _stub_session()
    events = list(s.run("Investigate how authentication works across this codebase."))
    kinds = [e.kind for e in events]
    assert "intent" in kinds
    assert "executing" in kinds
    assert "artifacts" in kinds
    assert kinds[-1] == "final"
    # a real PM job ran and produced artifacts
    art_ev = [e for e in events if e.kind == "artifacts"][0]
    assert art_ev.data["num"] > 0
    assert art_ev.data["job_id"]


def test_trivial_answers_without_swarm():
    s = _stub_session()
    res = s.run_collect("What does the acronym JSON stand for?")
    assert res.terminal_action == "answer"
    assert res.swarms_run == 0


def test_durable_state_reads_back_jobs():
    s = _stub_session()
    res = s.run_collect("Audit this repository for the single biggest risk.")
    assert res.terminal_action in ("stop", "answer")
    st = s.state()
    jobs = st.list_jobs()
    assert len(jobs) >= 1
    # artifacts readable for the GUI
    arts = st.job_artifacts(jobs[0]["id"])
    assert isinstance(arts, list)


def test_budget_is_respected():
    s = _stub_session()
    res = s.run_collect("Investigate how authentication works across this codebase.")
    assert res.swarms_run <= 3  # config budget
