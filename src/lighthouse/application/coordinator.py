"""One offline reconciliation cycle. Decisions never execute their intents."""

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Protocol

from lighthouse.application.ledger import (
    Change,
    Intent,
    Ledger,
    LedgerError,
    WriteResult,
)
from lighthouse.domain.workflow import (
    Candidate,
    Decision,
    Execution,
    Merge,
    Outcome,
    Pull,
    Review,
    Snapshot,
    State,
    Verification,
    Workflow,
)


@dataclass(frozen=True)
class Bundle:
    """Normalized observation evidence from the outer adapter, not an execution receipt."""

    candidates: tuple[Candidate, ...] = ()
    pull: Pull | None = None
    review: Review | None = None
    merge: Merge | None = None
    held: bool = False


@dataclass(frozen=True)
class Cycle:
    """Externally supplied identity, version, clock and independent receipts."""

    revision: str
    version: int
    now: datetime
    new_order: str = ""
    implementation: Execution = Execution.UNKNOWN
    reviewing: Execution = Execution.UNKNOWN
    reviewing_head: str | None = None
    verification: Verification | None = None


class ObservationSource(Protocol):
    def observe(self, accepted: State, cycle: Cycle) -> Bundle: ...


@dataclass(frozen=True)
class Status:
    revision: str
    version: int
    phase: Outcome
    reason: str
    actor: int | None
    order: str | None
    pr: int | None
    head: str | None
    intents: tuple[Intent, ...]
    write: WriteResult | None = None


def _identity(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError("invalid-normalized-evidence")


def _fingerprint(value: object) -> str:
    return sha256(json.dumps(value, default=_identity, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


class Coordinator:
    """Combine one normalized observation with durable state and explicit receipts."""

    def __init__(self, workflow: Workflow, ledger: Ledger, source: ObservationSource) -> None:
        self._workflow, self._ledger, self._source = workflow, ledger, source

    def reconcile(self, cycle: Cycle) -> Status:
        """Read before writing, then compare-and-commit one atomic result."""
        project = self._workflow.project
        state = self._ledger.state(project.repository)
        if (not cycle.revision or type(cycle.version) is not int or cycle.version < 0
                or cycle.now.utcoffset() is None):
            return self._status(cycle, state, "invalid-cycle", project.owner)
        audit = self._ledger.audit(project.repository)
        existing = next((change for change in audit if change.observation == cycle.revision), None)
        prior = state
        if existing is not None:
            prior = next((change.decision.state for change in audit
                          if change.decision.state.version == existing.expected), State(project.repository))
        observed = self._source.observe(prior, cycle)
        marker = "source-sha256:" + _fingerprint((asdict(cycle), asdict(observed)))
        if existing is not None:
            matched = existing.decision.evidence[-1:] == (marker,)
            # The audit can see a commit made after the initial state read.
            state = self._ledger.state(project.repository)
            return self._status(cycle, state, "duplicate-observation" if matched
                                else "conflicting-observation", None if matched else project.owner,
                                write=WriteResult.DUPLICATE if matched else WriteResult.CONFLICT)
        if observed.held:
            return self._status(cycle, state, "observation-held", project.owner)
        if cycle.version <= state.version:
            return self._status(cycle, state, "stale-version", project.owner, write=WriteResult.STALE)
        snapshot = Snapshot(
            project.repository, cycle.version, cycle.now, observed.candidates, cycle.new_order,
            cycle.implementation, cycle.reviewing, cycle.reviewing_head, observed.pull,
            observed.review, cycle.verification, observed.merge,
        )
        decision = self._workflow.evaluate(state, snapshot)
        if decision.state.version != cycle.version:
            return self._status(cycle, state, decision.reason, decision.actor)
        intent = self._intent(cycle, decision, observed.pull)
        evidence = replace(decision, evidence=(*decision.evidence, marker))
        try:
            result = self._ledger.record(Change(state.version, cycle.revision, evidence, intent))
        except LedgerError:
            return self._status(cycle, state, "ledger-write-failed", project.owner)
        if result is not WriteResult.COMMITTED:
            return self._status(cycle, self._ledger.state(project.repository),
                                "write-" + result.value, project.owner, write=result)
        reported = observed.pull if observed.pull and (
            decision.outcome is Outcome.COMPLETE or
            (decision.state.work is not None and decision.state.work.pr == observed.pull.number
             and decision.reason != "unbound-pull")
        ) else None
        return self._status(cycle, decision.state, decision.reason, decision.actor, reported, result,
                            order=state.work.order if state.work else None)

    @staticmethod
    def _intent(cycle: Cycle, decision: Decision, pull: Pull | None) -> Intent | None:
        if decision.outcome not in (Outcome.IMPLEMENT, Outcome.REVIEW, Outcome.REVISE):
            return None
        work = decision.state.work
        assert work is not None
        dispatch = _fingerprint((decision.state.repository, work.order, cycle.revision,
                                 decision.outcome.value))
        head = pull.head if work.pr is not None and pull is not None else None
        return Intent(dispatch, work.order, decision.outcome.value, work.pr, head)

    def _status(
        self, cycle: Cycle, state: State, reason: str, actor: int | None,
        pull: Pull | None = None, write: WriteResult | None = None, *, order: str | None = None,
    ) -> Status:
        work = state.work
        correlation = work.order if work else order
        intents = tuple(intent for intent in self._ledger.intents(state.repository)
                        if intent.order == correlation)
        return Status(cycle.revision, state.version, state.outcome, reason, actor,
                      correlation, work.pr if work else pull.number if pull else None,
                      pull.head if pull else None, intents, write)
