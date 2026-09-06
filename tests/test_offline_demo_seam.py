"""Real-kernel demo regression with routing and external effects prohibited."""
import socket
from functools import partial

import pytest

from pmharness.bridge import execute_intent
from pmharness.intent import validate_intent


@pytest.fixture
def offline_demo(monkeypatch, tmp_path, _isolate_pilot_env, _isolate_provider_state):
    from puppetmaster import workers, router
    from puppetmaster.model_registry import ModelSpec, load_registry, save_registry
    from puppetmaster.orchestrator import Orchestrator

    def forbidden(*args, **kwargs):
        pytest.fail("offline demo attempted routing, network, or a provider adapter")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(router, "route_task", forbidden)
    original_adapter = workers.get_adapter

    def local_adapter(name, *args, **kwargs):
        if name != "local":
            forbidden()
        return original_adapter(name, *args, **kwargs)

    monkeypatch.setattr(workers, "get_adapter", local_adapter)
    original_catalog = Orchestrator._ensure_plan_catalog

    def guarded_catalog(self, job, specs):
        # Stop the pre-fix run before discovery can spawn a CLI or contact a provider.
        assert all(s.adapter == "local" and s.payload.get("auto_route") is False
                   for s in specs), "offline demo specs must explicitly disable auto_route"
        return original_catalog(self, job, specs)

    monkeypatch.setattr(Orchestrator, "_ensure_plan_catalog", guarded_catalog)
    monkeypatch.setenv("HARNESS_ALLOW_DEMO_SWARM", "1")
    monkeypatch.setenv("HARNESS_SWARM_ADAPTER", "demo")
    monkeypatch.setenv("PUPPETMASTER_STATE_DIR", str(tmp_path / "pm"))
    catalog = tmp_path / "models.json"
    monkeypatch.setenv("PUPPETMASTER_MODELS_PATH", str(catalog))
    save_registry([ModelSpec(id="offline-sentinel", adapter="agentic",
                            adapter_model_name="offline-sentinel", capability_score=100)], catalog)
    assert load_registry(catalog)
    # Registry boot and credential sync are unrelated to deterministic execution;
    # keep them from consulting the developer's catalog or credentials.
    monkeypatch.setattr("harness.marionette_registry.boot_marionette_registry", lambda: None)
    monkeypatch.setattr("pmharness.bridge._sync_agentic_credential_env", lambda: None)
    monkeypatch.setattr("pmharness.runner.execute_intent",
                        partial(execute_intent, worker_mode="inline"))
    return tmp_path


@pytest.mark.parametrize("roles", [None, ["explore", "test-coverage-reviewer"]])
def test_demo_persists_only_local_tasks(offline_demo, roles):
    from puppetmaster.store_factory import create_store
    from puppetmaster.workers import specs_for_roles

    state = str(offline_demo / "seam")
    intent = validate_intent({"action": "run_swarm", "goal": "Offline seam regression",
                              **({"roles": roles} if roles is not None else {})})
    result = execute_intent(intent, worker_mode="inline", state_dir=state)
    assert result and result.num_artifacts > 0
    store = create_store("sqlite", state)
    tasks = sorted(store.list_tasks(result.job_id), key=lambda t: t.role)
    expected = sorted(specs_for_roles(roles), key=lambda s: s.role)
    assert [t.role for t in tasks] == [s.role for s in expected]
    assert all(t.adapter == "local" and t.payload["auto_route"] is False for t in tasks)
    assert [t.instruction for t in tasks] == [s.instruction for s in expected]
    by_role = {t.role: t.id for t in tasks}
    assert [t.depends_on for t in tasks] == [
        [by_role[r] for r in s.depends_on_roles if r in by_role] for s in expected
    ]


def test_demo_still_requires_consent(offline_demo, monkeypatch):
    monkeypatch.delenv("HARNESS_ALLOW_DEMO_SWARM")
    with pytest.raises(ValueError, match="refusing demo substrate"):
        execute_intent(validate_intent({"action": "run_swarm", "goal": "Refuse demo"}),
                       worker_mode="inline", state_dir=str(offline_demo / "refused"))
