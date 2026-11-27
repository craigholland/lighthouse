
"""Outer, explicitly injected T07 composition; never constructed by the CLI."""

from collections.abc import Callable
from pathlib import Path

from lighthouse.adapters.codex.stdio import ReviewRequest, StdioReviewWorker
from lighthouse.adapters.github.review_publisher import ReviewPublisher, ReviewTarget
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.review_dispatch import (
    Completion,
    ReviewDispatch,
    ReviewInput,
    Stage,
    Target,
    digest,
)
from lighthouse.domain.workflow import Project


def compose_review_dispatch(
    project: Project, ledger: SQLiteLedger, worker: StdioReviewWorker, publisher: ReviewPublisher,
    *, current: Callable[[Target], bool], enqueue: Callable[[Callable[[], None]], None],
    deadlines: Callable[[], tuple[float, float]], workspace: Path, model: str,
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
                # The PR can move while the deliberate outer queue is waiting.
                if not begin():
                    return
                try:
                    selected = current(target) is True
                except Exception:
                    selected = False
                if not selected:
                    service.hold(target.dispatch, fingerprint, Stage.UNAVAILABLE)
                    return
                result = worker.run(
                    ReviewRequest(target.repository, target.issue, target.pr, target.head, workspace,
                                  model, request.context, request.instructions, target.binding.verification),
                    limit, on_identity=acknowledge, cleanup_deadline=cleanup_limit,
                )
                old = service.status(target.dispatch).attempt
                if old is None or old.fingerprint != fingerprint:
                    return
                if result.comment is not None and result.thread_id and result.turn_id:
                    status = service.complete(target.dispatch, Completion(
                        fingerprint, result.thread_id, result.turn_id, result.comment, result.owned_cleanup,
                    ))
                    if status.stage is Stage.COMPLETED:
                        service.publish(target.dispatch, result.comment)
                    return
                stage = (
                    Stage.APPROVAL_REQUIRED if result.hold_reason == "permission-attention" else
                    Stage.UNKNOWN_AND_CLEANUP if result.acceptance_unknown and not result.owned_cleanup else
                    Stage.CLEANUP_UNCONFIRMED if result.session_started and not result.owned_cleanup else
                    Stage.EXECUTION_UNKNOWN if result.acceptance_unknown or old.thread else Stage.UNAVAILABLE
                )
                service.hold(target.dispatch, fingerprint, stage, old.thread, old.turn)

            enqueue(run)

    service = ReviewDispatch(project, ledger, Executor(), Comment(), current)
    return service
