"""Identity fence for a single displayed command approval registration."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ApprovalExpectation:
    action_id: str
    approval_id: str


class StaleApprovalError(Exception):
    """The caller must refresh the card and obtain a new human decision."""


def require_current_approval(pending: dict, expected: Optional[ApprovalExpectation]) -> None:
    if expected is None or not expected.action_id or not expected.approval_id:
        raise StaleApprovalError('approval_refresh_required')
    if not pending.get('approval_id'):
        raise StaleApprovalError('approval_refresh_required')
    if (pending.get('action_id'), pending['approval_id']) != (expected.action_id, expected.approval_id):
        raise StaleApprovalError('stale_approval')
