"""Fake read-only tool responses, not subprocess executions."""
from pathlib import Path

import pytest
from checkout_proof import CheckoutHold, verify_checkout
from test_authorization import packet_for


@pytest.mark.parametrize("failure", (
    "", "root", "origin", "head", "index", "dirty", "malformed", "unavailable", "deadline",
    "head-changed", "config", "oversize",
))
def test_exact_clean_checkout_requires_current_bounded_tool_evidence(
    tmp_path: Path, failure: str,
) -> None:
    workspace = (tmp_path / "checkout")
    workspace.mkdir()
    git = tmp_path / "git.exe"
    git.touch()
    packet = packet_for(tmp_path)
    budget = 5.0
    calls: list[tuple[str, ...]] = []
    expected = [
        (("rev-parse", "--show-toplevel"), workspace.as_posix().encode() + b"\n"),
        (("config", "--local", "--null", "--get-all", "remote.origin.url"),
         b"https://github.com/craigholland/lighthouse.git\0"),
        (("config", "--local", "--name-only", "--null", "--list"), b"remote.origin.url\0"),
        (("rev-parse", "--verify", "HEAD"), packet.head.encode() + b"\n"),
        (("ls-files", "-v", "-z"), b"H example.py\0"),
        (("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"), b""),
        (("rev-parse", "--verify", "HEAD"), packet.head.encode() + b"\n"),
    ]
    bad = {
        "root": (0, b"another\0root"), "origin": (1, b"https://github.com/other/repo\0"),
        "head": (3, b"b" * 40 + b"\n"), "index": (4, b"S example.py\0"),
        "dirty": (5, b" M example.py\0"), "malformed": (0, b"\xff\n"),
        "head-changed": (6, b"b" * 40 + b"\n"), "config": (2, b"filter.example.clean\0"),
        "oversize": (5, b"/" * 262_145),
    }

    def run(exe: Path, cwd: Path, args: tuple[str, ...], timeout: float) -> bytes:
        nonlocal budget
        index = len(calls)
        assert exe == git and cwd == workspace and timeout == 5
        assert args == expected[index][0]
        calls.append(args)
        if failure == "unavailable":
            raise OSError("private mock command details")
        if failure == "deadline":
            budget = 0
        if failure in bad and index == bad[failure][0]:
            return bad[failure][1]
        return expected[index][1]

    if failure:
        with pytest.raises(CheckoutHold) as caught:
            verify_checkout(git, workspace, packet, lambda: budget, run=run)
        assert "private mock" not in str(caught.value) and str(workspace) not in str(caught.value)
        assert len(calls) == (bad[failure][0] + 1 if failure in bad else 1)
    else:
        verify_checkout(git, workspace, packet, lambda: budget, run=run)
        assert calls == [args for args, _ in expected]
