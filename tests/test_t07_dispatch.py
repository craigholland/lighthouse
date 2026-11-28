
"""Actual composed reconcile-to-COMMENT path with fake I/O and temporary SQLite."""

import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from test_coordinator import CYCLE, accept, assemble, with_pull
from test_github import HEAD, PROJECT, REPO
from test_github_collection import Fake
from test_t07_stdio import (
    ACK,
    DONE,
    ENTER,
    EXIT,
    TURN_ACK,
    FakeSession,
    Shutdown,
    final_answer,
    notify,
)

from lighthouse.adapters.codex.stdio import ReviewRequest, StdioReviewWorker
from lighthouse.adapters.github.review_publisher import ReviewPublisher
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.ledger import LedgerError
from lighthouse.application.review_dispatch import (
    Attempt,
    Cleanup,
    Completion,
    Remote,
    ReviewDispatch,
    ReviewInput,
    Stage,
    Status,
    Target,
)
from lighthouse.domain.workflow import Execution, Outcome
from lighthouse.review_composition import compose_review_dispatch


def commit_review(path: Path, ledger: SQLiteLedger, *, head: str = HEAD, version: int = 2) -> ReviewInput:
    fake = Fake()
    with_pull(fake, discover=version == 2, head=head)
    result = assemble(path, fake, ledger).reconcile(replace(CYCLE, revision=f"event-{version}", version=version))
    assert result.phase is Outcome.REVIEW
    work = ledger.state(REPO).work
    assert work
    intent, = [i for i in result.intents if i.operation == "review" and i.head == head]
    return ReviewInput(Target(REPO, work.order, intent.dispatch_id, work.issue, 8, head, work.binding),
                       "Read-only ordinary application review.", "This fixture contains no private context.")


