"""Pure workflow decisions over attributed, normalized observations."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum, IntEnum


class Priority(IntEnum):
    HIGH = 0
    NORMAL = 1
    LOW = 2


class Execution(Enum):
    QUIESCENT = "quiescent"
    ACTIVE = "active"
    UNKNOWN = "unknown"


class Outcome(Enum):
    IDLE = "idle"
    UNCHANGED = "unchanged"
    IMPLEMENT = "implement"
    IMPLEMENTING = "implementing"
    REVIEW = "review"
    REVIEWING = "reviewing"
    REVISE = "revise"
    AWAIT_OWNER = "await-owner"
    COMPLETE = "complete"
    HOLD = "hold"


class Verdict(Enum):
    APPROVED = "approved"
    CHANGES = "changes-requested"
    OTHER = "other"


@dataclass(frozen=True)
class Project:
    """Current normalized profile and independent authorities."""

    repository: str
    base: str
    profile: str
    owner: int
    lead: int
    implementer: int


@dataclass(frozen=True)
class Binding:
    """Exact intake snapshot identifiers, supplied by the caller."""

    scope: str
    profile: str
    verification: str


@dataclass(frozen=True)
class Ready:
    actor: int
    evidence: str
    binding: Binding
    priorities: tuple[Priority, ...]


@dataclass(frozen=True)
class Candidate:
    repository: str
    number: int
    created_at: datetime
    binding: Binding
    is_open: bool
    blocked: bool
    dependencies_complete: bool
    priorities: tuple[Priority, ...] = ()
    ready: Ready | None = None


@dataclass(frozen=True)
class Work:
    """Accepted identity and the single PR, once independently linked."""

    issue: int
    order: str
    binding: Binding
    pr: int | None = None


@dataclass(frozen=True)
class Pull:
    repository: str
    base: str
    author: int
    issue: int
    order: str
    number: int
    head: str
    is_open: bool = True
    draft: bool = False


@dataclass(frozen=True)
class Review:
    """Effective review observation, not a text assertion of approval."""

    actor: int
    pr: int
    head: str
    evidence: str
    verdict: Verdict
    submitted: datetime
    effective: bool = True


@dataclass(frozen=True)
class Verification:
    pr: int
    head: str
    contract: str
    evidence: str
    confirmed: datetime


@dataclass(frozen=True)
class Merge:
    """Confirmed provider merge observation, never a test-merge prediction."""

    actor: int
    pr: int
    reviewed_head: str
    result_sha: str
    occurred: datetime
    evidence: str


@dataclass(frozen=True)
class Snapshot:
    """A project-wide, monotonically versioned normalized observation."""

    repository: str
    version: int
    now: datetime
    candidates: tuple[Candidate, ...] = ()
    order: str = ""
    implementation: Execution = Execution.UNKNOWN
    reviewing: Execution = Execution.UNKNOWN
    reviewing_head: str | None = None
    pull: Pull | None = None
    review: Review | None = None
    verification: Verification | None = None
    merge: Merge | None = None


@dataclass(frozen=True)
class State:
    repository: str
    version: int = -1
    work: Work | None = None
    outcome: Outcome = Outcome.IDLE
    action_keys: frozenset[tuple[Outcome, str, int, str]] = frozenset()


@dataclass(frozen=True)
class Decision:
    """Recommendation and next state; callers own persistence and effects."""

    state: State
    outcome: Outcome
    reason: str
    actor: int | None = None
    evidence: tuple[str, ...] = ()


def _eligible(project: Project, item: Candidate, now: datetime) -> bool:
    ready = item.ready
    return (
        item.repository == project.repository
        and item.number > 0
        and item.created_at <= now
        and item.is_open and not item.blocked and item.dependencies_complete
        and len(item.priorities) <= 1
        and bool(item.binding.scope and item.binding.verification and project.profile)
        and item.binding.profile == project.profile
        and ready is not None and bool(ready.evidence)
        and ready.actor in (project.owner, project.lead)
        and ready.binding == item.binding and ready.priorities == item.priorities
    )


class Workflow:
    """Evaluate a single project's decision without consulting external state."""

    def __init__(self, project: Project) -> None:
        self.project = project

    def evaluate(self, state: State, facts: Snapshot) -> Decision:
        """Return a disposition; old or duplicate versions never repeat work."""
        project = self.project
        if state.repository != project.repository or facts.repository != project.repository:
            return Decision(state, Outcome.HOLD, "wrong-project", project.owner)
        actors = (project.owner, project.lead, project.implementer)
        if len(set(actors)) != 3 or any(type(actor) is not int or actor <= 0 for actor in actors):
            return Decision(state, Outcome.HOLD, "invalid-actor-bindings")
        if facts.version <= state.version:
            return Decision(state, Outcome.UNCHANGED, "old-observation")
        state = replace(state, version=facts.version)
        work = state.work
        if Execution.UNKNOWN in (facts.implementation, facts.reviewing):
            return self._decision(state, Outcome.HOLD, "unknown-acceptance", project.owner)
        if work is None:
            return self._admit(state, facts)
        candidates = [i for i in facts.candidates if i.number == work.issue
                      and i.repository == project.repository]
        if len(candidates) != 1 or candidates[0].binding != work.binding or (
            work.binding.profile != project.profile
        ):
            return self._decision(state, Outcome.HOLD, "scope-not-current", project.lead)
        if not candidates[0].is_open and facts.merge is None:
            return self._decision(state, Outcome.HOLD, "issue-closed", project.owner)
        pull = facts.pull
        if pull is None:
            if work.pr is not None or facts.merge is not None:
                return self._decision(state, Outcome.HOLD, "missing-pull", project.owner)
            if facts.implementation is Execution.ACTIVE:
                return self._decision(state, Outcome.IMPLEMENTING, "implementation-active")
            return self._decision(state, Outcome.HOLD, "no-attributed-implementation", project.owner)
        if (pull.repository, pull.base, pull.author, pull.issue, pull.order) != (
            project.repository, project.base, project.implementer, work.issue, work.order
        ) or (work.pr is not None and work.pr != pull.number) or not pull.head or pull.number <= 0:
            return self._decision(state, Outcome.HOLD, "unbound-pull", project.owner)
        state = replace(state, work=replace(work, pr=pull.number))
        return self._inspect_pull(state, facts, pull, work)

    def _admit(self, state: State, facts: Snapshot) -> Decision:
        project = self.project
        if (facts.implementation is Execution.ACTIVE or facts.reviewing is Execution.ACTIVE
                or facts.pull is not None or facts.merge is not None):
            return self._decision(state, Outcome.HOLD, "occupied-slot", project.owner)
        numbers = [i.number for i in facts.candidates if i.repository == project.repository]
        if len(set(numbers)) != len(numbers):
            return self._decision(state, Outcome.HOLD, "ambiguous-candidates", project.owner)
        eligible = [i for i in facts.candidates if _eligible(project, i, facts.now)]
        if not eligible:
            return self._decision(state, Outcome.IDLE, "no-eligible-issue")
        if not facts.order:
            return self._decision(state, Outcome.HOLD, "missing-order-id", project.owner)
        chosen = min(eligible, key=lambda i: (
            i.priorities[0] if i.priorities else Priority.NORMAL, i.created_at, i.number
        ))
        assert chosen.ready is not None
        return self._decision(
            replace(state, work=Work(chosen.number, facts.order, chosen.binding)),
            Outcome.IMPLEMENT, "eligible-issue", project.implementer, (chosen.ready.evidence,),
        )

    def _inspect_pull(self, state: State, facts: Snapshot, pull: Pull, work: Work) -> Decision:
        p = self.project
        review = facts.review
        if review is not None and (
            not review.effective or not review.evidence
            or (review.actor, review.pr, review.head) != (p.lead, pull.number, pull.head)
            or review.submitted > facts.now
        ):
            review = None
        check = facts.verification
        if check is not None and (
            not check.evidence or (check.pr, check.head, check.contract)
            != (pull.number, pull.head, work.binding.verification) or check.confirmed > facts.now
        ):
            check = None
        merge = facts.merge
        quiet = facts.implementation is facts.reviewing is Execution.QUIESCENT
        if merge is not None:
            if (not pull.is_open and not pull.draft and quiet and review is not None
                    and review.verdict is Verdict.APPROVED and check is not None
                    and (merge.actor, merge.pr, merge.reviewed_head) == (
                        p.owner, pull.number, pull.head)
                    and merge.result_sha and merge.evidence and merge.occurred <= facts.now
                    and review.submitted < merge.occurred and check.confirmed < merge.occurred):
                return self._decision(
                    replace(state, work=None, action_keys=frozenset()), Outcome.COMPLETE, "owner-merge-confirmed",
                    evidence=(pull.head, merge.result_sha, review.evidence,
                              check.evidence, merge.evidence),
                )
            return self._decision(state, Outcome.HOLD, "merge-not-proven", p.owner)
        if not pull.is_open:
            return self._decision(state, Outcome.HOLD, "closed-unmerged", p.owner)
        if facts.reviewing is Execution.ACTIVE:
            if facts.reviewing_head != pull.head:
                return self._decision(state, Outcome.HOLD, "older-review-unresolved", p.lead)
            return self._decision(state, Outcome.REVIEWING, "current-review-active", p.lead)
        if not quiet or pull.draft:
            return self._decision(state, Outcome.IMPLEMENTING, "implementation-or-draft")
        if review is not None and review.verdict is Verdict.CHANGES:
            return self._next_once(
                state, pull, Outcome.REVISE, "lead-requests-changes", p.implementer, review.evidence
            )
        if review is not None and review.verdict is Verdict.APPROVED:
            if check is None:
                return self._decision(state, Outcome.HOLD, "missing-verification", p.implementer)
            return self._next_once(
                state, pull, Outcome.AWAIT_OWNER, "approved-and-verified", p.owner,
                review.evidence, check.evidence,
            )
        return self._next_once(state, pull, Outcome.REVIEW, "review-required", p.lead, pull.head)

    @staticmethod
    def _decision(
        state: State, outcome: Outcome, reason: str, actor: int | None = None,
        evidence: tuple[str, ...] = (),
    ) -> Decision:
        return Decision(replace(state, outcome=outcome), outcome, reason, actor, evidence)

    @staticmethod
    def _next_once(
        state: State, pull: Pull, outcome: Outcome, reason: str, actor: int, *evidence: str,
    ) -> Decision:
        key = (outcome, pull.head, pull.number, evidence[0])
        if key in state.action_keys:
            return Decision(replace(state, outcome=outcome), Outcome.UNCHANGED,
                            "already-recommended", evidence=evidence)
        return Workflow._decision(replace(state, action_keys=state.action_keys | {key}), outcome, reason, actor, evidence)
