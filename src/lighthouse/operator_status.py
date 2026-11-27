"""Read-only, secret-free status for a selected existing SQLite project."""

import json
import re
from pathlib import Path

from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.ledger import IntentStatus
from lighthouse.application.review_dispatch import Stage
from lighthouse.domain.workflow import Outcome

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")


def _reference(value: str | None, pattern: str) -> str | None:
    return value if value is not None and re.fullmatch(pattern, value) else None


def render_status(path: Path, repository: str, dispatch: str | None) -> str:
    """Render only normalized identities, never bodies, credentials or machine paths."""
    if (not _REPOSITORY.fullmatch(repository) or any(x in {".", ".."} for x in repository.split("/"))
            or (dispatch is not None and _reference(dispatch, r"[0-9a-f]{64}") is None)):
        raise ValueError("invalid status selector")
    ledger = SQLiteLedger(path, read_only=True)
    view = ledger.operator_snapshot(repository, dispatch)
    state, intent, attempt = view.state, view.intent, view.attempt
    work = state.work if dispatch is None else None
    stage = attempt.stage if attempt else None
    if stage in {Stage.CLAIMED, Stage.STARTING}:
        stage = Stage.EXECUTION_UNKNOWN
    result: dict[str, object] = {
        "project": repository, "phase": state.outcome.value,
        "issue": view.issue,
        "work": _reference(intent.order if intent else work.order if work else None, r"[A-Za-z0-9_-]{1,100}"),
        "pr": intent.pr if intent else work.pr if work else None,
        "head": _reference(intent.head if intent else None, r"[0-9a-f]{40}"),
        "dispatch": _reference(intent.dispatch_id, r"[0-9a-f]{64}") if intent else dispatch,
    }
    if attempt is not None:
        owner = stage in {
            Stage.EXECUTION_UNKNOWN, Stage.CLEANUP_UNCONFIRMED, Stage.UNKNOWN_AND_CLEANUP,
            Stage.APPROVAL_REQUIRED, Stage.PUBLISHING,
        }
        result.update(
            status=stage, remote=attempt.lifecycle.remote, local_cleanup=attempt.lifecycle.cleanup,
            approval_required=attempt.lifecycle.approval, causes=attempt.lifecycle.causes,
            thread=attempt.thread or None, turn=attempt.turn or None,
            review=attempt.review_id or None, dispatch_next_actor="owner" if owner else "lead",
        )
    elif intent is not None:
        result.update(status=intent.status.value)
        if intent.status is IntentStatus.PENDING:
            result["dispatch_next_actor"] = view.assignee
    elif dispatch is not None:
        result.update(status="not-found")
    elif state.outcome.value == "hold":
        result.update(status="held")
    if view.decision is not None:
        decision = view.decision
        next_actor = decision.actor
        # An unchanged observation can preserve approval of the same outstanding action,
        # but cannot borrow guidance from a different work order, PR, or head.
        if (
            next_actor is None and state.outcome is not Outcome.HOLD
            and decision.outcome is Outcome.UNCHANGED and decision.reason == "already-recommended"
            and intent is not None and intent.status is IntentStatus.PENDING and attempt is None
            and state.work is not None and (state.work.issue, state.work.order) == (view.issue, intent.order)
            and state.outcome.value == intent.operation and state.work.pr == intent.pr
            and (intent.head is None or decision.evidence[:1] == (intent.head,))
        ):
            next_actor = view.assignee
        result.update(
            decision_reason=_reference(view.decision.reason, r"[a-z0-9-]{1,100}"),
            decision_actor=view.decision.actor,
            next_actor=next_actor,
        )
    return json.dumps(result, sort_keys=True)
