"""Optimistic client input_id on first send must admit, not raise input_unknown."""

import uuid

import pytest

from harness.api.streams import _admit_stream_input
from harness.input_receipts import InputReceiptError, session_input_store
from tests.test_input_receipts_integration import session  # noqa: F401


def test_optimistic_first_send_input_id_admits_new_receipt(session):
    """Comet allocateOptimisticInputId always sends input_id before any receipt exists."""
    optimistic = uuid.uuid4().hex
    receipt, args, text, images = _admit_stream_input(
        session,
        'hello optimistic',
        [],
        str(session.state_dir),
        input_id=optimistic,
        retry_key='rk-' + optimistic[:8],
    )
    assert receipt['id'] == optimistic
    assert args['input_id'] == optimistic
    assert receipt['status'] == 'accepted'
    assert text == 'hello optimistic'
    assert images == []
    assert session_input_store(session).get(optimistic)['original_text'] == 'hello optimistic'


def test_optimistic_input_id_with_handoff_still_requires_existing_receipt(session):
    missing = uuid.uuid4().hex
    with pytest.raises(InputReceiptError) as excinfo:
        _admit_stream_input(
            session,
            'handoff without receipt',
            [],
            str(session.state_dir),
            input_id=missing,
            handoff_token='tok',
        )
    assert excinfo.value.code == 'input_unknown'
    assert session.input_receipts() == []


def test_existing_accepted_input_id_reuses_receipt_without_re_admit(session):
    first, _args, _, _ = _admit_stream_input(
        session, 'once', [], str(session.state_dir), input_id=uuid.uuid4().hex,
    )
    again, args2, text, _ = _admit_stream_input(
        session, 'ignored on reuse', [], str(session.state_dir), input_id=first['id'],
    )
    assert again['id'] == first['id'] == args2['input_id']
    assert text == 'once'
    assert len(session.input_receipts()) == 1
