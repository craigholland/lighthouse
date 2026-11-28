"""Private explicit selection of dormant runtime and review bindings."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from lighthouse.adapters.codex.stdio import StdioReviewWorker
from lighthouse.adapters.codex.windows_session import (
    Child,
    PrivateWindowsReview,
    WindowsReviewOwner,
)
from lighthouse.adapters.github.review_http import HTTPSReviewClient
from lighthouse.adapters.github.review_publisher import ReviewPublisher
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.review_dispatch import ReviewDispatch, Target
from lighthouse.domain.workflow import Project
from lighthouse.review_composition import compose_review_dispatch


@dataclass(frozen=True, repr=False)
class PrivateRuntimeBinding:
    """Private caller-selected target and independently provided runtime/publisher bindings."""

    target: Target
    windows: PrivateWindowsReview
    model: str
    github_bearer: str = field(repr=False)
    execution_seconds: float = 90
    cleanup_seconds: float = 5


def bind_review(
    project: Project, ledger: SQLiteLedger, binding: PrivateRuntimeBinding, *,
    current_authority: Callable[[Target], bool],
    current_lead: Callable[[str, int, str], int | None],
    enqueue: Callable[[Callable[[], None]], None],
    native_boundary: Callable[[], Child] | None = None,
    structured: bool = False,
    worker_context: tuple[str, str] | None = None,
    expected_event: str | None = None,
) -> ReviewDispatch:
    """Select concrete adapters without starting work, opening a child or contacting GitHub."""
    target = binding.target
    if (
        not target.valid() or target.repository != project.repository
        or target.repository != binding.windows.repository or target.binding.profile != project.profile
        or not math.isfinite(binding.execution_seconds) or not 0 < binding.execution_seconds <= 300
        or not math.isfinite(binding.cleanup_seconds) or not 0 < binding.cleanup_seconds <= 10
    ):
        raise ValueError("invalid dormant review binding")
    window = binding.windows
    owner = WindowsReviewOwner(window) if native_boundary is None else WindowsReviewOwner(window, child=native_boundary)

    def current(selected: Target) -> bool:
        return selected == target and current_authority(selected) is True

    def deadlines() -> tuple[float, float]:
        end = monotonic() + binding.execution_seconds
        return end, end + binding.cleanup_seconds

    worker = StdioReviewWorker(
        lambda request, end: owner.open(request, end, end + binding.cleanup_seconds),
        owner.checkout_matches, monotonic,
    )
    http = HTTPSReviewClient(project.repository, target.pr, binding.github_bearer, current_lead)
    publisher = ReviewPublisher(http, repository=project.repository)
    return compose_review_dispatch(
        project, ledger, worker, publisher, current=current, enqueue=enqueue, deadlines=deadlines,
        workspace=window.workspace, model=binding.model, structured=structured, worker_context=worker_context,
        expected_event=expected_event,
    )
