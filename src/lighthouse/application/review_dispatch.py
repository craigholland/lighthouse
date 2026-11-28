
"""Durable post-commit dispatch for one exact-head review and separate COMMENT."""

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from lighthouse.application.ledger import LedgerError
from lighthouse.domain.workflow import Binding, Project

_HEX = re.compile(r"[0-9a-f]{64}")
_HEAD = re.compile(r"[0-9a-f]{40}")
_REF = re.compile(r"[A-Za-z0-9_-]{1,100}")


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Target:
    """Committed dispatch and exact accepted work binding."""

    repository: str
    order: str
    dispatch: str
    issue: int
    pr: int
    head: str
    binding: Binding

    def valid(self) -> bool:
        return bool(
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository)
            and len(self.repository) <= 201 and _REF.fullmatch(self.order) and _HEX.fullmatch(self.dispatch)
            and type(self.issue) is int and self.issue > 0
            and type(self.pr) is int and self.pr > 0 and _HEAD.fullmatch(self.head)
            and all(re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value) for value in (
                self.binding.scope, self.binding.profile, self.binding.verification,
            ))
        )


@dataclass(frozen=True)
class ReviewInput:
    """Transient input; instructions and context do not enter durable state."""

    target: Target
    instructions: str = field(repr=False)
    context: str = field(repr=False)

    def fingerprint(self) -> str:
        for item in (self.instructions, self.context):
            if not item.strip() or "\0" in item or len(item.encode()) > 262144:
                raise ValueError("invalid-review-input")
        return digest(asdict(self))


class StartupProgress(StrEnum):
    """Last positively witnessed startup checkpoint, never completion evidence."""

    NOT_STARTED = "not-started"
    CHECKOUT_VERIFIED = "checkout-verified"
    SESSION_OPENED = "session-opened"
    RUNTIME_VERIFIED = "runtime-verified"
    ACCOUNT_VERIFIED = "account-verified"
    THREAD_VERIFIED = "thread-verified"
    CHECKOUT_REVERIFIED = "checkout-reverified"


_STARTUP_REASONS = frozenset({
    "ack-invalid", "account-unverified", "checkout-unverified", "cleanup-deadline-elapsed",
    "cleanup-unconfirmed", "deadline-elapsed", "event-budget", "event-order-invalid", "frame-budget",
    "frame-invalid", "identity-mismatch", "output-invalid", "permission-attention", "policy-unverified",
    "provider-interrupted", "request-budget", "request-invalid", "response-mismatch", "runtime-unverified",
    "second-dispatch", "server-error", "terminal-conflict", "terminal-failed", "terminal-invalid",
    "thread-unverified", "transport-lost", "unexpected-review-item",
})


@dataclass(frozen=True)
class StartupDiagnostic:
    """Small durable operator evidence, isolated from stage and lifecycle."""

    reason: str
    progress: StartupProgress

    def valid(self) -> bool:
        return isinstance(self.reason, str) and self.reason in _STARTUP_REASONS and isinstance(
            self.progress, StartupProgress,
        )

    @classmethod
    def from_worker(cls, reason: object, progress: object) -> StartupDiagnostic | None:
        if not isinstance(reason, str) or not isinstance(progress, StartupProgress):
            return None
        result = cls(reason, progress)
        return result if result.valid() else None


