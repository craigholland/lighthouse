"""Offline entry for the synthetic known-worker/claim demonstration."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from t02_fixture import fixture_proof


def main(argv: Sequence[str] | None = None) -> int:
    """Only help or disposable synthetic proof; no live command exists."""
    parser = argparse.ArgumentParser(description="Offline T02 known-worker evidence only.")
    parser.add_argument("--dry-run", action="store_true", help="exercise a temporary synthetic fixture")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.print_help()
        return 0
    with TemporaryDirectory() as directory:
        path = Path(directory) / "fixture.sqlite"
        proof = fixture_proof(path)
        proof.seed_fixture()
        proof.on_event("initial")
        proof.receive()
        reopened = fixture_proof(path)
        reopened.on_event("duplicate-with-fresh-id")
        result = reopened.receive()
        if not result.attributed_completion:
            return 1
        if any(len(path.with_suffix(suffix).read_bytes().splitlines()) != 1
               for suffix in (".marker", ".delivery")):
            return 1
    print("Offline fixture: one fake continuation, one fixed marker; no native or live action.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
