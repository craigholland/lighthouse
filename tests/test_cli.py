"""Exercise the installed CLI from outside the checkout."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("--help", "show the installed package version and exit"),
        ("--version", None),
    ],
)
def test_cli_information(tmp_path: Path, option: str, expected: str | None) -> None:
    """The installed module works without a checkout-relative import path."""
    result = subprocess.run(
        [sys.executable, "-I", "-m", "lighthouse", option],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert not result.stderr
    if expected is None:
        assert result.stdout.strip() == version("lighthouse") == "0.1.0.dev0"
    else:
        assert expected in result.stdout


@pytest.mark.parametrize("argument", ["--unknown", "--ver", "start"])
def test_cli_rejects_unknown_arguments(tmp_path: Path, argument: str) -> None:
    """Unsupported options and commands fail without suggesting they ran."""
    result = subprocess.run(
        [sys.executable, "-I", "-m", "lighthouse", argument],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert not result.stdout
    assert ("invalid choice" if argument == "start" else "unrecognized arguments") in result.stderr
    assert argument in result.stderr


@pytest.mark.parametrize("operation", ["import", "--help", "--version"])
def test_foundation_has_no_integration_side_effects(
    tmp_path: Path, operation: str
) -> None:
    """Fence runtime effects in a fresh interpreter running the real entry point."""
    script = """
import importlib.abc
import runpy
import sys

class StandardLibraryOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition(".")[0]
        if root not in sys.stdlib_module_names and root != "lighthouse":
            raise AssertionError(f"Unexpected third-party dependency: {fullname}")
        return None

def deny_integrations(event, _):
    if event.startswith(("socket.", "sqlite3.", "subprocess.")) or event in {
        "os.system", "os.startfile", "os.startfile/2", "os.exec", "os.spawn",
        "os.posix_spawn", "os.fork", "os.forkpty",
    }:
        raise AssertionError(f"Unexpected integration side effect: {event}")

sys.meta_path.insert(0, StandardLibraryOnly())
sys.addaudithook(deny_integrations)
operation = sys.argv[1]
if operation == "import":
    import lighthouse
    import lighthouse.__main__
else:
    sys.argv = ["lighthouse", operation]
    runpy.run_module("lighthouse", run_name="__main__", alter_sys=True)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, operation],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    if operation == "import":
        assert not result.stdout
    elif operation == "--help":
        assert "show the installed package version and exit" in result.stdout
    else:
        assert result.stdout.strip() == version("lighthouse")
