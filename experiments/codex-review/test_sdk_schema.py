"""Validate pinned SDK response parsing with synthetic records only."""

from pathlib import Path

import pytest
from harness import Fake, Journal, Outcome, Proof, Run, target_a
from sdk_schema import completion, observed_run


@pytest.mark.parametrize(("status", "expected"), [
    ("completed", "complete"), ("interrupted", "interrupted"), ("failed", "rejected"),
    ("inProgress", "unknown"), ("not-a-status", "unknown"),
])
def test_completion_is_typed(status: str, expected: Outcome) -> None:
    """Only terminal events with the matching synthetic execution affect state."""
    run = Run(thread="fake-thread", turn="fake-turn")
    turn = {"id": run.turn, "status": status, "items": []}
    assert completion({"threadId": run.thread, "turn": turn}, run) == expected
    assert completion({"threadId": "wrong", "turn": turn}, run) == "unknown"


def test_malformed_sdk_response_is_not_displayed() -> None:
    """A raw provider error or path is never returned to the evidence output."""
    run = Run(thread="fake-thread", turn="fake-turn")
    result = {"error": {"message": "fictional token", "path": "X:/example/private"}}
    assert completion(result, run) == observed_run(result, run) == "unknown"


def thread_fixture(run: Run, status: dict[str, object]) -> dict[str, object]:
    """Build a synthetic typed thread read containing the known turn."""
    turn = {"id": run.turn, "status": "inProgress", "items": []}
    return {
        "id": run.thread, "sessionId": "fake-session", "createdAt": 0, "updatedAt": 0,
        "cwd": "C:/synthetic/example", "cliVersion": "0.171.0", "ephemeral": False,
        "modelProvider": "fake-provider", "preview": "", "source": "cli",
        "status": status, "turns": [turn],
    }


def test_known_thread_read() -> None:
    """The typed thread response recovers only a unique matching run."""
    run = Run(thread="fake-thread", turn="fake-turn")
    thread = thread_fixture(run, {"type": "active", "activeFlags": []})
    assert observed_run({"thread": thread}, run) == "running"
    turn = {"id": run.turn, "status": "inProgress", "items": []}
    assert observed_run({"thread": {**thread, "turns": [turn, turn]}}, run) == "unknown"


@pytest.mark.parametrize(("status", "phase", "reason", "actor"), [
    ({"type": "active", "activeFlags": ["waitingOnApproval"]}, "hold", "permission", "owner"),
    ({"type": "systemError"}, "hold", "unavailable", "lead"),
    ({"type": "active", "activeFlags": ["waitingOnUserInput"]}, "hold", "launch-unknown", "lead"),
    ({"type": "idle"}, "hold", "launch-unknown", "lead"),
    ({"type": "active", "activeFlags": []}, "accepted", None, "lead"),
])
def test_thread_status_drives_proof_recovery(
    tmp_path: Path, status: dict[str, object], phase: str, reason: str | None, actor: str,
) -> None:
    """A typed thread read must preserve attention through the real recovery path."""
    class WorkerFromSchema(Fake):
        def observe(self, run: Run) -> Outcome:
            if self.lost_observation:
                raise ConnectionError
            return observed_run({"thread": thread_fixture(run, status)}, run)

    fake = WorkerFromSchema()
    journal = Journal(tmp_path / "receipt.json")
    target = target_a()
    proof = Proof(journal, fake, fake)
    run = proof.dispatch(target).run
    fake.lost_observation = True
    assert proof.observe(target).reason == "launch-unknown"
    fake.lost_observation = False
    restarted = Proof(journal, fake, fake)
    result = restarted.reconcile_run(target)
    assert (result.phase, result.reason, result.next_actor) == (phase, reason, actor)
    assert (result.confirmed, result.run) == ("accepted", run)
    assert restarted.dispatch(target) == result
    assert fake.starts == 1 and fake.posts == 0
