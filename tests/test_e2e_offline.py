"""End-to-end: StubDriver -> validated intent -> REAL Puppetmaster local
adapter -> scoring -> ledger. Proves the whole rig with zero API keys.

Marked as the canonical 'rig works' gate. If this passes, the harness can drive
Puppetmaster in-process and score it; only the driver model is swappable.
"""
import tempfile
from pathlib import Path

import pytest

from test_offline_demo_seam import offline_demo

from pmharness.registry import build
from pmharness.ledger import Ledger
from pmharness.runner import run_driver, new_run_id
from pmharness.bridge import execute_intent
from pmharness.intent import validate_intent

pytestmark = pytest.mark.usefixtures("offline_demo")


def test_bridge_executes_real_puppetmaster():
    """The bridge actually drives PM's Orchestrator in-process and gets
    structured artifacts back -- no MCP, no CLI subprocess."""
    intent = validate_intent({"action": "run_swarm", "goal": "E2E: smoke the seam"})
    res = execute_intent(intent, worker_mode="inline")
    assert res is not None
    assert res.status == "JobStatus.COMPLETE" or "complete" in res.status.lower()
    assert res.num_artifacts > 0
    assert res.artifact_types  # non-empty
    # compact artifacts are feedable back to a driver
    assert all("type" in a and "headline" in a for a in res.artifacts)


def test_non_swarm_intent_does_not_execute():
    assert execute_intent(validate_intent({"action": "answer"})) is None
    assert execute_intent(validate_intent({"action": "stop"})) is None


def test_full_stub_run_scores_perfect():
    """The oracle stub should ace the battery: it is the ceiling control."""
    tmp = tempfile.mkdtemp(prefix="pmh-e2e-")
    ledger = Ledger(Path(tmp) / "ledger.sqlite")
    run_id = new_run_id()
    scores = run_driver(build("stub-oracle"), ledger, run_id=run_id, execute=True)

    assert len(scores) == 10
    mean = sum(s.score for s in scores) / len(scores)
    assert mean == 1.0, f"stub oracle should score perfectly, got {mean}"

    # every swarm case that must_execute actually produced artifacts
    swarm_exec = [s for s in scores if s.executed_ok is not None]
    assert swarm_exec and all(s.executed_ok for s in swarm_exec)

    # ledger persisted every attempt
    summary = ledger.summary(run_id)
    assert len(summary) == 1
    assert summary[0]["model"] == "stub-oracle"
    assert summary[0]["avg_score"] == 100.0
    ledger.close()
