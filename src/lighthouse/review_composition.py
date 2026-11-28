
"""Outer, explicitly injected T07 composition; never constructed by the CLI."""

import json
from collections.abc import Callable
from pathlib import Path

from lighthouse.adapters.codex.stdio import (
    ReviewRequest,
    StdioReviewWorker,
    _Hold,
    _safe_comment,
)
from lighthouse.adapters.github.review_publisher import ReviewPublisher, ReviewTarget
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.review_dispatch import (
    Attempt,
    Cleanup,
    Completion,
    Lifecycle,
    Remote,
    ReviewDispatch,
    ReviewInput,
    Stage,
    StartupDiagnostic,
    Target,
    digest,
)
from lighthouse.domain.workflow import Project


def parse_outcome(text: str) -> tuple[str, str]:
    """Accept one explicit review event and body; no verdict inference."""

    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        value = dict(items)
        if len(value) != len(items):
            raise ValueError("duplicate-review-field")
        return value

    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict) or value.keys() != {"event", "body"}:
        raise ValueError("invalid-review-outcome")
    event, body = value["event"], value["body"]
    if (not isinstance(event, str) or event not in {"COMMENT", "APPROVE", "REQUEST_CHANGES"}
            or not isinstance(body, str) or not body.strip() or len(body.encode()) > 16384
            or "<!-- lighthouse:" in body or any(ord(c) < 32 and c not in "\r\n\t" for c in body)):
        raise ValueError("invalid-review-outcome")
    return event, body


def compose_review_dispatch(
    project: Project, ledger: SQLiteLedger, worker: StdioReviewWorker, publisher: ReviewPublisher,
    *, current: Callable[[Target], bool], enqueue: Callable[[Callable[[], None]], None],
    deadlines: Callable[[], tuple[float, float]], workspace: Path, model: str,
    structured: bool = False,
    worker_context: tuple[str, str] | None = None,
    expected_event: str | None = None,
) -> ReviewDispatch:
    """Connect a committed ledger to separately supplied execution and publication boundaries.

    The owner supplies a non-blocking queue and fixed workspace. No live queue,
    native session, credentials, or GitHub reviewer client is selected here.
    """

    class Comment:
        def submit(self, target: Target, marker: str, text: str) -> int:
            exact = ReviewTarget(target.repository, target.pr, target.head, project.lead, marker)
            receipt = publisher.publish(exact, text)
            if receipt.target != exact or receipt.output_digest != digest(text):
                raise ValueError("wrong-publication-receipt")
            return receipt.review_id

        def lookup(self, target: Target, marker: str, output: str) -> int | None:
            exact = ReviewTarget(target.repository, target.pr, target.head, project.lead, marker)
            receipt = publisher.lookup(exact)
            return receipt.review_id if receipt and receipt.target == exact and receipt.output_digest == output else None

    def formal_target(attempt: Attempt) -> ReviewTarget:
        target = attempt.target
        return ReviewTarget(target.repository, target.pr, target.head, project.lead, attempt.marker, attempt.event)

    def submit_formal(attempt: Attempt, text: str) -> int | None:
        exact = formal_target(attempt)
        receipt = publisher.publish(exact, text)
        return receipt.review_id if receipt.target == exact and receipt.output_digest == attempt.output else None

    def lookup_formal(attempt: Attempt) -> int | None:
        exact = formal_target(attempt)
        receipt = publisher.lookup(exact)
        return receipt.review_id if receipt and receipt.target == exact and receipt.output_digest == attempt.output else None

    class Executor:
        def start(self, request: ReviewInput, begin: Callable[[], bool],
                  accept: Callable[[str, str], bool]) -> None:
            target = request.target
            fingerprint = request.fingerprint()
            limit, cleanup_limit = deadlines()

            def acknowledge(thread: str, turn: str) -> None:
                if not accept(thread, turn):
                    raise ValueError("execution-identity-not-retained")

            def run() -> None:
                # Read the provider outside the writer lock, then atomically check T04 and claim.
                try:
                    selected = current(target) is True
                except Exception:
                    selected = False
                if not selected:
                    service.hold(target.dispatch, fingerprint, Stage.UNAVAILABLE)
                    return
                if not begin():
                    return
                instructions, context = worker_context or (request.instructions, request.context)
                result = worker.run(
                    ReviewRequest(target.repository, target.issue, target.pr, target.head, workspace,
                                  model, context, instructions, target.binding.verification, structured),
                    limit, on_identity=acknowledge, cleanup_deadline=cleanup_limit,
                )
                old = service.status(target.dispatch).attempt
                if old is None or old.fingerprint != fingerprint:
                    return
                if result.comment is not None and result.thread_id and result.turn_id:
                    try:
                        event, body = parse_outcome(result.comment) if structured else ("COMMENT", result.comment)
                        if expected_event is not None and event != expected_event:
                            raise ValueError("review-event-not-authorized")
                        if structured:
                            body = _safe_comment(body, workspace)
                    except (ValueError, RecursionError, _Hold):
                        service.hold(
                            target.dispatch, fingerprint, Stage.EXECUTION_UNKNOWN, old.thread, old.turn,
                            lifecycle=Lifecycle(Remote.COMPLETED, Cleanup.CONFIRMED if result.owned_cleanup
                                                else Cleanup.UNCONFIRMED),
                        )
                        return
                    status = service.complete(target.dispatch, Completion(
                        fingerprint, result.thread_id, result.turn_id, body, result.owned_cleanup, event,
                    ))
                    if status.stage is Stage.COMPLETED:
                        service.publish(target.dispatch, body)
                    return
                stage = (
                    Stage.APPROVAL_REQUIRED if result.hold_reason == "permission-attention" else
                    Stage.UNKNOWN_AND_CLEANUP if result.acceptance_unknown and not result.owned_cleanup else
                    Stage.CLEANUP_UNCONFIRMED if result.session_started and not result.owned_cleanup else
                    Stage.EXECUTION_UNKNOWN if result.acceptance_unknown or old.thread else Stage.UNAVAILABLE
                )
                lifecycle = Lifecycle(
                    Remote.COMPLETED if result.remote_completed else
                    Remote.UNKNOWN if result.acceptance_unknown or old.thread else Remote.NOT_STARTED,
                    Cleanup.CONFIRMED if result.owned_cleanup else
                    Cleanup.UNCONFIRMED if result.session_started else Cleanup.NOT_NEEDED,
                    result.hold_reason == "permission-attention",
                )
                service.hold(
                    target.dispatch, fingerprint, stage, old.thread, old.turn, lifecycle=lifecycle,
                    startup=StartupDiagnostic.from_worker(result.hold_reason, result.startup_progress),
                )

            enqueue(run)

    service = ReviewDispatch(
        project, ledger, Executor(), Comment(), current, formal_submit=submit_formal, formal_lookup=lookup_formal,
    )
    return service
