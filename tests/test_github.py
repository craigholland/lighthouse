"""Synthetic REST 2022-11-28 response fixtures through the mapper entry point."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from lighthouse.adapters.github.facts import (
    API_VERSION,
    Context,
    GitHubFacts,
    ReadinessBinding,
    Resources,
    scope_fingerprint,
)
from lighthouse.configuration import Labels
from lighthouse.domain.workflow import (
    Binding,
    Execution,
    Outcome,
    Project,
    Snapshot,
    State,
    Verdict,
    Verification,
    Work,
    Workflow,
)

REPO = "example/project"
PROJECT = Project(REPO, "development", "profile", 11, 12, 13)
LABELS = Labels()
BODY = """## Objective
Sample objective.
## Sources
Sample source.
## In scope
Synthetic only.
## Out of scope
Live effects.
## Expected surfaces
Test files.
## Acceptance criteria
Pass sample checks.
## Dependencies
None.
## Verification
Sample checks.
## Stop conditions
Missing evidence.
## Handoff
Independent review."""
TITLE = "Sample task"
BINDING = Binding(scope_fingerprint(TITLE, BODY, ()), PROJECT.profile, "checks")
CONTEXT = Context(PROJECT, LABELS, "checks", True, readiness=ReadinessBinding(4, 100, BINDING))
HEAD, RESULT = "a" * 40, "b" * 40
TIME = datetime(2026, 11, 24, tzinfo=UTC)
PRE = "2026-11-23T10:00:00Z"
LATER = "2026-11-23T11:00:00Z"


def resources() -> Resources:
    return Resources(
        REPO, 4, "scan-7", API_VERSION, True,
        {"id": 40, "number": 4, "repository_url": "https://api.github.com/repos/" + REPO,
         "title": TITLE, "body": BODY, "created_at": "2026-11-22T09:00:00Z", "updated_at": LATER,
         "state": "open", "labels": [{"id": 2, "name": LABELS.ready}]},
        [{"id": 100, "event": "labeled", "created_at": PRE,
          "label": {"name": LABELS.ready}, "actor": {"id": 12, "type": "Bot"},
          "performed_via_github_app": None}],
    )


def pull(
    *, merged: bool = False, **extra: Any,
) -> dict[str, Any]:
    return {
        "id": 80, "number": 8, "user": {"id": 13, "login": "sample[bot]"},
        "base": {"repo": {"full_name": REPO}, "ref": "development"},
        "head": {"sha": HEAD}, "draft": False,
        "body": f"Evidence\n\nLighthouse-Issue: {REPO}#4\nLighthouse-Work-Order: order",
        "state": "closed" if merged else "open", "merged": merged,
        "merged_at": LATER if merged else None, "merge_commit_sha": RESULT,
        "merged_by": {"id": 11} if merged else None,
        **extra,
    }


def review(**extra: Any) -> dict[str, Any]:
    return {"id": 90, "user": {"id": 12}, "state": "APPROVED", "commit_id": HEAD,
            "submitted_at": PRE, **extra}


def test_realistic_observations_feed_domain_but_do_not_assert_other_authorities() -> None:
    observed = GitHubFacts(CONTEXT).normalize(resources())
    assert observed.hold is None and observed.revision == "scan-7"
    assert observed.candidate is not None and observed.candidate.ready is not None
    engine = Workflow(PROJECT)
    facts = Snapshot(REPO, 1, TIME, (observed.candidate,), "order",
                     implementation=Execution.QUIESCENT, reviewing=Execution.QUIESCENT)
    accepted = engine.evaluate(State(REPO), facts)
    assert accepted.outcome is Outcome.IMPLEMENT
    mapper = GitHubFacts(replace(CONTEXT, work=accepted.state.work))
    active = mapper.normalize(replace(resources(), pull=pull(), reviews=[review()]))
    assert active.hold is None and active.pull and active.review and active.merge is None
    approved = replace(facts, version=2, pull=active.pull, review=active.review)
    assert engine.evaluate(accepted.state, approved).reason == "missing-verification"
    merged = mapper.normalize(replace(resources(), pull=pull(merged=True), reviews=[review()]))
    assert merged.hold is None and merged.merge is not None
    assert (merged.merge.reviewed_head, merged.merge.result_sha) == (HEAD, RESULT)
    before_merge = datetime.fromisoformat(PRE)
    final = replace(approved, pull=merged.pull, merge=merged.merge,
                    verification=Verification(8, HEAD, "checks", "test-receipt", before_merge))
    assert engine.evaluate(accepted.state, replace(
        final, implementation=Execution.UNKNOWN,
    )).state.work == accepted.state.work
    assert engine.evaluate(accepted.state, final).outcome is Outcome.COMPLETE


@pytest.mark.parametrize("mutation", [
    {"complete": False}, {"failed": True}, {"repository": "other/project"},
    {"version": "unverified"}, {"events": None}, {"revision": ""}, {"issue_number": True},
])
def test_bundle_fails_closed(mutation: dict[str, Any]) -> None:
    result = GitHubFacts(CONTEXT).normalize(replace(resources(), **mutation))
    assert result.hold and result.candidate is result.pull is result.merge is None


@pytest.mark.parametrize("change", [
    {"actor": {"id": 13, "login": "correct-looking"}}, {"event": "unlabeled"},
    {"id": 101},
])
def test_active_label_cannot_reuse_inapplicable_event(change: dict[str, Any]) -> None:
    base = resources()
    assert isinstance(base.events, list)
    result = GitHubFacts(CONTEXT).normalize(replace(base, events=[{**base.events[0], **change}]))
    assert result.hold and result.candidate and result.candidate.ready is None


def test_changed_scope_removed_label_and_bad_task_fields() -> None:
    source = resources()
    assert isinstance(source.issue, dict)
    mapper = GitHubFacts(CONTEXT)
    for fields in (
        {"body": BODY + "\nChanged wording"},
        {"labels": []},
        {"body": "## Objective\nMissing sections"},
        {"repository_url": "https://api.github.com/repos/other/project"},
        {"labels": [{"id": 1, "name": LABELS.high}, {"id": 2, "name": LABELS.low}]},
    ):
        observed = mapper.normalize(replace(source, issue={**source.issue, **fields}))
        assert observed.candidate is None or observed.candidate.ready is None


@pytest.mark.parametrize("fields", [
    {"user": {"id": 12}}, {"base": {"repo": {"full_name": REPO}, "ref": "main"}},
    {"base": {"repo": {"full_name": "other/project"}, "ref": "development"}},
    {"number": 9}, {"head": {"sha": "bad"}}, {"body": "Closes #4!"},
    {"body": f"```\nLighthouse-Issue: {REPO}#4\nLighthouse-Work-Order: order\n```"},
    {"body": f"Lighthouse-Issue: {REPO}#4\nLighthouse-Work-Order: other"},
])
def test_wrong_pull_cannot_advance(fields: dict[str, Any]) -> None:
    mapper = GitHubFacts(replace(CONTEXT, work=Work(4, "order", BINDING, 8)))
    result = mapper.normalize(replace(resources(), pull=pull(**fields), reviews=[]))
    assert result.hold and result.pull is None


@pytest.mark.parametrize("reviews,verdict", [
    ([review(user={"id": 11})], None), ([review(commit_id=RESULT)], None),
    ([review(), review(id=91, state="COMMENTED")], Verdict.APPROVED),
    ([review(state="PENDING", submitted_at=None)], None),
    ([review(), review(id=91, state="DISMISSED", submitted_at=LATER)], None),
    ([review(id=91, state="CHANGES_REQUESTED", submitted_at=LATER), review()], Verdict.CHANGES),
])
def test_review_effectiveness(reviews: list[dict[str, Any]], verdict: Verdict | None) -> None:
    mapper = GitHubFacts(replace(CONTEXT, work=Work(4, "order", BINDING)))
    result = mapper.normalize(replace(resources(), pull=pull(), reviews=reviews))
    assert result.hold is None
    assert (result.review.verdict if result.review else None) is verdict


@pytest.mark.parametrize("fields,reviews", [
    ({"merge_commit_sha": None}, [review()]),
    ({"merged_by": {"id": 12}}, [review()]),
    ({"merged_at": None}, [review()]),
    ({}, [review(submitted_at="2026-11-23T12:00:00Z")]),
    ({}, None),
])
def test_unproven_merge_is_hold(
    fields: dict[str, Any], reviews: list[dict[str, Any]] | None,
) -> None:
    mapper = GitHubFacts(replace(CONTEXT, work=Work(4, "order", BINDING)))
    result = mapper.normalize(replace(resources(), pull=pull(merged=True, **fields), reviews=reviews))
    assert result.hold and result.merge is None
