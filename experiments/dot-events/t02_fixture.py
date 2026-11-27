"""Synthetic-only coordinator and fixture identity for the offline T02 proof."""

from __future__ import annotations

from pathlib import Path

from t02_receiver import Acceptance, Delivery, Observation, Proof, Work


class FakeKnownWorker:
    """Continue the one fixed fake target; record actual calls independently."""

    acceptance: Acceptance | None
    drop: bool

    def __init__(self, path: Path) -> None:
        self.path = path
        self.acceptance = None
        self.drop = False

    def continue_known(self, work: Work) -> Delivery:
        with self.path.with_suffix(".delivery").open("a", encoding="ascii") as stream:
            stream.write("continues fixture-worker\n")
        if self.drop:
            raise TimeoutError("synthetic acknowledgement lost")
        self.acceptance = Acceptance(work.dispatch, work.worker, work.revision, "fixture-turn")
        return Delivery(True, self.acceptance)

    def inspect_known(self, work: Work) -> Acceptance | None:
        return self.acceptance


def fixture_work(path: Path) -> Work:
    """Prepare one canonical binding for the exact synthetic state location."""
    return Work(
        "fixture-project", "fixture/repo", 5, "fixture-dispatch", "marker only",
        "a" * 40, "dot-implementation", "fixture-worker", "fixture-host",
        "fixture-checkout", "fixture-reviewed-authority", 100, str(path.resolve()),
    )


def fixture_proof(path: Path) -> Proof:
    """Reopen the known fixture without creating any state."""
    work = fixture_work(path)
    return Proof(path, work, FakeKnownWorker(path), lambda: Observation(work, True), lambda: 10)
