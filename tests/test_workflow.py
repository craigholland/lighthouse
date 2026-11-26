"""Exercise the pure workflow entry point with synthetic facts only."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from lighthouse.domain.workflow import (
    Binding,
    Candidate,
    Execution,
    Merge,
    Outcome,
    Priority,
    Project,
    Pull,
    Ready,
    Review,
    Snapshot,
    State,
    Verdict,
    Verification,
    Workflow,
)

NOW = datetime(2026, 1, 2, tzinfo=UTC)
PAST = NOW - timedelta(hours=1)
EARLIER = PAST - timedelta(hours=1)
PROJECT = Project("sample/one", "development", "profile", 1, 2, 3)
ENGINE = Workflow(PROJECT)
BINDING = Binding("scope", "profile", "contract")
ISSUE = Candidate(PROJECT.repository, 7, EARLIER, BINDING, True, False, True,
                  ready=Ready(2, "ready", BINDING, ()))
FACTS = Snapshot(PROJECT.repository, 1, NOW, (ISSUE,), "order",
                 implementation=Execution.QUIESCENT, reviewing=Execution.QUIESCENT)
PULL = Pull(PROJECT.repository, PROJECT.base, 3, 7, "order", 8, "head-a")
APPROVAL = Review(2, 8, "head-a", "approval", Verdict.APPROVED, EARLIER)
CHECK = Verification(8, "head-a", "contract", "check", EARLIER)
MERGE = Merge(1, 8, "head-a", "merge-sha", PAST, "merge-record")


def admit() -> State:
    result = ENGINE.evaluate(State(PROJECT.repository), FACTS)
    assert (result.outcome, result.actor, result.evidence) == (Outcome.IMPLEMENT, 3, ("ready",))
    return result.state


def test_lifecycle_revision_then_actual_owner_merge() -> None:
    state = admit()
    running = ENGINE.evaluate(state, replace(FACTS, version=2, implementation=Execution.ACTIVE))
    assert running.outcome is Outcome.IMPLEMENTING
    facts = replace(FACTS, version=3, pull=PULL)
    reviewed = ENGINE.evaluate(running.state, facts)
    assert (reviewed.outcome, reviewed.actor) == (Outcome.REVIEW, 2)
    assert ENGINE.evaluate(reviewed.state, facts).outcome is Outcome.UNCHANGED
    assert ENGINE.evaluate(reviewed.state, replace(facts, version=2)).state == reviewed.state
    assert ENGINE.evaluate(reviewed.state, replace(facts, version=4)).outcome is Outcome.UNCHANGED
    requested = replace(APPROVAL, verdict=Verdict.CHANGES)
    revision = ENGINE.evaluate(reviewed.state, replace(facts, version=5, review=requested))
    assert revision.outcome is Outcome.REVISE and revision.actor == 3
    new_pull = replace(PULL, head="head-b")
    new = replace(facts, version=6, pull=new_pull, review=requested)
    superseded = ENGINE.evaluate(
        revision.state, replace(new, reviewing=Execution.ACTIVE, reviewing_head=PULL.head)
    )
    assert superseded.outcome is Outcome.HOLD
    rereview = ENGINE.evaluate(superseded.state, replace(new, version=7))
    assert rereview.outcome is Outcome.REVIEW
    approved = replace(new, version=8, review=replace(APPROVAL, head=new_pull.head),
                       verification=replace(CHECK, head=new_pull.head))
    waiting = ENGINE.evaluate(rereview.state, approved)
    assert waiting.outcome is Outcome.AWAIT_OWNER and waiting.actor == 1
    assert waiting.state.work is not None
    done = ENGINE.evaluate(waiting.state, replace(
        approved, version=9, pull=replace(new_pull, is_open=False),
        merge=replace(MERGE, reviewed_head=new_pull.head),
    ))
    assert done.outcome is Outcome.COMPLETE and done.state.work is None
    assert done.evidence == ("head-b", "merge-sha", "approval", "check", "merge-record")
    assert ENGINE.evaluate(done.state, approved).outcome is Outcome.UNCHANGED


@pytest.mark.parametrize("item", [
    replace(ISSUE, is_open=False), replace(ISSUE, blocked=True),
    replace(ISSUE, dependencies_complete=False), replace(ISSUE, ready=None),
    replace(ISSUE, ready=Ready(3, "ready", BINDING, ())),
    replace(ISSUE, ready=Ready(2, "ready", replace(BINDING, scope="old"), ())),
    replace(ISSUE, binding=replace(BINDING, verification="")),
    replace(ISSUE, priorities=(Priority.HIGH, Priority.LOW)),
    replace(ISSUE, priorities=(Priority.LOW,)),
])
def test_admission_rejects_invalid_candidates(item: Candidate) -> None:
    facts = replace(FACTS, candidates=(item,))
    assert ENGINE.evaluate(State(PROJECT.repository), facts).outcome is Outcome.IDLE


def test_priority_defaults_ties_and_project_isolation() -> None:
    high = replace(ISSUE, number=11, priorities=(Priority.HIGH,),
                   ready=Ready(1, "owner-ready", BINDING, (Priority.HIGH,)))
    tie = replace(ISSUE, number=6)
    later = replace(ISSUE, number=2, created_at=PAST)
    other = replace(high, repository="sample/two")
    initial = State(PROJECT.repository)
    result = ENGINE.evaluate(initial, replace(FACTS, candidates=(ISSUE, other, tie, later, high)))
    assert result.state.work is not None and result.state.work.issue == 11
    result = ENGINE.evaluate(initial, replace(FACTS, candidates=(ISSUE, other, tie, later)))
    assert result.state.work is not None and result.state.work.issue == 6
    assert ENGINE.evaluate(State(other.repository), FACTS).reason == "wrong-project"
    assert initial.work is None


@pytest.mark.parametrize("execution", [Execution.ACTIVE, Execution.UNKNOWN])
def test_occupied_or_uncertain_slot_is_never_admitted(execution: Execution) -> None:
    initial = State(PROJECT.repository)
    facts = replace(FACTS, now=NOW + timedelta(days=30), implementation=execution)
    assert ENGINE.evaluate(initial, facts).outcome is Outcome.HOLD
    assert ENGINE.evaluate(admit(), replace(facts, version=2)).state.work is not None


@pytest.mark.parametrize("pull", [
    replace(PULL, repository="sample/two"), replace(PULL, base="main"),
    replace(PULL, author=2), replace(PULL, issue=9), replace(PULL, order="other"),
    replace(PULL, is_open=False),
])
def test_unrelated_or_closed_pr_holds(pull: Pull) -> None:
    result = ENGINE.evaluate(admit(), replace(FACTS, version=2, pull=pull))
    assert result.outcome is Outcome.HOLD and result.state.work is not None


def test_same_pr_binding_and_changed_scope_hold() -> None:
    facts = replace(FACTS, version=2, pull=PULL)
    linked = ENGINE.evaluate(admit(), facts).state
    assert ENGINE.evaluate(linked, replace(facts, version=3, pull=replace(PULL, number=9))
                           ).reason == "unbound-pull"
    changed = replace(ISSUE, binding=replace(BINDING, scope="new"))
    assert ENGINE.evaluate(linked, replace(facts, version=3, candidates=(changed,))
                           ).reason == "scope-not-current"


@pytest.mark.parametrize("review", [
    replace(APPROVAL, actor=1), replace(APPROVAL, head="obsolete"),
    replace(APPROVAL, pr=9), replace(APPROVAL, effective=False),
    replace(APPROVAL, verdict=Verdict.OTHER), replace(APPROVAL, submitted=NOW + timedelta(hours=1)),
])
def test_review_must_be_effective_lead_approval_for_exact_head(review: Review) -> None:
    result = ENGINE.evaluate(admit(), replace(FACTS, version=2, pull=PULL,
                                              review=review, verification=CHECK))
    assert result.outcome is Outcome.REVIEW


def test_required_verification_and_draft_gate() -> None:
    facts = replace(FACTS, version=2, pull=PULL, review=APPROVAL)
    result = ENGINE.evaluate(admit(), replace(facts, verification=replace(CHECK, contract="other")))
    assert result.reason == "missing-verification"
    assert ENGINE.evaluate(admit(), replace(facts, pull=replace(PULL, draft=True))
                           ).outcome is Outcome.IMPLEMENTING


@pytest.mark.parametrize(("merge", "review", "check", "execution"), [
    (None, APPROVAL, CHECK, Execution.QUIESCENT),
    (replace(MERGE, actor=2), APPROVAL, CHECK, Execution.QUIESCENT),
    (replace(MERGE, reviewed_head="other"), APPROVAL, CHECK, Execution.QUIESCENT),
    (MERGE, replace(APPROVAL, submitted=NOW), CHECK, Execution.QUIESCENT),
    (MERGE, APPROVAL, replace(CHECK, confirmed=NOW), Execution.QUIESCENT),
    (MERGE, APPROVAL, CHECK, Execution.ACTIVE),
    (MERGE, APPROVAL, CHECK, Execution.UNKNOWN),
])
def test_merge_cannot_complete_without_exact_prior_evidence_and_quiescence(
    merge: Merge | None, review: Review, check: Verification, execution: Execution,
) -> None:
    result = ENGINE.evaluate(admit(), replace(
        FACTS, version=2, pull=replace(PULL, is_open=False), merge=merge,
        review=review, verification=check, implementation=execution,
    ))
    assert result.outcome is Outcome.HOLD and result.state.work is not None

def test_missing_execution_facts_and_nonindependent_actors_hold() -> None:
    state = State(PROJECT.repository)
    assert ENGINE.evaluate(state, Snapshot(PROJECT.repository, 1, NOW)).reason == (
        "unknown-acceptance"
    )
    invalid = Workflow(replace(PROJECT, lead=PROJECT.implementer))
    assert invalid.evaluate(state, FACTS).reason == "invalid-actor-bindings"



def test_deduped_recommendations_reconcile_phase_from_current_evidence() -> None:
    facts = replace(FACTS, version=2, pull=PULL)
    reviewing = ENGINE.evaluate(admit(), facts)
    approved = replace(facts, version=3, review=APPROVAL, verification=CHECK)
    waiting = ENGINE.evaluate(reviewing.state, approved)
    assert waiting.outcome is Outcome.AWAIT_OWNER

    dismissed = ENGINE.evaluate(
        waiting.state, replace(approved, version=4, review=replace(APPROVAL, effective=False))
    )
    missing = ENGINE.evaluate(waiting.state, replace(approved, version=4, verification=None))
    assert missing.outcome is Outcome.HOLD
    restored = ENGINE.evaluate(missing.state, replace(
        approved, version=5, verification=replace(CHECK, evidence="fresh-check"),
    ))
    assert dismissed.outcome is restored.outcome is Outcome.UNCHANGED
    assert dismissed.actor is restored.actor is None
    assert (dismissed.state.outcome, restored.state.outcome) == (
        Outcome.REVIEW, Outcome.AWAIT_OWNER,
    )
    assert dismissed.state.action_keys == restored.state.action_keys == waiting.state.action_keys
