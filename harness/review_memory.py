from __future__ import annotations

"""Review + memory-proposal mixin for ConversationalSession.

Extracted mechanically from harness/conversation.py to continue decomposing the
ConversationalSession god-object, matching ToolDispatchMixin / WikiDistillMixin
contract: these methods operate through `self` (``_pending_reviews``,
``_pending_reviews_lock``, ``_apply_lock``, ``_turn_memory_queue``,
``_pending_memory_proposals``, ``_memory``, …) provided by the concrete class --
the mixin defines no state and no __init__.

``_apply_worker_patch`` stays on ConversationalSession (checkpoint / git-apply
path tightly coupled to host state). Swarm drain stays on the host; ``send``
lives on SendLoopMixin; busy lifecycle lives on BusyControlMixin.

Method Resolution Order keeps behavior identical: ``apply_review``,
``dismiss_review``, ``accept_memory_proposal``, etc. still resolve via
inheritance.
"""


class ReviewMemoryMixin:
    """Mixin holding pending-diff review apply/dismiss and memory-proposal helpers.

    The concrete class (ConversationalSession) supplies the state these
    methods read/write via `self`. This mixin defines no __init__ and no
    instance state of its own.
    """

    def apply_review(self, review_id: str, decisions: dict, scope: str = "review") -> dict:
        """Apply a whole review, or only explicit stable IDs in selected scope."""
        from copy import deepcopy
        import re
        from .diffreview import decision_for_hunk, reconstruct_diff, resolve_hunk_decision_id

        def failure(message):
            return {"ok": False, "applied_files": [], "rejected_hunks": [],
                    "checkpoint_id": None, "message": message}

        if scope not in ("review", "selected"):
            return failure("Invalid review scope")
        if not isinstance(decisions, dict):
            return failure("Invalid review decisions")

        # Serialize selection, repository application, and queue replacement so
        # concurrent clicks cannot replay a stale snapshot of the review.
        with self._apply_lock:
            with self._pending_reviews_lock:
                original = self._pending_reviews.get(review_id)
                if not original:
                    return failure("Pending review not found")
                review = deepcopy(original)

            counts: dict[str, int] = {}
            known = set()
            for f in review["files"]:
                for h in f["hunks"]:
                    did = resolve_hunk_decision_id(h, f["path"], counts)
                    h["decision_id"] = did
                    known.add(did)
            if scope == "selected" and (
                not decisions or not set(decisions).issubset(known)
                or any(value not in ("accept", "reject") for value in decisions.values())
            ):
                return failure("Select pending hunks by stable decision ID with accept/reject decisions")

            selected = {}
            rejected_hunks = []
            applied_files = []
            remaining_files = []
            header_pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
            for f in review["files"]:
                pending = []
                accepted_shift = 0
                rejected_shift = 0
                for h in f["hunks"]:
                    did = h["decision_id"]
                    match = header_pattern.match(h["header"])
                    if scope == "selected" and did not in decisions:
                        remaining = dict(h)
                        if match and (accepted_shift or rejected_shift):
                            old_start, old_count, new_start, new_count = match.groups()
                            remaining["header"] = (
                                f"@@ -{int(old_start) + accepted_shift},{old_count or '1'} "
                                f"+{int(new_start) - rejected_shift},{new_count or '1'} @@"
                                + h["header"][match.end():]
                            )
                        pending.append(remaining)
                        continue
                    decision = decision_for_hunk(decisions, h, f["path"])
                    selected[did] = decision
                    delta = int(match.group(4) or 1) - int(match.group(2) or 1) if match else 0
                    if decision == "accept":
                        if f["path"] not in applied_files:
                            applied_files.append(f["path"])
                        accepted_shift += delta
                    else:
                        rejected_hunks.append(h["id"])
                        rejected_shift += delta
                if pending:
                    remaining_files.append({**f, "hunks": pending})

            accepted_diff = reconstruct_diff(review["files"], selected)
            cp_id = None
            files_changed = []
            apply_msg = "Selected hunks were rejected. No changes applied."
            if applied_files:
                applied, files_changed, apply_msg = self._apply_worker_patch(
                    [{"type": "patch", "payload": {
                        "files": applied_files, "unified_diff": accepted_diff,
                    }}],
                    review.get("job_id", ""), repo=review.get("target_repo", ""),
                )
                cp_id = getattr(self, "_last_checkpoint_id", None)
                if not applied:
                    err_msg = f"Failed to apply: {apply_msg}"
                    with self._pending_reviews_lock:
                        still = self._pending_reviews.get(review_id)
                        if still is not None:
                            still["error"] = err_msg
                    return {"ok": False, "applied_files": [], "rejected_hunks": rejected_hunks,
                            "checkpoint_id": cp_id, "message": err_msg}
                apply_msg = f"Successfully applied: {apply_msg}"

            with self._pending_reviews_lock:
                if review_id in self._pending_reviews:
                    if remaining_files:
                        review["files"] = remaining_files
                        review.pop("error", None)
                        self._pending_reviews[review_id] = review
                    else:
                        self._pending_reviews.pop(review_id, None)
            return {"ok": True, "applied_files": files_changed,
                    "rejected_hunks": rejected_hunks, "checkpoint_id": cp_id,
                    "message": apply_msg}

    def dismiss_review(self, review_id: str) -> bool:
        with self._pending_reviews_lock:
            if review_id in self._pending_reviews:
                self._pending_reviews.pop(review_id)
                return True
            return False

    def _flush_turn_memory_proposals(self) -> list:
        """Move queued mid-turn memory-add hints into pending Save/Skip cards.

        Called only after assistant_done on interactive turns. Caps at 3
        proposals. Nothing is written to the store until accept_memory_proposal.
        """
        queued = list(self._turn_memory_queue or [])
        self._turn_memory_queue = []
        if not queued:
            return []
        import uuid as _uuid
        out = []
        # Exact-text dedupe against already-persisted entries and against
        # proposals already pending from earlier turns.
        existing_texts = {
            (e.text or "").strip().lower() for e in self._memory.list()
        }
        for p in self._pending_memory_proposals.values():
            existing_texts.add((p.get("text") or "").strip().lower())
        for item in queued:
            if len(out) >= 3:
                break
            text = (item.get("text") or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in existing_texts:
                continue
            existing_texts.add(key)
            prop_id = "memprop_" + _uuid.uuid4().hex[:12]
            cat = (item.get("category") or "general").strip() or "general"
            prop = {
                "id": prop_id,
                "text": text,
                "category": cat,
            }
            self._pending_memory_proposals[prop_id] = prop
            out.append(prop)
        return out

    def accept_memory_proposal(self, proposal_id: str) -> dict:
        """Persist a pending end-of-turn memory proposal (source=agent)."""
        prop = self._pending_memory_proposals.pop(proposal_id, None)
        if not prop:
            return {"ok": False, "error": "proposal not found"}
        text = (prop.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "empty proposal"}
        entry = self._memory.add(
            text=text,
            category=(prop.get("category") or "general").strip() or "general",
            source="agent",
        )
        return {
            "ok": True,
            "id": entry.id,
            "text": entry.text,
            "category": entry.category,
            "source": entry.source,
            "created_at": entry.created_at,
        }

    def dismiss_memory_proposal(self, proposal_id: str) -> dict:
        """Drop a pending end-of-turn memory proposal without writing."""
        if proposal_id in self._pending_memory_proposals:
            self._pending_memory_proposals.pop(proposal_id, None)
            return {"ok": True}
        return {"ok": False, "error": "proposal not found"}
