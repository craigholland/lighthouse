"""Dormant Windows Session using exact owned process/pipe operations."""

from __future__ import annotations

import math
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Protocol

from lighthouse.adapters.codex._win32 import WinChild
from lighthouse.adapters.codex.stdio import RUNTIME, ReviewRequest, Shutdown

MAX_RUNTIME_ARTIFACT_BYTES = 512 * 1024 * 1024
_FRAME = 1_048_576
_SEND = 4_194_304
_FIXED_ENV = {"SystemRoot", "WINDIR", "TEMP", "TMP", "PATH"}


class Child(Protocol):
    def start(self, executable: Path, args: tuple[str, ...], cwd: Path, env: dict[str, str], deadline: float) -> None: ...
    def read(self, size: int, deadline: float) -> bytes | None: ...
    def write(self, data: bytes, deadline: float) -> int: ...
    def terminate(self) -> None: ...
    def witnesses(self, deadline: float) -> tuple[bool, bool]: ...
    def close(self, deadline: float) -> None: ...


class WindowsSession:
    """One contiguous JSONL reader; clean shutdown needs both exact retained witnesses."""

    def __init__(
        self, child: Child, cutoff: float, clock: Callable[[], float] = monotonic, *,
        operation_cutoff: float | None = None,
    ) -> None:
        self._child, self._cutoff, self._clock = child, cutoff, clock
        self._operation_cutoff = cutoff if operation_cutoff is None else min(cutoff, operation_cutoff)
        self._buffer = bytearray()
        self._closed = False
        self._eof = False

    def _bound(self, deadline: float) -> float:
        end = min(deadline, self._cutoff)
        if self._closed or not math.isfinite(end) or self._clock() >= end:
            raise TimeoutError("review pipe deadline elapsed")
        return end

    def write(self, data: bytes, deadline: float) -> None:
        if not 0 < len(data) <= _SEND or not data.endswith(b"\n") or b"\n" in data[:-1]:
            raise OSError("invalid review write")
        deadline = min(deadline, self._operation_cutoff)
        offset = 0
        while offset < len(data):
            block = data[offset:offset + 65536]
            count = self._child.write(block, self._bound(deadline))
            if type(count) is not int or not 0 < count <= len(block):
                raise OSError("incomplete review write")
            offset += count
        self._bound(deadline)

    def read(self, max_bytes: int, deadline: float) -> bytes | None:
        return self._read(max_bytes, min(deadline, self._operation_cutoff))

    def _read(self, max_bytes: int, deadline: float) -> bytes | None:
        if not 0 < max_bytes <= _FRAME:
            raise OSError("invalid review read bound")
        while True:
            end = self._bound(deadline)
            if (index := self._buffer.find(b"\n")) >= 0:
                if index + 1 > max_bytes:
                    raise OSError("review frame over limit")
                result = bytes(self._buffer[:index + 1])
                del self._buffer[:index + 1]
                return result
            if self._eof:
                if self._buffer:
                    raise OSError("truncated final review frame")
                return None
            capacity = min(65536, max_bytes - len(self._buffer))
            if capacity <= 0:
                raise OSError("review frame over limit")
            chunk = self._child.read(capacity, end)
            self._bound(deadline)
            if chunk is None:
                self._eof = True
            elif not 0 < len(chunk) <= capacity:
                raise OSError("invalid review pipe result")
            else:
                self._buffer.extend(chunk)

    def shutdown(self, deadline: float) -> Shutdown:
        """Terminate only the original owner; drain complete buffered frames before the cutoff."""
        if self._closed:
            return Shutdown(False, False)
        end = min(deadline, self._cutoff)
        result = Shutdown(False, False)
        try:
            self._child.terminate()  # Always request cleanup, even if the budget is spent.
            root, empty = self._child.witnesses(end)
            if root is True and empty is True:
                frames: list[bytes] = []
                size = 0
                while (frame := self._read(_FRAME, end)) is not None:
                    size += len(frame)
                    if len(frames) >= 16 or size > _FRAME:
                        raise OSError("unread review frames exceed cleanup budget")
                    frames.append(frame)
                self._bound(end)
                result = Shutdown(True, True, tuple(frames))
        except (ValueError, OSError):
            pass
        finally:
            self._closed = True
            try:
                self._child.close(end)
            except OSError:
                result = Shutdown(False, False)
        if self._clock() >= end:
            return Shutdown(False, False)
        return result


