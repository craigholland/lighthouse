"""Validate pinned SDK response parsing with synthetic records only."""

import pytest
from harness import Outcome, Run
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


def test_known_thread_read() -> None:
    """The typed thread response recovers only a unique matching run."""
    run = Run(thread="fake-thread", turn="fake-turn")
    turn = {"id": run.turn, "status": "inProgress", "items": []}
    thread = {
        "id": run.thread, "sessionId": "fake-session", "createdAt": 0, "updatedAt": 0,
        "cwd": "C:/synthetic/example", "cliVersion": "0.171.0", "ephemeral": False,
        "modelProvider": "fake-provider", "preview": "", "source": "cli",
        "status": {"type": "idle"}, "turns": [turn],
    }
    assert observed_run({"thread": thread}, run) == "running"
    assert observed_run({"thread": {**thread, "turns": [turn, turn]}}, run) == "unknown"
