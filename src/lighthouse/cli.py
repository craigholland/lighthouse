"""Parse the foundation CLI; this entry point does not start orchestration."""

import argparse
from importlib.metadata import version


def main(argv: list[str] | None = None) -> int:
    """Show help or installed version; reject unsupported arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m lighthouse",
        description="Lighthouse foundation: show help or the installed package version.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=version("lighthouse"),
        help="show the installed package version and exit",
    )
    parser.parse_args(argv)
    return 0
