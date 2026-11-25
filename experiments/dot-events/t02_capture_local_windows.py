"""Local facts for dormant capture composition, with explicit I/O boundaries."""

from __future__ import annotations

import hashlib
import os
import queue
import re
import socket
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from t02_capture_local import LocalCaptureObservation
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_event_types import Hold, decode

_MAX_ARTIFACT_BYTES = 128 * 1024 * 1024


def _canonical(path: Path, *, directory: bool) -> str:
    """Check exact path text and reject reparse points in every ancestor."""
    if str(path.resolve(strict=True)) != str(path):
        raise Hold("capture local path changed")
    for item in (path, *path.parents):
        info = item.lstat()
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise Hold("capture local reparse point held")
    if path.is_dir() if directory else path.is_file():
        return str(path)
    raise Hold("capture local object type held")


def _digest(path: Path, clock: Callable[[], int], deadline: int) -> str:
    before = path.stat()
    if not 0 < before.st_size <= _MAX_ARTIFACT_BYTES:
        raise Hold("capture artifact size held")
    checksum = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        while clock() < deadline:
            data = stream.read(min(1024 * 1024, _MAX_ARTIFACT_BYTES - read + 1))
            if not data:
                if (read == before.st_size and path.stat() == before
                    and _canonical(path, directory=False) == str(path) and clock() < deadline):
                    return checksum.hexdigest()
                break
            read += len(data)
            if read > _MAX_ARTIFACT_BYTES:
                break
            checksum.update(data)
    raise Hold("capture artifact inspection held")


def observe_local_capture(
    packet: CapturePacket,
    host_name: Callable[[], str],
    git_projection: Callable[[Path, int], tuple[str, str, bool]],
    clock: Callable[[], int],
    deadline: int,
    *, canonical: Callable[..., str] = _canonical,
    digest: Callable[[Path, Callable[[], int], int], str] = _digest,
) -> LocalCaptureObservation:
    """Observe only declared local paths; never read either private secret."""
    fields = decode(packet.canonical, MAX_PACKET_BYTES)

    def path(key: str) -> Path:
        value = fields[key]
        if clock() >= deadline or not isinstance(value, str):
            raise Hold("capture local observer held")
        return Path(value)

    checkout = canonical(path("checkout"), directory=True)
    root = Path(checkout)
    names = ("runtime_archive", "runtime_executable", "platform_key", "loopback_bearer", "state")
    entries = tuple(canonical(path(key), directory=False) for key in names)
    repo, head, clean = git_projection(root, deadline)
    archive, executable = (digest(Path(name), clock, deadline) for name in entries[:2])
    host = host_name()
    if clock() >= deadline:
        raise Hold("capture local observation expired")
    return LocalCaptureObservation(host, repo, checkout, head, clean, archive, executable, entries)

