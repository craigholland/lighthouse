"""Clock-advance regressions for the private stage's UTC authority."""
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from authorization import ExecutionPacket, VerifiedExecution
from live_stage import Request, StageHold, read_signal, run_stage, write_signal
from test_live_stage import ENV, Completed, _checkout, _verify, _workspace


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


@pytest.mark.parametrize("mode", ["before-proof", "during-proof", "drift", "old-authority"])
def test_expiry_or_drift_denies_review_effect(tmp_path: Path, mode: str) -> None:
    control, packet = _workspace(tmp_path)
    wall = [packet.expires_at - 1]
    def now() -> datetime:
        return datetime.fromtimestamp(wall[0], UTC)

    run_stage(
        "verifier", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
        verify_call=_verify, utc_now=now,
    )
    effects: list[str] = []
    proofs: list[str] = []
    clock = [103.0]

    def checkout(executable: Path, workspace: Path, approved: ExecutionPacket,
                 remaining: Callable[[], float]) -> None:
        _checkout(executable, workspace, approved, remaining)
        proofs.append(approved.head)
        if len(proofs) != 2:
            return
        assert (control / "review.authority.json").is_file()
        if mode == "during-proof":
            wall[0] += 1
        elif mode == "drift":
            raise StageHold("Fake checkout drift.")
        elif mode == "old-authority":
            clock[0] += 6

    def parent_reverify(_delay: float) -> None:
        run_stage(
            "reverify", control, env=ENV, clock=lambda: 103, parent_pid=lambda: 123,
            verify_call=_verify, utc_now=now,
        )
        authority = read_signal(control / "reverify.result.json")
        write_signal(control / "review.authority.json", authority)
        if mode == "before-proof":
            wall[0] += 1

    def review(
        _packet: ExecutionPacket, _context: bytes, _instructions: bytes, /, *,
        before_review: Callable[[str], None], on_started: Callable[[str, str], None],
        verify_checkout: Callable[[], None], **_kwargs: object,
    ) -> Completed:
        verify_checkout()
        before_review("thread")
        effects.append("review")
        on_started("thread", "turn")
        return Completed("thread", "turn", packet.head, "synthetic")

    reason = {"before-proof": "expired", "during-proof": "expired",
              "drift": "checkout drift", "old-authority": "authority elapsed"}
    with pytest.raises(StageHold, match=reason[mode]):
        run_stage(
            "review", control, env=ENV, clock=lambda: clock[0], parent_pid=lambda: 123,
            sleep=parent_reverify, review_call=review, utc_now=now, checkout_call=checkout,
        )
    assert len(proofs) == (1 if mode == "before-proof" else 2)
    assert not effects
    assert not (control / "review.intent.json").exists()
    assert not (control / "review.started.json").exists()
