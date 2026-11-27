"""Compose fake GitHub I/O, real normalization, workflow and SQLite."""

import sqlite3
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from test_github import (
    CONTEXT,
    HEAD,
    PRE,
    PROJECT,
    REPO,
    TIME,
    pull,
    resources,
    review,
)
from test_github_collection import (
    EVENTS,
    PULLS,
    READY,
    REVIEWS,
    Fake,
    make_scan,
    response,
)

from lighthouse.adapters.github.observation_source import GitHubObservationSource
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.coordinator import Coordinator, Cycle
from lighthouse.application.ledger import Change, IntentStatus, WriteResult
from lighthouse.domain.workflow import Execution, Outcome, Verification, Workflow

CYCLE = Cycle("observation-1", 1, TIME, "order", Execution.QUIESCENT, Execution.QUIESCENT)


def assemble(
    path: Path, fake: Fake, ledger: SQLiteLedger,
) -> Coordinator:
    source = GitHubObservationSource(
        make_scan(path / "cache", fake), lambda state: {4: replace(CONTEXT, work=state.work)},
    )
    return Coordinator(Workflow(PROJECT), ledger, source)


def ready(fake: Fake, *, discover: bool = False, closed: bool = False) -> None:
    data = resources()
    assert isinstance(data.issue, dict)
    issue = {**data.issue, "state": "closed"} if closed else data.issue
    fake.routes[READY].append(response([] if closed else [issue]))
    fake.routes["issues/4"].extend((response(issue), response(issue)))
    fake.routes[EVENTS].append(response(data.events))
    if discover:
        fake.routes[PULLS].append(response([pull()]))


def with_pull(fake: Fake, *, head: str = HEAD, merged: bool = False,
              approval: str | None = None, discover: bool = False) -> None:
    ready(fake, discover=discover, closed=merged)
    actual = pull(merged=merged, head={"sha": head})
    fake.routes["pulls/8"].extend((response(actual), response(actual)))
    items = [] if approval is None else [review(commit_id=head, state=approval)]
    fake.routes[REVIEWS].append(response(items))


def accept(path: Path, ledger: SQLiteLedger) -> str:
    fake = Fake()
    ready(fake)
    result = assemble(path, fake, ledger).reconcile(CYCLE)
    assert result.phase is Outcome.IMPLEMENT and result.write is WriteResult.COMMITTED
    assert result.order == "order" and result.actor == PROJECT.implementer
    intent, = result.intents
    assert intent.status is IntentStatus.PENDING
    return intent.dispatch_id


def test_atomic_admission_exact_replay_conflict_stale_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    original = accept(tmp_path, ledger)
    ledger = SQLiteLedger(path)
    for cycle, result in (
        (CYCLE, WriteResult.DUPLICATE),
        (replace(CYCLE, new_order="different"), WriteResult.CONFLICT),
        (replace(CYCLE, revision="different"), WriteResult.STALE),
    ):
        fake = Fake()
        # Exact replay consults the original version's pre-transition context.
        ready(fake, discover=False)
        fake.routes[PULLS].append(response([]))
        result_status = assemble(tmp_path, fake, ledger).reconcile(cycle)
        assert result_status.write is result
        assert result_status.intents[0].dispatch_id == original
    assert len(ledger.audit(REPO)) == len(ledger.intents(REPO)) == 1


def test_review_revision_reconciliation_and_actual_owner_completion(tmp_path: Path) -> None:
    ledger = SQLiteLedger.initialize(tmp_path / "ledger")
    accept(tmp_path, ledger)
    next_head = "c" * 40
    check = Verification(8, next_head, "checks", "check-next", datetime.fromisoformat(PRE))
    for version, head, verdict, evidence, expected, count in (
        (2, HEAD, None, None, Outcome.REVIEW, 2),
        (3, HEAD, "CHANGES_REQUESTED", None, Outcome.REVISE, 3),
        (4, next_head, None, None, Outcome.REVIEW, 4),
        (5, next_head, "APPROVED", replace(check, head=HEAD), Outcome.HOLD, 4),
        (6, next_head, "APPROVED", check, Outcome.AWAIT_OWNER, 4),
        (7, next_head, "APPROVED", None, Outcome.HOLD, 4),
        (8, next_head, "APPROVED", check, Outcome.AWAIT_OWNER, 4),
        (9, next_head, "APPROVED", check, Outcome.COMPLETE, 4),
    ):
        fake = Fake()
        with_pull(fake, head=head, merged=version == 9, approval=verdict, discover=version == 2)
        cycle = replace(CYCLE, revision=f"observation-{version}", version=version,
                        verification=evidence)
        s = assemble(tmp_path, fake, ledger).reconcile(cycle)
        assert s.write is WriteResult.COMMITTED and s.phase is expected
        assert s.pr == 8 and s.head == head and s.order == "order" and len(s.intents) == count
        if version < 9:
            assert ledger.state(REPO).work is not None
    assert ledger.audit(REPO)[7].decision.outcome is Outcome.UNCHANGED
    assert ledger.state(REPO).work is None