def _project_git(
    argv: tuple[str, ...], *, cwd: Path, env: dict[str, str], timeout: float,
) -> bytes:
    """Read bounded bytes without a shell; kill only the owned Git child."""
    end = time.monotonic() + timeout
    process = subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output: queue.Queue[bytes | OSError] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            assert process.stdout is not None
            with process.stdout as stream:
                output.put(stream.read(_MAX_GIT_OUTPUT + 1))
        except OSError as exc:
            output.put(exc)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        result = output.get(timeout=max(0.0, end - time.monotonic()))
        if isinstance(result, OSError) or len(result) > _MAX_GIT_OUTPUT:
            raise Hold("capture Git output held")
        if process.wait(timeout=max(0.0, end - time.monotonic())) != 0:
            raise Hold("capture Git operation held")
        return result
    except (queue.Empty, subprocess.TimeoutExpired):
        raise Hold("capture Git deadline held") from None
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=max(0.0, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                # The containing owner, not this call, confirms eventual quiescence.
                raise Hold("capture Git shutdown unconfirmed") from None


class GitRunner(Protocol):
    """Limited read-only Git invocation seam for offline tests."""

    def __call__(
        self, argv: tuple[str, ...], *, cwd: Path, env: dict[str, str], timeout: float,
    ) -> bytes: ...


_MAX_GIT_OUTPUT = 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{40}")
_ALLOWED_PREFIX = (
    "-c", "core.hooksPath=NUL", "-c", "core.fsmonitor=false",
    "-c", "core.attributesFile=NUL", "-c", "status.submoduleSummary=false",
)


def verify_checkout(
    checkout: Path, expected_head: str, *, expected_checkout: Path,
    expected_host: str, expected_origin: str, git_executable: Path, git_sha256: str,
    clock: Callable[[], int], deadline_ms: int, host_name: Callable[[], str] = socket.gethostname,
    runner: GitRunner = _project_git, canonical: Callable[..., str] = _canonical,
    digest: Callable[[Path, Callable[[], int], int], str] = _digest,
) -> tuple[str, str, bool]:
    """Project host, origin, head and tracked status without fetching or executing repo hooks.

    Expected checkout, host, executable path and hash must come from trusted
    local configuration. The operator must have exclusive control of the Git
    installation and checkout; this is not isolation from concurrent local writers.
    """
    def checkpoint() -> None:
        if clock() >= deadline_ms:
            raise Hold("capture local observation expired")

    try:
        checkpoint()
        if (not expected_host or host_name() != expected_host
            or str(checkout) != str(expected_checkout) or not checkout.is_absolute()
            or not git_executable.is_absolute() or git_executable.name.lower() != "git.exe"
            or _SHA.fullmatch(expected_head) is None
            or re.fullmatch(r"[0-9a-f]{64}", git_sha256) is None
            or re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+\.git", expected_origin) is None):
            raise Hold("capture local binding held")
        root = Path(canonical(checkout, directory=True))
        git = canonical(git_executable, directory=False)
        if root != expected_checkout or git != str(git_executable):
            raise Hold("capture local canonical binding held")
        if digest(git_executable, clock, deadline_ms) != git_sha256:
            raise Hold("capture Git executable digest held")

        metadata = root / ".git"
        for directory in (metadata, metadata / "objects", metadata / "refs"):
            canonical(directory, directory=True)
        for file in ("HEAD", "config", "index"):
            canonical(metadata / file, directory=False)
        for item in ("commondir", "config.worktree", "info/grafts", "objects/info/alternates"):
            if (metadata / item).exists() or (metadata / item).is_symlink():
                raise Hold("capture linked Git metadata held")

        env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR"}}
        env.update({
            "GIT_CONFIG_GLOBAL": "NUL", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ATTR_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_DIR": str(metadata), "GIT_WORK_TREE": str(root),
            "GIT_NO_LAZY_FETCH": "1",
        })

        def run(*args: str) -> bytes:
            timeout = (deadline_ms - clock()) / 1000
            if timeout <= 0:
                raise Hold("capture Git deadline held")
            output = runner(
                (git, *_ALLOWED_PREFIX, *args), cwd=root, env=env, timeout=timeout,
            )
            checkpoint()
            if len(output) > _MAX_GIT_OUTPUT:
                raise Hold("capture Git output held")
            return output

        raw = run("config", "--local", "--no-includes", "--null", "--list")
        rows = _rows(raw)
        origin = []
        for row in rows:
            name, sep, value = row.partition(b"\n")
            if (name.startswith((b"include.", b"includeif.", b"filter.", b"extensions."))
                or name in (b"core.worktree", b"core.fsmonitor", b"core.hookspath",
                            b"core.attributesfile", b"core.sparsecheckout", b"core.ignorestat",
                            b"splitindex.sharedindexexpire", b"core.splitindex")):
                raise Hold("capture unsafe Git configuration held")
            if name == b"remote.origin.url":
                if not sep:
                    raise Hold("capture Git origin held")
                origin.append(value)
        if origin != [expected_origin.encode("ascii")]:
            raise Hold("capture Git origin held")

        def head() -> None:
            current = run("rev-parse", "--verify", "HEAD^{commit}")
            if current.rstrip(b"\r\n") != expected_head.encode("ascii"):
                raise Hold("capture Git head held")

        head()
        for row in _rows(run("ls-files", "--stage", "-z")):
            attrs, sep, name = row.partition(b"\t")
            mode, _, stage = attrs.split(b" ")
            if not sep or not name or mode not in (b"100644", b"100755") or stage != b"0":
                raise Hold("capture linked or unresolved tracked entries held")
            parts = name.decode("utf-8").split("/")
            if any(part in {"", ".", ".."} or ":" in part or chr(92) in part for part in parts):
                raise Hold("capture tracked path escaped binding")
            path = root
            for i, part in enumerate(parts):
                checkpoint()
                path /= part
                if not path.is_relative_to(root):
                    raise Hold("capture tracked path left checkout")
                if not path.exists() and not path.is_symlink():
                    break
                canonical(path, directory=i < len(parts) - 1)
        for row in _rows(run("ls-files", "-v", "-z")):
            if not row.startswith(b"H "):
                raise Hold("capture hidden tracked status held")
        clean = not run(
            "status", "--porcelain=v1", "-z", "--untracked-files=no", "--ignore-submodules=all",
        )
        head()
        return expected_origin.removeprefix("https://github.com/").removesuffix(".git"), expected_head, clean
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        raise Hold("capture local Git observation held") from None


def _rows(raw: bytes) -> list[bytes]:
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise Hold("capture incomplete Git output")
    rows = raw[:-1].split(b"\0")
    if any(not item for item in rows):
        raise Hold("capture malformed Git output")
    return rows
