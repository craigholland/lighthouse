"""Parse the foundation CLI; this entry point does not start orchestration."""

import argparse
from importlib.metadata import version
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Show help or installed version; reject unsupported arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m lighthouse",
        description="Lighthouse foundation: inspect status, help or the installed package version.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=version("lighthouse"),
        help="show the installed package version and exit",
    )
    commands = parser.add_subparsers(dest="command")
    status = commands.add_parser("status", allow_abbrev=False, help="inspect an existing ledger without effects")
    status.add_argument("--ledger", required=True, type=Path)
    status.add_argument("--project", required=True)
    status.add_argument("--dispatch")
    review = commands.add_parser("review", allow_abbrev=False, help="run one already committed review")
    review.add_argument("--settings", required=True, type=Path)
    review.add_argument("--dispatch", required=True)
    args = parser.parse_args(argv)
    if args.command == "review":
        from lighthouse.review_runner import run_review

        try:
            print(run_review(args.settings, args.dispatch))
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            parser.exit(2, "Lighthouse review held: verify the exact private selection and evidence.\n")
    if args.command == "status":
        from lighthouse.operator_status import render_status

        try:
            print(render_status(args.ledger, args.project, args.dispatch))
        except (ValueError, OSError, RuntimeError):
            parser.exit(2, "Lighthouse status unavailable: check the selected existing ledger and identifiers.\n")
    return 0
