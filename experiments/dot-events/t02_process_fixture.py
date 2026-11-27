"""Bounded test process; it can only address a known synthetic test DB."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from t02_fixture import FakeKnownWorker, fixture_proof
from t02_receiver import Delivery, Proof, Work


def main() -> int:
    """Hold at a deterministic gate, then perform one synthetic experiment call."""
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("operation", choices=("handoff", "receive", "crash-before", "crash-after", "crash-delivery"))
    args = parser.parse_args()
    path: Path = args.path
    proof = fixture_proof(path)
    print("ready", flush=True)
    if input() != "advance":
        return 2
    if args.operation == "handoff":
        proof.on_event("fixture-race")
    elif args.operation == "crash-delivery":
        recorded = FakeKnownWorker.continue_known

        def exit_after_delivery(self: FakeKnownWorker, work: Work) -> Delivery:
            recorded(self, work)
            os._exit(23)

        FakeKnownWorker.continue_known = exit_after_delivery  # type: ignore[method-assign]
        proof.on_event("fixture-race")
        return 3
    elif args.operation == "receive":
        proof.receive()
    else:
        original = Proof._write_marker
        after = args.operation == "crash-after"

        def exit_at_effect(self: Proof) -> None:
            if after:
                original(self)
            os._exit(23)

        Proof._write_marker = exit_at_effect  # type: ignore[method-assign]
        proof.receive()
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
