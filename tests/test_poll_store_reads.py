from collections import Counter

from harness.cli_job_merge import merge_running_cli_jobs_all_projects


def test_cross_project_poll_reads_each_store_once(monkeypatch):
    counts = Counter()

    class Store:
        busy_timeout_ms = 0

        def list_jobs(self):
            counts['jobs'] += 1
            return []

        def list_tasks_for_jobs(self, ids):
            return []

        def count_artifacts_for_jobs(self, ids):
            return {}

    def create(*args):
        counts['opens'] += 1
        return Store()

    monkeypatch.setattr('harness.state.create_store', create)
    monkeypatch.setattr('harness.cli_job_merge._foreign_state_dir_candidates',
                        lambda primary: ['/tmp/poll-a', '/tmp/poll-b', '/tmp/poll-c'])
    for _ in range(5):
        assert merge_running_cli_jobs_all_projects(seen_ids=set(), tasks_by_job={}) == []
    assert counts == {'opens': 15, 'jobs': 15}
