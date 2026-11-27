"""Request-level evidence for the T02 fake handoff and managed marker."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from t02_fixture import FakeKnownWorker, fixture_proof, fixture_work
from t02_receiver import Acceptance, Delivery, Observation, Proof, StateError, Work


def counts(path: Path) -> tuple[int, int]:
    """Count effects, not call dispositions or database flags."""
    delivery = path.with_suffix(".delivery")
    marker = path.with_suffix(".marker")
    return (
        len(delivery.read_bytes().splitlines()) if delivery.exists() else 0,
        len(marker.read_bytes().splitlines()) if marker.exists() else 0,
    )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    target = tmp_path / "fixture.sqlite"
    fixture_proof(target).seed_fixture()
    return target


def test_duplicate_and_reordered_hints_after_restart(path: Path) -> None:
    proof = fixture_proof(path)
    assert not proof.receive().started
    assert proof.on_event("later").turn == "fixture-turn"
    assert not proof.status().attributed_completion
    assert proof.receive().attributed_completion
    for event in ("earlier", "later", "new-id-for-same-work"):
        reopened = fixture_proof(path)
        assert reopened.on_event(event).attributed_completion
        assert reopened.receive().attributed_completion
    assert counts(path) == (1, 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "another"}, {"revision": "b" * 40}, {"worker": "other"},
        {"host": "other"}, {"checkout": "other"}, {"role": "lead"},
        {"authority": "revoked"}, {"expires": 101}, {"dispatch": "new"},
    ],
)
def test_reject_changed_observed_work(path: Path, changes: dict[str, str | int]) -> None:
    work = fixture_work(path)
    moved = replace(work, **changes)  # type: ignore[arg-type]
    proof = Proof(path, work, FakeKnownWorker(path), lambda: Observation(moved, True), lambda: 10)
    assert proof.on_event("hint").hold
    assert not proof.receive().started
    assert counts(path) == (0, 0)
    assert not fixture_proof(path).status().attempted


def test_unavailable_then_expired_retains_attempt(path: Path) -> None:
    work = fixture_work(path)
    worker = FakeKnownWorker(path)
    connected = False
    tick = 10
    proof = Proof(path, work, worker, lambda: Observation(work, connected), lambda: tick)
    assert proof.on_event("offline").hold
    connected = True
    assert proof.on_event("online").attempted
    connected = False
    assert proof.receive().hold
    connected = True
    tick = work.expires
    assert proof.receive().hold
    assert proof.on_event("new").attempted
    assert counts(path) == (1, 0)


@pytest.mark.parametrize("did_accept", [True, False])
def test_lost_ack_delayed_exact_acceptance(path: Path, did_accept: bool) -> None:
    work = fixture_work(path)
    worker = FakeKnownWorker(path)
    worker.drop = True
    proof = Proof(path, work, worker, lambda: Observation(work, True), lambda: 10)
    result = proof.on_event("hint")
    assert result.attempted and not result.acknowledged and result.hold
    # A synchronous transport loss may still have invoked the local worker.
    if did_accept:
        assert proof.receive().marker
        assert not proof.status().attributed_completion
    assert fixture_proof(path).on_event("redelivery").hold
    assert proof.reconcile().hold
    for evidence in (
        Acceptance("different", work.worker, work.revision, "x"),
        Acceptance(work.dispatch, work.worker, work.revision, ""),
    ):
        worker.acceptance = evidence
        assert proof.reconcile().hold
        assert proof.status().turn is None
    if did_accept:
        worker.acceptance = Acceptance(work.dispatch, work.worker, work.revision, "real-fixture-turn")
        resolved = proof.reconcile()
        assert resolved.attributed_completion and not resolved.acknowledged
        worker.acceptance = replace(worker.acceptance, turn="conflict")
        assert proof.reconcile().hold and proof.status().turn == "real-fixture-turn"
    assert counts(path) == (1, int(did_accept))


def test_wrong_state_path_and_corrupt_state(path: Path) -> None:
    work = fixture_work(path)
    other = path.with_name("other.sqlite")
    unknown = Proof(other, work, FakeKnownWorker(other), lambda: Observation(work, True), lambda: 10)
    with pytest.raises(StateError):
        unknown.seed_fixture()
    assert unknown.on_event("hint").hold and not other.exists()
    other.write_bytes(path.read_bytes())
    assert fixture_proof(other).on_event("copied").hold
    path.write_bytes(b"not sqlite")
    assert fixture_proof(path).on_event("corrupt").hold
    assert path.read_bytes() == b"not sqlite"
    assert counts(path) == (0, 0)


def test_schema_change_and_contention_hold_without_recreation(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        assert fixture_proof(path).on_event("locked").hold
        assert counts(path) == (0, 0)
        db.rollback()
        db.execute("PRAGMA user_version=0")
    assert fixture_proof(path).on_event("wrong schema").hold
    assert counts(path) == (0, 0)


@pytest.mark.parametrize("operation", ["handoff", "receive"])
def test_lost_commit_confirmation_holds_on_restart(
    path: Path, operation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = fixture_proof(path)
    if operation == "receive":
        proof.on_event("hint")
    original = Proof._transaction

    @contextmanager
    def uncertain(self: Proof, *, validate: bool = True) -> Iterator[sqlite3.Connection]:
        with original(self, validate=validate) as db:
            yield db
        raise sqlite3.OperationalError("fixture: acknowledgement to commit lost")

    with monkeypatch.context() as patch:
        patch.setattr(Proof, "_transaction", uncertain)
        result = proof.receive() if operation == "receive" else proof.on_event("hint")
    assert result.hold
    reopened = fixture_proof(path)
    result = reopened.receive() if operation == "receive" else reopened.on_event("duplicate")
    assert result.hold
    assert counts(path) == (int(operation == "receive"), 0)


def run_children(path: Path, operation: str, children: int) -> list[int]:
    """Release ready children together and bound every wait and cleanup."""
    script = Path(__file__).with_name("t02_process_fixture.py")
    procs: list[subprocess.Popen[str]] = []
    env = {"PYTHONIOENCODING": "utf-8"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    try:
        for _ in range(children):
            procs.append(subprocess.Popen(  # noqa: S603
                [sys.executable, "-E", str(script), str(path), operation],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ))
        # Reader tasks are bounded by the parent timeout and pipes close on cleanup.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=children) as pool:
            for proc in procs:
                assert proc.stdout is not None
            ready = [pool.submit(read_ready, proc) for proc in procs]
            try:
                assert [future.result(timeout=8) for future in ready] == ["ready\n"] * children
            except BaseException:
                for proc in procs:
                    if proc.poll() is None:
                        proc.kill()
                raise
        for proc in procs:
            assert proc.stdin is not None
            proc.stdin.write("advance\n")
            proc.stdin.flush()
        return [proc.wait(timeout=8) for proc in procs]
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=8)


def read_ready(proc: subprocess.Popen[str]) -> str:
    assert proc.stdout is not None
    return proc.stdout.readline()


def test_real_competing_processes_and_reopen(path: Path) -> None:
    assert run_children(path, "handoff", 3) == [0, 0, 0]
    assert run_children(path, "receive", 3) == [0, 0, 0]
    proof = fixture_proof(path)
    assert proof.on_event("another").attributed_completion
    assert proof.receive().attributed_completion
    assert counts(path) == (1, 1)


@pytest.mark.parametrize("operation, markers", [("crash-before", 0), ("crash-after", 1)])
def test_process_exit_after_claim_before_durable_receipt(
    path: Path, operation: str, markers: int,
) -> None:
    proof = fixture_proof(path)
    assert proof.on_event("one").attempted
    assert run_children(path, operation, 1) == [23]
    reopened = fixture_proof(path)
    result = reopened.receive()
    assert result.started and not result.marker and result.hold
    assert counts(path) == (1, markers)


def test_delivery_crash_before_acceptance_record_never_retries(path: Path) -> None:
    assert run_children(path, "crash-delivery", 1) == [23]
    reopened = fixture_proof(path)
    status = reopened.on_event("reordered-after-restart")
    assert status.attempted and not status.acknowledged and status.turn is None and status.hold
    assert reopened.reconcile().hold
    assert counts(path) == (1, 0)


def test_callback_ack_does_not_prove_native_acceptance(path: Path) -> None:
    class AckOnly(FakeKnownWorker):
        def continue_known(self, work: Work) -> Delivery:
            super().continue_known(work)
            self.acceptance = None
            return Delivery(True)

    work = fixture_work(path)
    proof = Proof(path, work, AckOnly(path), lambda: Observation(work, True), lambda: 10)
    status = proof.on_event("transport-ack")
    assert status.acknowledged and status.turn is None and status.hold
    assert fixture_proof(path).on_event("again") == status
    assert not proof.reconcile().attributed_completion
    assert counts(path) == (1, 0)


def test_runtime_import_does_not_create_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from t02_proof import main

    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert main(["--dry-run"]) == 0
    with pytest.raises(SystemExit) as invalid:
        main(["--live"])
    assert invalid.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_conflicting_known_turn_holds_marker_after_reopen_and_competition(path: Path) -> None:
    work = fixture_work(path)
    worker = FakeKnownWorker(path)
    proof = Proof(path, work, worker, lambda: Observation(work, True), lambda: 10)
    accepted = proof.on_event("first")
    assert accepted.acknowledged and accepted.turn == "fixture-turn"
    worker.acceptance = Acceptance(work.dispatch, work.worker, work.revision, "contradictory-turn")
    assert proof.reconcile().hold
    reopened = fixture_proof(path)
    assert run_children(path, "receive", 3) == [0, 0, 0]
    assert counts(path) == (1, 0)
    for result in (proof.status(), reopened.status(), reopened.on_event("new-id"), reopened.receive()):
        assert result.hold and result.attempted and result.acknowledged
        assert result.turn == "fixture-turn" and not result.started and not result.attributed_completion
    worker.acceptance = Acceptance(work.dispatch, work.worker, work.revision, "fixture-turn")
    assert proof.reconcile().hold
    assert counts(path) == (1, 0)
