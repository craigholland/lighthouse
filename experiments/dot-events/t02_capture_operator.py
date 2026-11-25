"""Capture-only offline entry; no operational composition can be selected."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Expose the hold without inspecting arguments as paths or credentials."""
    parser = argparse.ArgumentParser(description="Lighthouse capture-only operator preparation.")
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--dry-run", action="store_true", help="show the offline preparation state")
    options.add_argument("--execute", action="store_true", help="operational execution is disabled")
    args = parser.parse_args(argv)
    if args.execute:
        parser.exit(2, "Held: capture-only execution is disabled.\n")
    if args.dry_run:
        print("Offline preparation only; no packet, provider, listener or runtime was opened.")
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
