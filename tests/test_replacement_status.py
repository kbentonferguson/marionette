from harness.pilot_replacement import LivePilotReplacement
from harness.session_runners import SessionRunnerRegistry
from tests.test_input_receipts_integration import session


def test_model_replacement_reservation_is_attaching_not_a_running_turn(session):
    runners = SessionRunnerRegistry(max_concurrent_sessions=1)
    sid = session.harness_session_id
    runners.get_or_create(sid, lambda: session)
    with LivePilotReplacement(session):
        assert session.state() == 'idle'
        assert runners.status(sid) == 'attaching'
    assert runners.status(sid) == 'idle'
