"""Clock-advance regressions for the private stage's UTC authority."""
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from authorization import ExecutionPacket, VerifiedExecution
from live_stage import Request, StageHold, read_signal, run_stage, write_signal
from test_live_stage import ENV, Completed, _verify, _workspace


def test_expiry_during_verification_does_not_consume_claim(tmp_path: Path) -> None:
    control, packet = _workspace(tmp_path)
    wall = [packet.expires_at - 1]

    def slow_verification(
        data: bytes, request: Request, remaining: Callable[[], float],
    ) -> VerifiedExecution:
        verified = _verify(data, request, remaining)
        wall[0] += 1
        return verified

    with pytest.raises(StageHold, match="expired"):
        run_stage(
            "verifier", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
            verify_call=slow_verification, utc_now=lambda: datetime.fromtimestamp(wall[0], UTC),
        )
    assert not (control.parent / "t01-55.claim").exists()
    assert not (control / "verifier.result.json").exists()


def test_expiry_after_authority_ipc_denies_review_effect(tmp_path: Path) -> None:
    control, packet = _workspace(tmp_path)
    wall = [packet.expires_at - 1]
    def now() -> datetime:
        return datetime.fromtimestamp(wall[0], UTC)

    run_stage(
        "verifier", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
        verify_call=_verify, utc_now=now,
    )
    effects: list[str] = []

    def parent_reverify(_delay: float) -> None:
        run_stage(
            "reverify", control, env=ENV, clock=lambda: 103, parent_pid=lambda: 123,
            verify_call=_verify, utc_now=now,
        )
        authority = read_signal(control / "reverify.result.json")
        write_signal(control / "review.authority.json", authority)
        wall[0] += 1

    def review(
        _packet: ExecutionPacket, _context: bytes, _instructions: bytes, /, *,
        before_review: Callable[[str], None], on_started: Callable[[str, str], None],
        **_kwargs: object,
    ) -> Completed:
        before_review("thread")
        effects.append("review")
        on_started("thread", "turn")
        return Completed("thread", "turn", packet.head, "synthetic")

    with pytest.raises(StageHold, match="expired"):
        run_stage(
            "review", control, env=ENV, clock=lambda: 103, parent_pid=lambda: 123,
            sleep=parent_reverify, review_call=review, utc_now=now,
        )
    assert not effects
    assert not (control / "review.intent.json").exists()
    assert not (control / "review.started.json").exists()
