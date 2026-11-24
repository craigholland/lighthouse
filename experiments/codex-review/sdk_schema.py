"""Translate selected pinned public SDK schemas without creating a client."""

from typing import Literal

from harness import Outcome, Run
from openai_codex.types import ThreadReadResponse, TurnCompletedNotification, TurnStatus
from pydantic import ValidationError


def completion(payload: object, run: Run) -> Outcome:
    """Map a matching terminal notification or return a sanitized unknown outcome."""
    try:
        note = TurnCompletedNotification.model_validate(payload)
    except ValidationError:
        return "unknown"
    if (note.thread_id, note.turn.id) != (run.thread, run.turn):
        return "unknown"
    return _outcome(note.turn.status, terminal=True)


def observed_run(payload: object, run: Run) -> Outcome:
    """Extract only the known turn from a typed thread read; no error body escapes."""
    try:
        note = ThreadReadResponse.model_validate(payload)
    except ValidationError:
        return "unknown"
    matches = [turn for turn in note.thread.turns if turn.id == run.turn]
    if note.thread.id != run.thread or len(matches) != 1:
        return "unknown"
    status = note.thread.status.root
    if status.type == "systemError":
        return "unavailable"
    if status.type == "active" and any(
        flag.value == "waitingOnApproval" for flag in status.active_flags
    ):
        return "permission"
    if matches[0].status == TurnStatus.in_progress and (
        status.type != "active" or status.active_flags
    ):
        return "unknown"
    return _outcome(matches[0].status, terminal=False)


def _outcome(status: TurnStatus, *, terminal: bool) -> Literal[
    "complete", "interrupted", "rejected", "running", "unknown"
]:
    match status:
        case TurnStatus.completed:
            return "complete"
        case TurnStatus.interrupted:
            return "interrupted"
        case TurnStatus.failed:
            return "rejected"
        case TurnStatus.in_progress:
            return "unknown" if terminal else "running"
