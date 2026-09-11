"""Bridge-to-metadata handoff regressions using the real Puppetmaster store."""
from __future__ import annotations

import threading
from queue import Queue
from dataclasses import asdict
from types import SimpleNamespace

from harness.job_readmodel import ActiveContext, KnownSources, MetadataReader, PMSelection, ReadContext
from harness.local_jobs import LocalJobsMixin
from harness.send_loop_phases import stream_swarm
from pmharness.intent import DriverIntent


class _LocalRunner(LocalJobsMixin):
    def __init__(self, path):
        self.config = SimpleNamespace(repo=str(path), driver="stub")
        self.state_dir = str(path)
        self.harness_session_id = "session-owner"
        self._local_jobs = {}
        self._local_jobs_lock = threading.Lock()
        self._local_job_cancels = {}
        self._local_jobs_path = str(path / "swarm_local_jobs.json")
        self._display_transcript = []
        self._load_local_jobs()


def test_stream_swarm_publishes_canonical_ref_while_five_workers_are_queued(monkeypatch, tmp_path):
    """The live bridge callback must bind the placeholder before worker completion."""
    from puppetmaster.orchestrator import Orchestrator
    from puppetmaster.store_factory import create_store

    monkeypatch.setenv("HARNESS_ALLOW_DEMO_SWARM", "1")
    monkeypatch.setenv("HARNESS_REPO", "")
    runner = _LocalRunner(tmp_path / "local")
    runner.config.repo = ""
    runner.state_dir = str(tmp_path / "pm")
    dispatch_id = "dispatch-handoff"
    local_id = f"local-swarm-{dispatch_id}"
    runner._register_local_job(
        local_id, "prove canonical handoff", role="explore", engine="agentic",
        dispatch_id=dispatch_id, skip_routing_preview=True,
    )
    entered = threading.Event()
    release = threading.Event()
    created = []
    events = Queue()
    original = Orchestrator._run_workers

    def block_workers(self, job, tasks, **kwargs):
        entered.set()
        assert release.wait(15), "test must inspect the running metadata before workers run"
        return original(self, job, tasks, **kwargs)

    monkeypatch.setattr(Orchestrator, "_run_workers", block_workers)

    original_associate = runner._associate_local_job_with_pm

    def associate(job_id, value):
        created.append(value)
        original_associate(job_id, value)

    monkeypatch.setattr(runner, "_associate_local_job_with_pm", associate)

    intent = DriverIntent(
        action="run_swarm", goal="prove canonical handoff",
        roles=["explore", "review", "test", "security-review", "conflict-auditor"],
    )

    thread = threading.Thread(target=stream_swarm, kwargs=dict(
        session=runner, intent=intent, delta_q=events, dispatch_id=dispatch_id,
        worker_mode="inline",
    ))
    thread.start()
    try:
        assert entered.wait(15), "real Orchestrator never reached its worker lifecycle"
        assert len(created) == 1
        association = created[0]
        assert association["source"] == "harness"
        assert association["session_id"] == runner.harness_session_id
        assert association["dispatch_id"] == dispatch_id
        assert association["job_ref"]["version"] == 2
        assert set(association["job_ref"]) == {"job_id", "state_id", "version", "incarnation"}

        store = create_store("sqlite", tmp_path / "pm")
        ctx = ReadContext(runner.harness_session_id, str(tmp_path / "repo"), "view-handoff", "session")
        sources = KnownSources.from_roots([("harness", store.root, "sqlite", False)])
        reader = MetadataReader(lambda: ActiveContext(ctx.session_id, ctx.repo, ctx.view_generation), sources)
        page = reader.read_job_page(ctx, sources.stores[0].selection)
        assert len(page["rows"]) == 1
        row = page["rows"][0]
        assert row["selection"]["job_ref"] == association["job_ref"]
        assert row["lifecycle"] == "running"
        assert row["ownership"] == {"origin": "marionette", "session_id": runner.harness_session_id, "project_id": None}
        assert row["task_count"] == 5

        selection = PMSelection(ctx, sources.stores[0].selection, store.job_ref(association["job_ref"]["job_id"]))
        detail = reader.read_selected_metadata(selection)
        assert len(detail["tasks"]["rows"]) == 5
        assert {task["status"] for task in detail["tasks"]["rows"]} == {"queued"}
        expert_tasks = detail["expert"]["tasks"]
        assert {task["role"] for task in expert_tasks} == set(intent.roles)
        assert {task["adapter"] for task in expert_tasks} == {"local"}
        assert {task["model"] for task in expert_tasks} == {None}
        assert detail["expert"]["artifacts"] == []

        local = runner.local_metadata_handle().read_page(asdict(ctx))
        assert len(local["rows"]) == 1
        assert local["rows"][0]["canonical"] == association
    finally:
        release.set()
        thread.join(30)

    assert not thread.is_alive()
    kind, result = events.get_nowait()
    assert kind == "done", result
    assert result.job_id == association["job_ref"]["job_id"]
    assert result.adapter == "demo"
    assert result.artifacts
