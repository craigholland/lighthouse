"""Provision privately owned overlapped capture channels, dormant by default."""

from __future__ import annotations

import ctypes as c
import importlib
import secrets
from collections.abc import Callable
from ctypes import wintypes as w
from dataclasses import dataclass
from typing import Protocol, cast

from t02_event_types import Hold


class _Connect(Protocol):
    def GetOverlappedResult(self, wait: bool) -> tuple[int, int]: ...


class _ChannelApi(Protocol):
    def CreateNamedPipe(self, name: str, mode: int, flags: int, instances: int,
                        output: int, input: int, timeout: int, security: int) -> int: ...
    def CreateFile(self, name: str, access: int, share: int, security: int, create: int,
                   mode: int, template: int) -> int: ...
    def ConnectNamedPipe(self, handle: int, overlapped: bool) -> _Connect: ...
    def GetCurrentProcess(self) -> int: ...
    def DuplicateHandle(self, source: int, handle: int, target: int, access: int,
                        inherit: bool, options: int) -> int: ...
    def CloseHandle(self, handle: int) -> None: ...


def _event() -> int:
    kernel = c.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateEventW
    create.argtypes = (c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR)
    create.restype = w.HANDLE
    handle = create(None, True, False, None)
    if not handle:
        raise Hold("capture stop event unavailable")
    return int(handle)


@dataclass(frozen=True, repr=False)
class CapturePipeHandles:
    """The child endpoints are passed only in the explicit inheritance list."""

    controller: tuple[int, int, int]
    supervisor: tuple[int, int, int]


class CapturePipeOwner:
    """Own all provisioned handles; does not expose pipe addresses or credentials."""

    def __init__(
        self, clock: Callable[[], int], *, api: _ChannelApi | None = None,
        make_event: Callable[[], int] = _event,
        nonce: Callable[[], str] = lambda: secrets.token_hex(24),
    ) -> None:
        self._clock = clock
        self._api = api if api is not None else cast(_ChannelApi, importlib.import_module("_winapi"))
        self._make_event = make_event
        self._nonce = nonce
        self._attempted = False
        self._handles: set[int] = set()
        self._child_copies: set[int] = set()
        self._quarantine: list[_Connect] = []

    def _retain(self, handle: int) -> int:
        if handle <= 0 or handle in self._handles:
            raise Hold("capture channel ownership unknown")
        self._handles.add(handle)
        return handle

    def _pair(self, deadline: int) -> tuple[int, int]:
        if self._clock() >= deadline:
            raise Hold("capture channel provision expired")
        nonce = self._nonce()
        if len(nonce) != 48 or any(digit not in "0123456789abcdef" for digit in nonce):
            raise Hold("capture pipe entropy unavailable")
        address = r"\\.\pipe\lighthouse-t02-private-" + nonce
        # One instance, inbound, byte-mode, overlapped, reject remote clients.
        server = self._retain(self._api.CreateNamedPipe(address, 0x40080001, 8, 1, 0, 2048, 10, 0))
        if self._clock() >= deadline:
            raise Hold("capture channel provision expired")
        client = self._retain(self._api.CreateFile(address, 0x40000000, 0, 0, 3, 0x40000000, 0))
        # The sole client is already attached; nonblocking confirmation only.
        result = self._api.ConnectNamedPipe(server, True)
        self._quarantine.append(result)
        if result.GetOverlappedResult(False)[1] != 0 or self._clock() >= deadline:
            raise Hold("capture channel connection unknown")
        self._quarantine.remove(result)
        return server, client

    def prepare(self, deadline: int) -> CapturePipeHandles:
        """Provision once; cancellation or an ambiguous setup never retries."""
        if self._attempted or self._clock() >= deadline:
            raise Hold("capture pipe preparation held")
        self._attempted = True
        try:
            controller_read, supervisor_write = self._pair(deadline)
            supervisor_read, controller_write = self._pair(deadline)
            stop = self._retain(self._make_event())
            process = self._api.GetCurrentProcess()
            inherited = []
            for handle in (supervisor_read, supervisor_write, stop):
                if self._clock() >= deadline:
                    raise Hold("capture channel duplication expired")
                inherited.append(self._retain(self._api.DuplicateHandle(process, handle, process, 0, True, 2)))
            if self._clock() >= deadline:
                raise Hold("capture channel duplication expired")
            self._child_copies = {supervisor_read, supervisor_write, *inherited}
            return CapturePipeHandles((controller_read, controller_write, stop),
                                      (inherited[0], inherited[1], inherited[2]))
        except (Hold, OSError):
            self.close()
            raise Hold("capture private channel setup held") from None

    def release_supervisor_copies(self) -> None:
        """After the exact spawn attempt, close all parent copies of child endpoints."""
        handles, self._child_copies = self._child_copies, set()
        for handle in handles:
            if handle in self._handles:
                self._api.CloseHandle(handle)
                self._handles.remove(handle)

    def close(self) -> None:
        """Close owned copies only; unknown overlapped storage is not reusable."""
        handles, self._handles = self._handles, set()
        self._child_copies.clear()
        for handle in handles:
            try:
                self._api.CloseHandle(handle)
            except OSError:
                # Closing cannot serve as cleanup proof; no retry or replacement.
                pass