@pytest.mark.parametrize("kind", ["partial", "mapper", "unknown"])
def test_held_evidence_does_not_release_or_replace_work(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    original = accept(tmp_path, ledger)
    before = ledger.state(REPO)
    fake = Fake()
    ready(fake)
    fake.routes[PULLS].append(response([]))
    if kind == "partial":
        fake.routes[EVENTS] = deque([response({})])
    if kind == "mapper":
        data = resources()
        assert isinstance(data.issue, dict)
        changed = {**data.issue, "body": data.issue["body"] + "\nChanged"}
        fake.routes["issues/4"] = deque([response(changed), response(changed)])
    cycle = replace(CYCLE, version=2, revision="unknown",
                    implementation=Execution.UNKNOWN if kind == "unknown" else Execution.QUIESCENT)
    status = assemble(tmp_path, fake, SQLiteLedger(path)).reconcile(cycle)
    assert status.reason == ("unknown-acceptance" if kind == "unknown" else "observation-held")
    assert status.intents[0].dispatch_id == original
    assert ledger.state(REPO).work == before.work
    assert len(ledger.audit(REPO)) == (2 if kind == "unknown" else 1)


def test_failed_write_never_reports_new_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = SQLiteLedger.initialize(tmp_path / "ledger")
    fake = Fake()
    ready(fake)
    connect = sqlite3.connect

    class LastWriteFails(sqlite3.Connection):
        def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
            if sql.startswith("INSERT INTO intents"):
                raise sqlite3.OperationalError("synthetic failure")
            return super().execute(sql, parameters)

    def injected(path: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        # Only the ledger write path is faulted; cache still uses real persistence.
        factory = LastWriteFails if "mode=rw" in str(path) else sqlite3.Connection
        return connect(path, *args, **kwargs, factory=factory)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", injected)
        status = assemble(tmp_path, fake, ledger).reconcile(CYCLE)
    assert status.reason == "ledger-write-failed" and status.write is None
    assert ledger.state(REPO).work is None and not ledger.audit(REPO) and not ledger.intents(REPO)


def test_intervening_commit_before_expected_version_write_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    fake, rival = Fake(), Fake()
    ready(fake)
    ready(rival)
    other = assemble(tmp_path, rival, SQLiteLedger(path))
    record = ledger.record

    def competing(change: Change) -> WriteResult:
        ran = other.reconcile(replace(CYCLE, revision="rival", new_order="rival-order"))
        assert ran.write is WriteResult.COMMITTED
        return record(change)

    monkeypatch.setattr(ledger, "record", competing)
    s = assemble(tmp_path, fake, ledger).reconcile(CYCLE)
    assert (s.write, s.reason, s.order) == (WriteResult.STALE, "write-stale", "rival-order")
    assert [row.observation for row in ledger.audit(REPO)] == ["rival"]
    assert len(ledger.intents(REPO)) == 1


@pytest.mark.parametrize("conflict", [False, True])
def test_replay_uses_reservation_committed_before_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: bool,
) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    fake, rival = Fake(), Fake()
    ready(fake)
    ready(rival)
    other = assemble(tmp_path, rival, SQLiteLedger(path))
    audit = ledger.audit

    def intervening_audit(repository: str) -> tuple[Change, ...]:
        assert other.reconcile(CYCLE).write is WriteResult.COMMITTED
        return audit(repository)

    monkeypatch.setattr(ledger, "audit", intervening_audit)
    cycle = replace(CYCLE, new_order="other-order") if conflict else CYCLE
    status = assemble(tmp_path, fake, ledger).reconcile(cycle)
    assert status.write is (WriteResult.CONFLICT if conflict else WriteResult.DUPLICATE)
    assert (status.version, status.phase, status.order) == (1, Outcome.IMPLEMENT, "order")
    assert status.intents == ledger.intents(REPO)
    assert len(status.intents) == len(audit(REPO)) == 1
