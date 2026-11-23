"""Entry point for the offline, synthetic Codex review proof."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Never

from harness import Fake, Journal, Proof, target_a


class OfflineParser(argparse.ArgumentParser):
    """Suppress unexpected argv values from the public error channel."""

    def error(self, message: str) -> Never:
        """Reject unsupported arguments without logging raw external input."""
        self.exit(2, "Only --help or --dry-run is supported; live execution is disabled.\n")


def main() -> int:
    """Run only with explicit dry-run; there is no live composition or fallback."""
    parser = OfflineParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true", help="exercise fake providers only")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("Only --dry-run is available; live execution is disabled.")
    fake = Fake()
    subject = target_a()
    try:
        with TemporaryDirectory(prefix="lighthouse-review-fake-") as tmp:
            driver = Proof(Journal(Path(tmp) / "receipt.json"), fake, fake)
            driver.dispatch(subject)
            driver.observe(subject)
            result = driver.publication(subject)
    except (OSError, RuntimeError):
        print("Offline proof could not use its scratch journal.", file=sys.stderr)
        return 1
    print(f"Offline fake result: {result.phase}; no live review or execution.")
    return 0 if result.phase == "reviewed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
