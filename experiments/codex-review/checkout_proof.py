"""Read-only verification of the exact private review checkout."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import Thread
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from authorization import ExecutionPacket

_LIMIT = 262_144
_ORIGINS = frozenset((
    b"https://github.com/craigholland/lighthouse",
    b"https://github.com/craigholland/lighthouse.git",
))
type GitRun = Callable[[Path, Path, tuple[str, ...], float], bytes]


class CheckoutHold(RuntimeError):
    """Missing or mismatched local proof; never contains raw process data."""


def run_git(executable: Path, workspace: Path, args: tuple[str, ...], timeout: float) -> bytes:
    """Run only the verifier's fixed argument vectors; keep output bounded."""
    env = {
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
    }
    if os.name == "nt" and (system_root := os.environ.get("SystemRoot")):
        env["SystemRoot"] = system_root
    command = (str(executable), "--no-pager", "--no-optional-locks",
               "-c", "core.fsmonitor=false", *args)
    end = monotonic() + timeout
    with subprocess.Popen(
        command, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
    ) as process:
        stream = process.stdout
        assert stream is not None
        chunks: list[bytes] = []

        def read() -> None:
            try:
                chunks.append(stream.read(_LIMIT + 1))
            except OSError:
                return

        reader = Thread(target=read, daemon=True)
        reader.start()
        reader.join(max(0, end - monotonic()))
        if reader.is_alive() or not chunks or len(chunks[0]) > _LIMIT:
            process.kill()
            raise CheckoutHold("Checkout tool output unavailable or too large.")
        try:
            status = process.wait(timeout=max(0, end - monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            raise
        if status != 0:
            raise CheckoutHold("Checkout tool rejected the read-only request.")
        return chunks[0]


def verify_checkout(
    executable: Path, workspace: Path, packet: ExecutionPacket, remaining: Callable[[], float],
    *, run: GitRun = run_git,
) -> None:
    """Reject missing, stale, malformed or dirty local checkout evidence."""
    try:
        if (
            packet.repository != "craigholland/lighthouse"
            or not executable.is_absolute() or executable.resolve(strict=True) != executable
            or executable.name.lower() != "git.exe" or not executable.is_file()
            or not workspace.is_absolute() or workspace.resolve(strict=True) != workspace
            or not workspace.is_dir()
        ):
            raise CheckoutHold("Private checkout or Git binding is invalid.")

        def read(*args: str) -> bytes:
            budget = remaining()
            if not budget > 0:
                raise CheckoutHold("Checkout proof deadline elapsed.")
            raw = run(executable, workspace, args, budget)
            if not remaining() > 0 or len(raw) > _LIMIT:
                raise CheckoutHold("Checkout proof deadline or output limit exceeded.")
            return raw

        root = read("rev-parse", "--show-toplevel").removesuffix(b"\n").removesuffix(b"\r")
        if not root or b"\n" in root or b"\r" in root or Path(root.decode("utf-8")) != workspace:
            raise CheckoutHold("Checkout root mismatch.")
        # System/global inputs are disabled by run_git. Omitting --local
        # includes the higher-priority worktree layer as well as common config.
        # Inspect include directives without following them.
        keys = read("config", "--no-includes", "--name-only", "--null", "--list")
        if not keys.endswith(b"\0") or any(
            not key or key.lower().startswith((b"include.", b"includeif.", b"filter."))
            or (key.lower().startswith(b"url.") and key.lower().endswith(b".insteadof"))
            for key in keys[:-1].split(b"\0")
        ):
            raise CheckoutHold("Checkout configuration is not inert.")
        origin = read("config", "--no-includes", "--null", "--get-all", "remote.origin.url")
        if not origin.endswith(b"\0") or origin[:-1] not in _ORIGINS:
            raise CheckoutHold("Checkout origin mismatch or ambiguity.")
        expected_head = packet.head.encode("ascii")
        head_args = ("rev-parse", "--verify", "HEAD")
        if read(*head_args) not in (expected_head + b"\n", expected_head + b"\r\n"):
            raise CheckoutHold("Checkout head mismatch.")
        index = read("ls-files", "-v", "-z")
        if not index.endswith(b"\0") or any(
            not entry.startswith(b"H ") or len(entry) < 3 for entry in index[:-1].split(b"\0")
        ):
            raise CheckoutHold("Checkout index unavailable or masks tracked changes.")
        if read("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"):
            raise CheckoutHold("Checkout review content is not clean.")
        if read(*head_args) not in (expected_head + b"\n", expected_head + b"\r\n"):
            raise CheckoutHold("Checkout head changed during proof.")
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        raise CheckoutHold("Checkout proof unavailable.") from None