class Stage(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    STARTING = "starting"
    ACCEPTED = "accepted"
    APPROVAL_REQUIRED = "approval-required"
    UNAVAILABLE = "unavailable"
    EXECUTION_UNKNOWN = "execution-unknown"
    CLEANUP_UNCONFIRMED = "cleanup-unconfirmed"
    UNKNOWN_AND_CLEANUP = "execution-unknown-and-cleanup-unconfirmed"
    COMPLETED = "completed"
    PUBLISHING = "publication-unknown"
    COMMENTED = "commented"
    STALE = "stale-head"
    HELD = "held"


class Remote(StrEnum):
    NOT_STARTED = "not-started"
    UNKNOWN = "completion-unconfirmed"
    COMPLETED = "completion-observed"


class Cleanup(StrEnum):
    NOT_NEEDED = "not-needed"
    UNCONFIRMED = "owned-cleanup-unconfirmed"
    CONFIRMED = "owned-cleanup-confirmed"


@dataclass(frozen=True)
class Lifecycle:
    """Independent remote, local and approval facts, with no provider text."""

    remote: Remote = Remote.NOT_STARTED
    cleanup: Cleanup = Cleanup.NOT_NEEDED
    approval: bool = False

    @property
    def causes(self) -> tuple[str, ...]:
        return (
            *(("approval-required",) if self.approval else ()),
            *((self.remote.value,) if self.remote is Remote.UNKNOWN else ()),
            *((self.cleanup.value,) if self.cleanup is Cleanup.UNCONFIRMED else ()),
        )


@dataclass(frozen=True)
class Attempt:
    """Durable safe status, references and digests, never review text or paths."""

    target: Target
    fingerprint: str
    stage: Stage = Stage.CLAIMED
    thread: str = ""
    turn: str = ""
    output: str = ""
    marker: str = ""
    review_id: int = 0
    lifecycle: Lifecycle = Lifecycle()
    event: str = "COMMENT"
    startup: StartupDiagnostic | None = None

    def valid(self) -> bool:
        identity = bool(_REF.fullmatch(self.thread) and _REF.fullmatch(self.turn))
        empty = not self.thread and not self.turn
        phase_identity = (
            empty if self.stage in {Stage.CLAIMED, Stage.STARTING} else
            identity or empty if self.stage in {
                Stage.EXECUTION_UNKNOWN, Stage.CLEANUP_UNCONFIRMED, Stage.UNKNOWN_AND_CLEANUP,
                Stage.APPROVAL_REQUIRED, Stage.UNAVAILABLE,
            } else identity
        )
        has_output = self.stage in {Stage.COMPLETED, Stage.PUBLISHING, Stage.COMMENTED, Stage.STALE}
        has_marker = self.stage in {Stage.PUBLISHING, Stage.COMMENTED}
        return bool(
            self.target.valid() and _HEX.fullmatch(self.fingerprint) and phase_identity
            and self.event in {"COMMENT", "APPROVE", "REQUEST_CHANGES"}
            and (has_output or self.event == "COMMENT")
            and (self.startup is None or (self.startup.valid() and self.stage in {
                Stage.UNAVAILABLE, Stage.EXECUTION_UNKNOWN, Stage.CLEANUP_UNCONFIRMED,
                Stage.UNKNOWN_AND_CLEANUP, Stage.APPROVAL_REQUIRED,
            }))
            and self.stage not in {Stage.PENDING, Stage.HELD}
            and (bool(_HEX.fullmatch(self.output)) if has_output else not self.output)
            and (bool(_HEX.fullmatch(self.marker)) if has_marker else not self.marker)
            and type(self.lifecycle.approval) is bool
            and (self.lifecycle.remote is not Remote.COMPLETED or identity)
            and (not has_output or self.lifecycle == Lifecycle(Remote.COMPLETED, Cleanup.CONFIRMED))
            and (self.stage is not Stage.APPROVAL_REQUIRED or self.lifecycle.approval)
            and type(self.review_id) is int
            and (self.review_id > 0 if self.stage is Stage.COMMENTED else self.review_id == 0)
        )


class Attempts(Protocol):
    def review_attempt(self, repository: str, dispatch: str) -> Attempt | None: ...
    def claim_review(self, attempt: Attempt) -> bool: ...
    def advance_review(self, expected: Attempt, updated: Attempt) -> bool: ...


@dataclass(frozen=True)
class Status:
    stage: Stage
    actor: int | None
    reason: str
    attempt: Attempt | None = None


@dataclass(frozen=True)
class Completion:
    fingerprint: str
    thread: str
    turn: str
    comment: str = field(repr=False)
    owned_cleanup: bool
    event: str = "COMMENT"


class Executor(Protocol):
    def start(self, request: ReviewInput, begin: Callable[[], bool],
              accept: Callable[[str, str], bool]) -> None: ...


class Comment(Protocol):
    def submit(self, target: Target, marker: str, text: str) -> int | None: ...
    def lookup(self, target: Target, marker: str, output: str) -> int | None: ...


class ReviewDispatch:
    """Claim an existing review intent once; never retry an unknown effect."""

    def __init__(
        self, project: Project, attempts: Attempts, executor: Executor, comment: Comment,
        current: Callable[[Target], bool], *,
        formal_submit: Callable[[Attempt, str], int | None] | None = None,
        formal_lookup: Callable[[Attempt], int | None] | None = None,
    ) -> None:
        self.project = project
        self._formal_submit, self._formal_lookup = formal_submit, formal_lookup
        self._attempts, self._executor, self._comment, self._current = attempts, executor, comment, current

    def _is_current(self, target: Target) -> bool:
        try:
            return self._current(target) is True
        except Exception:
            return False

    def status(self, dispatch: str) -> Status:
        attempt = self._attempts.review_attempt(self.project.repository, dispatch)
        if attempt is None:
            return Status(Stage.PENDING, self.project.lead, "not-admitted")
        stage = (Stage.EXECUTION_UNKNOWN if attempt.stage in {Stage.CLAIMED, Stage.STARTING}
                 else attempt.stage)
        actor = self.project.owner if stage in {
            Stage.EXECUTION_UNKNOWN, Stage.APPROVAL_REQUIRED, Stage.CLEANUP_UNCONFIRMED, Stage.UNKNOWN_AND_CLEANUP, Stage.PUBLISHING,
        } else self.project.lead
        return Status(stage, actor, ", ".join(attempt.lifecycle.causes) or stage.value, attempt)

    def start(self, request: ReviewInput) -> Status:
        target = request.target
        try:
            fingerprint = request.fingerprint()
        except (ValueError, UnicodeError):
            return Status(Stage.HELD, self.project.lead, "invalid-review-input")
        if (not target.valid() or target.repository != self.project.repository
                or target.binding.profile != self.project.profile):
            return Status(Stage.HELD, self.project.lead, "wrong-target")
        prior = self._attempts.review_attempt(target.repository, target.dispatch)
        if prior is not None:
            if prior.fingerprint != fingerprint:
                return Status(Stage.HELD, self.project.lead, "context-changed", prior)
            return self.status(target.dispatch)
        candidate = Attempt(target, fingerprint)
        if not self._is_current(target) or not self._attempts.claim_review(candidate):
            existing = self._attempts.review_attempt(target.repository, target.dispatch)
            if existing is not None and existing.fingerprint == fingerprint:
                return self.status(target.dispatch)
            return Status(Stage.HELD, self.project.lead, "admission-not-current-or-blocked", existing)

        starting = replace(candidate, stage=Stage.STARTING, lifecycle=Lifecycle(Remote.UNKNOWN, Cleanup.UNCONFIRMED))

        def begin() -> bool:
            return self._attempts.advance_review(candidate, starting)

        def accepted(thread: str, turn: str) -> bool:
            if not _REF.fullmatch(thread) or not _REF.fullmatch(turn):
                return False
            return self._attempts.advance_review(
                starting, replace(starting, stage=Stage.ACCEPTED, thread=thread, turn=turn),
            )

        try:
            self._executor.start(request, begin, accepted)
        except Exception:
            # Do not infer whether an effect occurred or retry after a failed submission.
            return self.status(target.dispatch)
        return self.status(target.dispatch)

    def hold(
        self, dispatch: str, fingerprint: str, stage: Stage, thread: str = "", turn: str = "", *,
        lifecycle: Lifecycle | None = None,
        startup: StartupDiagnostic | None = None,
    ) -> Status:
        prior = self._attempts.review_attempt(self.project.repository, dispatch)
        if (prior is not None and prior.fingerprint == fingerprint
                and (prior.thread, prior.turn) == (thread, turn)
                and prior.stage in {Stage.CLAIMED, Stage.STARTING, Stage.ACCEPTED}
                and stage in {Stage.EXECUTION_UNKNOWN, Stage.CLEANUP_UNCONFIRMED,
                              Stage.APPROVAL_REQUIRED, Stage.UNAVAILABLE, Stage.UNKNOWN_AND_CLEANUP}):
            self._attempts.advance_review(prior, replace(
                prior, stage=stage, lifecycle=lifecycle or prior.lifecycle, startup=startup,
            ))
        return self.status(dispatch)

    def complete(self, dispatch: str, result: Completion) -> Status:
        prior = self._attempts.review_attempt(self.project.repository, dispatch)
        if (prior is None or prior.stage not in {Stage.ACCEPTED, Stage.CLEANUP_UNCONFIRMED}
                or not prior.thread or (prior.fingerprint, prior.thread, prior.turn)
                != (result.fingerprint, result.thread, result.turn)):
            return self.status(dispatch)
        if result.owned_cleanup is not True:
            return self.hold(dispatch, result.fingerprint, Stage.CLEANUP_UNCONFIRMED, result.thread, result.turn,
                             lifecycle=Lifecycle(Remote.COMPLETED, Cleanup.UNCONFIRMED))
        if (result.event not in {"COMMENT", "APPROVE", "REQUEST_CHANGES"} or not result.comment.strip() or len(result.comment.encode("utf-8", errors="replace")) > 16384
                or any(ord(char) < 32 and char not in "\r\n\t" for char in result.comment)):
            return self.hold(dispatch, result.fingerprint, Stage.EXECUTION_UNKNOWN, result.thread, result.turn,
                             lifecycle=Lifecycle(Remote.COMPLETED, Cleanup.CONFIRMED))
        self._attempts.advance_review(prior, replace(
            prior, stage=Stage.COMPLETED, output=digest(result.comment), event=result.event,
            lifecycle=Lifecycle(Remote.COMPLETED, Cleanup.CONFIRMED), startup=None,
        ))
        return self.status(dispatch)

    def publish(self, dispatch: str, text: str = "") -> Status:
        """Publish validated transient text once; ambiguous attempts permit lookup only."""
        old = self._attempts.review_attempt(self.project.repository, dispatch)
        if old is None or old.stage not in {Stage.COMPLETED, Stage.PUBLISHING}:
            return self.status(dispatch)
        if old.stage is Stage.COMPLETED:
            if len(text) > 16384 or digest(text) != old.output:
                return Status(Stage.HELD, self.project.lead, "completion-output-not-attributed", old)
            if not self._is_current(old.target):
                self._attempts.advance_review(old, replace(old, stage=Stage.STALE))
                return self.status(dispatch)
            pending = replace(old, stage=Stage.PUBLISHING, marker=digest((old.fingerprint, old.event, old.output)))
            if not self._attempts.advance_review(old, pending):
                return self.status(dispatch)
            try:
                if pending.event == "COMMENT":
                    review_id = self._comment.submit(pending.target, pending.marker, text)
                else:
                    review_id = self._formal_submit(pending, text) if self._formal_submit else None
            except Exception:
                review_id = None
        else:
            pending = old
            try:
                if pending.event == "COMMENT":
                    review_id = self._comment.lookup(pending.target, pending.marker, pending.output)
                else:
                    review_id = self._formal_lookup(pending) if self._formal_lookup else None
            except Exception:
                review_id = None
        if type(review_id) is int and review_id > 0:
            try:
                self._attempts.advance_review(pending, replace(pending, stage=Stage.COMMENTED, review_id=review_id))
            except LedgerError:
                # The earlier marker remains the only lookup key; never repeat a POST.
                return Status(Stage.PUBLISHING, self.project.owner, "publication-receipt-not-retained", pending)
        return self.status(dispatch)