class Edges:
    """Injected queue, protocol session and isolated GitHub stub."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.queue: list[Callable[[], None]] = []
        self.sessions: list[FakeSession] = []
        self.frames = (ENTER, EXIT, DONE, ACK)
        self.cleanup = Shutdown(True, True)
        self.head = HEAD
        self.posts: list[dict[str, object]] = []
        self.lose_ack = False
        self.drop_outcome = False
        self.raise_enqueue = False
        self.move_on_shutdown = False
        self.startup_failure = ""

    def outside_transaction(self) -> None:
        with sqlite3.connect(self.path, timeout=0.05) as probe:
            probe.execute("BEGIN IMMEDIATE")

    def current(self, target: Target) -> bool:
        self.outside_transaction()
        return target.repository == REPO and target.head == self.head

    def open_session(self, req: ReviewRequest, deadline: float) -> FakeSession:
        self.outside_transaction()
        assert (req.repository, req.issue, req.pull_request, req.head, deadline) == (REPO, 4, 8, self.head, 20)
        edges = self

        class Session(FakeSession):
            def write(self, data: bytes, deadline: float) -> None:
                super().write(data, deadline)
                req = json.loads(data)
                stage = edges.startup_failure
                mode = req.get("method")
                response = self.queue[-1] if self.queue else None
                if response is None or mode not in {"initialize", "account/read", "thread/start"}:
                    return
                result = json.loads(response)
                if mode == "initialize" and stage == "runtime":
                    result["result"]["userAgent"] = "synthetic unsupported runtime"
                elif mode == "account/read" and stage == "account":
                    result["result"]["account"] = None
                elif mode == "thread/start" and stage == "policy":
                    result["result"]["sandbox"]["networkAccess"] = True
                elif mode == "thread/start" and stage == "thread":
                    result["result"]["thread"]["ephemeral"] = True
                elif mode == "thread/start" and stage == "permission":
                    result = {"id": "permission", "method": "item/commandExecution/requestApproval", "params": {}}
                elif mode == "thread/start" and stage == "transport":
                    raise OSError("synthetic-private-data-must-not-appear")
                else:
                    return
                self.queue[-1] = json.dumps(result).encode() + b"\n"
            def shutdown(self, deadline: float) -> Shutdown:
                if edges.move_on_shutdown:
                    edges.head = "c" * 40
                return super().shutdown(deadline)

        session = Session(req, review_frames=self.frames, cleanup=self.cleanup)
        self.sessions.append(session)
        return session

    def enqueue(self, run: Callable[[], None]) -> None:
        self.outside_transaction()
        if self.raise_enqueue:
            raise OSError("fixture admission acknowledgement lost")
        self.queue.append(run)

    def read_pr(self, repository: str, number: int) -> object:
        self.outside_transaction()
        return {"url": f"https://api.github.com/repos/{repository}/pulls/{number}", "number": number, "state": "open",
                "base": {"repo": {"full_name": repository}}, "head": {"sha": self.head}}

    def authorized_lead(self, repository: str, number: int, head: str) -> int:
        return PROJECT.lead if (repository, number, head) == (REPO, 8, self.head) else 0

    def create_review(self, repository: str, number: int, *, head: str, event: str, body: str) -> object:
        self.outside_transaction()
        state = {"COMMENT": "COMMENTED", "APPROVE": "APPROVED", "REQUEST_CHANGES": "CHANGES_REQUESTED"}[event]
        row = {"id": 247, "commit_id": head, "user": {"id": PROJECT.lead}, "state": state, "body": body,
               "pull_request_url": f"https://api.github.com/repos/{repository}/pulls/{number}"}
        self.posts.append(row)
        if self.lose_ack:
            raise TimeoutError("fixture acknowledgement absent")
        return row

    def list_reviews(self, repository: str, number: int, *, limit: int) -> object:
        self.outside_transaction()
        assert (repository, number, limit) == (REPO, 8, 100)
        return [] if self.drop_outcome else self.posts

    def build(self, *, structured: bool = False) -> ReviewDispatch:
        return compose_review_dispatch(
            PROJECT, SQLiteLedger(self.path), StdioReviewWorker(self.open_session, lambda *_: True, lambda: 0),
            ReviewPublisher(self, repository=REPO), current=self.current, enqueue=self.enqueue,
            deadlines=lambda: (20, 22), workspace=self.path.parent, model="fixture-model.1", structured=structured,
        )


def test_committed_reconcile_to_comment_once_without_releasing_work(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    edges = Edges(path)
    services = (edges.build(), edges.build())
    barrier = Barrier(2, timeout=2)

    def compete(index: int) -> Status:
        barrier.wait()
        return services[index].start(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(compete, (0, 1)))
    assert all(result.stage is Stage.EXECUTION_UNKNOWN for result in statuses)
    run, = edges.queue
    assert edges.sessions == edges.posts == []
    run()
    run()  # A duplicate delivery of the same queued callback must also be inert.
    status = edges.build().status(request.target.dispatch)
    assert status.stage is Stage.COMMENTED and status.attempt and status.attempt.review_id == 247
    assert status.attempt.target == request.target and status.attempt.fingerprint == request.fingerprint()
    assert len(edges.posts) == len(edges.sessions) == 1
    assert edges.build().start(request).stage is Stage.COMMENTED
    assert ledger.state(REPO).work is not None and ledger.state(REPO).outcome is Outcome.REVIEW
    assert request.context not in repr(status) and "Looks good" not in repr(status)


@pytest.mark.parametrize("case", ["no-commit", "lost-start", "pre-ack", "cleanup", "both-unknown", "approval", "moved", "finished-stale", "lost-post"])
def test_holds_and_bounded_lookup_never_replay(tmp_path: Path, case: str) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    implement = accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    dispatch = request.target.dispatch
    edges = Edges(path)
    if case == "no-commit":
        for unsupported in ("0" * 64, implement):
            bad = replace(request, target=replace(request.target, dispatch=unsupported))
            assert edges.build().start(bad).stage is Stage.HELD
        assert not edges.queue
        return
    edges.raise_enqueue = case == "lost-start"
    edges.lose_ack = case == "lost-post"
    if case in {"pre-ack", "both-unknown"}:
        edges.frames = (ENTER, EXIT, DONE)
    if case in {"cleanup", "both-unknown"}:
        edges.cleanup = Shutdown(True, False)
    if case == "approval":
        edges.frames = (ACK, b'{"id":55,"method":"item/commandExecution/requestApproval","params":{}}\n')
    edges.move_on_shutdown = case == "finished-stale"
    service = edges.build()
    assert service.start(request).stage is Stage.EXECUTION_UNKNOWN
    if case == "moved":
        edges.head = "c" * 40
    if edges.queue:
        edges.queue[0]()
    expected = {
        "lost-start": Stage.EXECUTION_UNKNOWN, "pre-ack": Stage.EXECUTION_UNKNOWN,
        "cleanup": Stage.CLEANUP_UNCONFIRMED, "approval": Stage.APPROVAL_REQUIRED,
        "moved": Stage.UNAVAILABLE, "lost-post": Stage.PUBLISHING,
        "both-unknown": Stage.UNKNOWN_AND_CLEANUP, "finished-stale": Stage.STALE,
    }[case]
    reopened = edges.build()
    status = reopened.status(dispatch)
    assert status.stage is expected and status.attempt
    assert reopened.complete(dispatch, Completion("x" * 64, "other-thread", "other-turn",
                                                "Unattributed output", True)).stage is expected
    assert reopened.start(request).stage is expected and len(edges.queue) <= 1
    if case not in {"moved", "finished-stale"}:
        edges.head = "c" * 40
        replacement = commit_review(tmp_path, ledger, head=edges.head, version=3)
        assert reopened.start(replacement).stage is Stage.HELD
    if case == "lost-post":
        edges.drop_outcome = True
        assert reopened.publish(dispatch).stage is Stage.PUBLISHING
        edges.drop_outcome = False
        assert reopened.publish(dispatch).stage is Stage.COMMENTED
        assert len(edges.posts) == 1
    else:
        assert not edges.posts


def test_receipt_write_failure_and_independent_process_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    dispatch = request.target.dispatch
    edges = Edges(path)
    service = edges.build()
    assert service.start(request).stage is Stage.EXECUTION_UNKNOWN

    old_advance = SQLiteLedger.advance_review

    def fail_save(self: SQLiteLedger, expected: Attempt, updated: Attempt) -> bool:
        if updated.stage is Stage.COMMENTED:
            raise LedgerError("fixture write error")
        return old_advance(self, expected, updated)

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteLedger, "advance_review", fail_save)
        edges.queue[0]()
    assert len(edges.posts) == 1

    source = (
        "import sys; from pathlib import Path; "
        "from lighthouse.adapters.sqlite.ledger import SQLiteLedger; "
        "ledger=SQLiteLedger(Path(sys.argv[1])); "
        "original=ledger.review_attempt(sys.argv[2],sys.argv[3]); "
        "assert original and original.stage.value=='publication-unknown'; "
        "assert original.target.dispatch==sys.argv[3] and original.marker; "
        "from dataclasses import replace; "
        "from lighthouse.application.review_dispatch import Attempt; "
        "assert not ledger.claim_review(Attempt(original.target, original.fingerprint))"
    )
    subprocess.run([sys.executable, "-I", "-c", source, str(path), REPO, dispatch],
                   cwd=tmp_path, check=True, capture_output=True, timeout=10)
    assert edges.build().publish(dispatch).stage is Stage.COMMENTED
    assert len(edges.posts) == 1


def test_rolled_back_review_recommendation_cannot_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    original = SQLiteLedger._connection
    seen: list[str] = []

    @contextmanager
    def rollback(self: SQLiteLedger, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with original(self, write=write) as conn:
            yield conn
            if write:
                for identifier, data in conn.execute("SELECT id, data FROM intents"):
                    if '"operation":"review"' in data:
                        seen.append(identifier)
                raise LedgerError("test forced rollback before commit")

    fake = Fake()
    with_pull(fake, discover=True)
    coordinator = assemble(tmp_path, fake, ledger)
    with monkeypatch.context() as patch:
        patch.setattr(SQLiteLedger, "_connection", rollback)
        result = coordinator.reconcile(replace(CYCLE, revision="rolled-back", version=2))
    assert result.reason == "ledger-write-failed" and len(seen) == 1
    work = ledger.state(REPO).work
    assert work is not None and work.pr is None and all(i.dispatch_id != seen[0] for i in ledger.intents(REPO))
    edges = Edges(path)
    request = ReviewInput(Target(REPO, work.order, seen[0], work.issue, 8, HEAD, work.binding),
                          "Review only the configured application.", "Synthetic rollback evidence.")
    assert edges.build().start(request).stage is Stage.HELD
    assert not edges.queue and not edges.sessions and not edges.posts


@pytest.mark.parametrize("already_queued", [False, True])
def test_newer_durable_hold_gates_dispatch(tmp_path: Path, already_queued: bool) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    edges = Edges(path)
    service = edges.build()
    if already_queued:
        assert service.start(request).stage is Stage.EXECUTION_UNKNOWN
    fake = Fake()
    with_pull(fake)
    held = replace(CYCLE, revision="workflow-hold", version=3, reviewing=Execution.UNKNOWN)
    assert assemble(tmp_path, fake, ledger).reconcile(held).phase is Outcome.HOLD
    if already_queued:
        edges.queue[0]()
        retained = service.status(request.target.dispatch).attempt
        assert retained is not None and retained.stage is Stage.CLAIMED
    else:
        assert service.start(request).stage is Stage.HELD
        assert not edges.queue
    assert not edges.sessions and not edges.posts
    assert ledger.state(REPO).outcome is Outcome.HOLD
    assert any(intent.dispatch_id == request.target.dispatch for intent in ledger.intents(REPO))

    fresh = Fake()
    with_pull(fresh)
    recovered = replace(CYCLE, revision="workflow-recovered", version=4)
    assert assemble(tmp_path, fresh, ledger).reconcile(recovered).phase is Outcome.REVIEW
    if not already_queued:
        assert service.start(request).stage is Stage.EXECUTION_UNKNOWN
    edges.queue[0]()
    assert service.status(request.target.dispatch).stage is Stage.COMMENTED
    assert len(edges.sessions) == len(edges.posts) == 1


@pytest.mark.parametrize(("event", "remote", "approval"), [
    ("completed", Remote.COMPLETED, False),
    ("incomplete", Remote.UNKNOWN, False),
    ("approval", Remote.UNKNOWN, True),
])
def test_failed_cleanup_preserves_independent_status(
    tmp_path: Path, event: str, remote: Remote, approval: bool,
) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    edges = Edges(path)
    edges.cleanup = Shutdown(True, False)
    edges.frames = {
        "completed": (ACK, ENTER, EXIT, DONE),
        "incomplete": (ACK, ENTER),
        "approval": (ACK, b'{"id":55,"method":"item/commandExecution/requestApproval","params":{}}\n'),
    }[event]
    assert edges.build().start(request).stage is Stage.EXECUTION_UNKNOWN
    edges.queue[0]()
    reopened = edges.build()
    status = reopened.status(request.target.dispatch)
    saved = status.attempt
    assert saved is not None and saved.thread and saved.turn
    assert saved.lifecycle.remote is remote and saved.lifecycle.cleanup is Cleanup.UNCONFIRMED
    assert saved.lifecycle.approval is approval
    assert Cleanup.UNCONFIRMED.value in status.reason
    assert ("approval-required" in status.reason) is approval
    assert (Remote.UNKNOWN.value in status.reason) is (remote is Remote.UNKNOWN)
    assert status.actor == PROJECT.owner
    assert reopened.start(request) == status and reopened.publish(request.target.dispatch) == status
    assert len(edges.queue) == len(edges.sessions) == 1 and not edges.posts
    assert ledger.state(REPO).work is not None


@pytest.mark.parametrize(("event", "expected"), [
    ("APPROVE", "APPROVED"), ("REQUEST_CHANGES", "CHANGES_REQUESTED"), ("COMMENT", "COMMENTED"),
])
def test_explicit_outcome_reopens_without_reposting(tmp_path: Path, event: str, expected: str) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    edges = Edges(path)
    edges.lose_ack = True
    edges.frames = (final_answer(json.dumps({"event": event, "body": "Synthetic review."})), DONE, TURN_ACK)
    runner = edges.build(structured=True)
    runner.start(request)
    edges.queue.pop()()
    assert runner.status(request.target.dispatch).stage is Stage.PUBLISHING
    assert [row["state"] for row in edges.posts] == [expected]
    reopened = edges.build(structured=True)
    assert reopened.start(request).stage is Stage.PUBLISHING
    edges.posts[0]["state"] = "PENDING"
    assert reopened.publish(request.target.dispatch).stage is Stage.PUBLISHING
    edges.posts[0]["state"] = expected
    receipt = reopened.publish(request.target.dispatch)
    assert receipt.attempt is not None and receipt.attempt.event == event and receipt.attempt.review_id == 247
    assert len(edges.posts) == len(edges.sessions) == 1


def test_structured_worker_does_not_promote_free_prose(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    edges = Edges(path)
    prose = ("Review could not be completed: read-only commands to inspect the exact authorized commit "
             "were blocked by execution policy. No defects are established, but the patch cannot be approved "
             "from the supplied summary alone; the correctness verdict reflects this verification limitation.")
    edges.frames = (ENTER, notify("item/completed", {"item": {"type": "exitedReviewMode", "review": prose}}),
                    DONE, TURN_ACK)
    runner = edges.build(structured=True)
    runner.start(request)
    edges.queue.pop()()
    status = runner.status(request.target.dispatch)
    assert status.stage is Stage.EXECUTION_UNKNOWN
    assert status.attempt is not None and status.attempt.lifecycle.remote is Remote.COMPLETED
    assert status.attempt.lifecycle.cleanup is Cleanup.CONFIRMED
    assert not edges.posts


@pytest.mark.parametrize(("failure", "reason", "progress", "local", "stage"), [
    ("runtime", "runtime-unverified", "session-opened", "owned-cleanup-confirmed", "unavailable"),
    ("account", "account-unverified", "runtime-verified", "owned-cleanup-confirmed", "unavailable"),
    ("policy", "policy-unverified", "account-verified", "owned-cleanup-confirmed", "unavailable"),
    ("thread", "thread-unverified", "account-verified", "owned-cleanup-confirmed", "unavailable"),
    ("permission", "permission-attention", "account-verified", "owned-cleanup-confirmed", "approval-required"),
    ("transport", "transport-lost", "account-verified", "owned-cleanup-unconfirmed", "cleanup-unconfirmed"),
])
def test_startup_diagnostic_persists_without_replay(
    tmp_path: Path, failure: str, reason: str, progress: str, local: str, stage: str,
) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    edges = Edges(path)
    edges.startup_failure = failure
    if failure == "transport":
        edges.cleanup = Shutdown(True, False)
    service = edges.build()
    service.start(request)
    edges.queue.pop()()
    command = [sys.executable, "-I", "-m", "lighthouse", "status", "--ledger", str(path),
               "--project", REPO, "--dispatch", request.target.dispatch]
    before = path.read_bytes()
    observed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=10, check=True)
    data = json.loads(observed.stdout)
    assert (data["startup_reason"], data["startup_progress"]) == (reason, progress)
    assert (data["remote"], data["local_cleanup"], data["status"]) == ("not-started", local, stage)
    assert data["approval_required"] == (failure == "permission")
    assert "synthetic-private-data" not in observed.stdout and str(tmp_path) not in observed.stdout
    reopened = edges.build()
    reopened.start(request)
    reopened.publish(request.target.dispatch)
    assert len(edges.sessions) == 1 and not edges.queue and not edges.posts
    assert path.read_bytes() == before
    if failure == "runtime":
        # Remove the new optional key from this owned test record to model old schema-v2 files.
        with sqlite3.connect(path) as conn:
            row, = conn.execute("SELECT data FROM review_attempts").fetchone()
            old = json.loads(row)
            del old["startup"]
            conn.execute("UPDATE review_attempts SET data=?", (json.dumps(old, sort_keys=True, separators=(",", ":")),))
        observed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=10, check=True)
        older = json.loads(observed.stdout)
        assert (older["startup_reason"], older["startup_progress"]) == ("unknown", "unknown")
        assert (older["remote"], older["local_cleanup"], older["status"]) == ("not-started", local, stage)
        assert edges.build().start(request).attempt is not None
        assert len(edges.sessions) == 1 and not edges.queue and not edges.posts