@dataclass(frozen=True, repr=False)
class PrivateWindowsReview:
    """Owner-selected fixed paths and minimal allowlisted runtime environment."""

    repository: str
    workspace: Path
    executable: Path
    executable_sha256: str
    git: Path
    codex_home: Path
    environment: tuple[tuple[str, str], ...]
    runtime: str = RUNTIME

    def inputs(self) -> dict[str, str]:
        paths = (self.workspace, self.executable, self.git, self.codex_home)
        env = dict(self.environment)
        if (self.runtime != RUNTIME or not re.fullmatch(r"[0-9a-f]{64}", self.executable_sha256)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository)
                or any(not p.is_absolute() or p.drive.startswith("\\\\") for p in paths)
                or self.executable.suffix.lower() != ".exe" or self.git.name.lower() != "git.exe"
                or self.codex_home == self.workspace or self.codex_home.is_relative_to(self.workspace)
                or not {"SystemRoot", "TEMP"} <= env.keys() <= _FIXED_ENV
                or len(env) != len(self.environment)
                or any(not value or "\0" in value for value in env.values())):
            raise OSError("private Windows review binding unavailable")
        return {**env, "CODEX_HOME": str(self.codex_home)}


class WindowsReviewOwner:
    """Open only the selected pinned App Server in the independently verified checkout."""

    def __init__(self, settings: PrivateWindowsReview, *, child: Callable[[], Child] = WinChild) -> None:
        self._settings, self._child = settings, child
        self._settings.inputs()

    def checkout_matches(self, request: ReviewRequest, deadline: float) -> bool:
        s = self._settings
        if (
            request.repository != s.repository or request.workspace != s.workspace
            or not re.fullmatch(r"[0-9a-f]{40}", request.head)
        ):
            return False

        def git(*args: str) -> str:
            left = deadline - monotonic()
            if left <= 0:
                raise TimeoutError
            result = subprocess.run(
                [str(s.git), "--no-optional-locks", "-c", "core.fsmonitor=false",
                 "-c", "core.untrackedCache=false", *args], cwd=s.workspace, capture_output=True,
                check=True, timeout=min(left, 2),
                env={k: v for k, v in s.inputs().items() if k != "CODEX_HOME"}
                | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "NUL"},
                creationflags=0x08000000,
            )
            if len(result.stdout) > 4096 or monotonic() >= deadline:
                raise OSError
            return result.stdout.decode("utf-8").strip()

        try:
            origin = f"https://github.com/{s.repository}"
            return (
                Path(git("rev-parse", "--show-toplevel")).resolve(strict=True) == s.workspace.resolve(strict=True)
                and git("config", "--local", "--get-all", "remote.origin.url") in {origin, origin + ".git"}
                and git("rev-parse", "--verify", "HEAD^{commit}") == request.head
                and git("status", "--porcelain=v1", "--untracked-files=normal") == ""
            )
        except (OSError, UnicodeError, subprocess.SubprocessError):
            return False

    def open(self, request: ReviewRequest, deadline: float, cleanup_deadline: float) -> WindowsSession:
        s = self._settings
        if (not math.isfinite(cleanup_deadline) or not monotonic() < deadline <= cleanup_deadline
                or not self.checkout_matches(request, deadline)):
            raise OSError("exact Windows checkout not verified")
        try:
            if not s.codex_home.is_dir() or s.executable.resolve(strict=True) != s.executable:
                raise OSError
            digest = sha256()
            total = 0
            with s.executable.open("rb") as file:
                while block := file.read(1_048_576):
                    total += len(block)
                    if total > MAX_RUNTIME_ARTIFACT_BYTES or monotonic() >= deadline:
                        raise TimeoutError
                    digest.update(block)
            if digest.hexdigest() != s.executable_sha256:
                raise OSError
        except OSError:
            raise OSError("selected Windows runtime not verified") from None
        child = self._child()
        session = WindowsSession(child, cleanup_deadline, operation_cutoff=deadline)
        try:
            child.start(s.executable, ("app-server", "--listen", "stdio://"), s.workspace, s.inputs(), deadline)
        except Exception:
            session.shutdown(cleanup_deadline)
            raise OSError("owned Windows startup not confirmed") from None
        return session
