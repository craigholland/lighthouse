"""Deadline-owned asynchronous WinSock DNS; no synchronous resolver fallback."""

from __future__ import annotations

import ctypes as c
import os
import socket
from collections.abc import Callable
from ctypes import wintypes as w
from threading import Lock

from t02_event_types import Hold

_PENDING = 997
_WAIT_TIMEOUT = 258
_P = c.c_void_p


class _Address(c.Structure):
    pass


_AddressPtr = c.POINTER(_Address)
_Address._fields_ = [
    ("flags", c.c_int), ("family", c.c_int), ("kind", c.c_int), ("protocol", c.c_int),
    ("size", c.c_size_t), ("canonical", _P), ("address", _P), ("blob", _P),
    ("blob_size", c.c_size_t), ("provider", _P), ("next", _AddressPtr),
]


class _Overlapped(c.Structure):
    _fields_ = [
        ("internal", c.c_size_t), ("internal_high", c.c_size_t), ("union", _P),
        ("event", w.HANDLE),
    ]


def _native() -> tuple[c.WinDLL, c.WinDLL]:
    if os.name != "nt":
        raise Hold("asynchronous Windows DNS required")
    k = c.WinDLL("kernel32", use_last_error=True)
    ws = c.WinDLL("Ws2_32", use_last_error=True)
    signatures = (
        (k, "CreateEventW", w.HANDLE, (_P, w.BOOL, w.BOOL, w.LPCWSTR)),
        (k, "WaitForSingleObject", w.DWORD, (w.HANDLE, w.DWORD)),
        (k, "CloseHandle", w.BOOL, (w.HANDLE,)),
        (ws, "GetAddrInfoExW", c.c_int, (
            w.LPCWSTR, w.LPCWSTR, w.DWORD, _P, c.POINTER(_Address),
            c.POINTER(_AddressPtr), _P, c.POINTER(_Overlapped), _P, c.POINTER(w.HANDLE),
        )),
        (ws, "GetAddrInfoExCancel", c.c_int, (c.POINTER(w.HANDLE),)),
        (ws, "GetAddrInfoExOverlappedResult", c.c_int, (c.POINTER(_Overlapped),)),
        (ws, "FreeAddrInfoExW", None, (_AddressPtr,)),
    )
    for module, name, returns, arguments in signatures:
        function = getattr(module, name)
        function.restype = returns
        function.argtypes = arguments
    return k, ws


class _Query:
    """Retain the ABI buffers and native event until acknowledged completion."""

    def __init__(self, hostname: str) -> None:
        self._k, self._ws = _native()
        self._name = c.create_unicode_buffer(hostname)
        self._service = c.create_unicode_buffer("443")
        self._hints = _Address()
        self._hints.kind = socket.SOCK_STREAM
        self._result = _AddressPtr()
        self._cancel = w.HANDLE()
        self._overlap = _Overlapped()
        self._overlap.event = self._k.CreateEventW(None, True, False, None)
        if not self._overlap.event:
            raise Hold("DNS owner event unavailable")

    def start(self) -> int:
        return int(self._ws.GetAddrInfoExW(
            self._name, self._service, 12, None, c.byref(self._hints), c.byref(self._result),
            None, c.byref(self._overlap), None, c.byref(self._cancel),
        ))  # NS_DNS, overlapped with event, no worker thread or child.

    def wait(self, milliseconds: int) -> bool:
        status = int(self._k.WaitForSingleObject(self._overlap.event, milliseconds))
        if status == _WAIT_TIMEOUT:
            return False
        if status != 0:
            raise Hold("DNS termination could not be observed")
        return True

    def status(self) -> int:
        return int(self._ws.GetAddrInfoExOverlappedResult(c.byref(self._overlap)))

    def cancel(self) -> None:
        self._ws.GetAddrInfoExCancel(c.byref(self._cancel))

    def answers(self) -> tuple[str, ...]:
        result: list[str] = []
        ptr = self._result
        for _ in range(16):
            if not ptr:
                if not result:
                    raise Hold("DNS returned no address")
                return tuple(dict.fromkeys(result))
            row = ptr.contents
            if row.family == socket.AF_INET and row.size == 16 and row.address:
                result.append(socket.inet_ntop(socket.AF_INET, c.string_at(row.address + 4, 4)))
            elif row.family == socket.AF_INET6 and row.size == 28 and row.address:
                if int.from_bytes(c.string_at(row.address + 24, 4), "little"):
                    raise Hold("scoped DNS answer not allowed")
                result.append(socket.inet_ntop(socket.AF_INET6, c.string_at(row.address + 8, 16)))
            else:
                raise Hold("unsupported DNS answer")
            ptr = row.next
        if ptr or not result:
            raise Hold("DNS answer count outside bound")
        return tuple(dict.fromkeys(result))

    def close(self) -> None:
        if self._result:
            self._ws.FreeAddrInfoExW(self._result)
        self._k.CloseHandle(self._overlap.event)


# Never free buffers for an unconfirmed operation. The fixed probe will not
# start another native lookup after such a loss of confirmation. This bounded
# quarantine is process-scoped so the owner survives failure of the caller.
_quarantined: _Query | None = None
_owner = Lock()


def resolve(hostname: str, deadline_ms: int, clock: Callable[[], int]) -> tuple[str, ...]:
    """Own and cancel at most one outstanding DNS request; never send after timeout."""
    global _quarantined
    if not _owner.acquire(blocking=False):
        raise Hold("DNS owner already busy")
    try:
        if _quarantined is not None:
            if _quarantined.wait(0):
                _quarantined.close()
                _quarantined = None
            raise Hold("previous DNS termination was not confirmed")
        left = deadline_ms - clock()
        if left <= 100:
            raise Hold("DNS deadline unavailable")
        query = _Query(hostname)
        finished = False
        try:
            status = query.start()
            if status == _PENDING:
                finished = query.wait(max(0, deadline_ms - clock() - 100))
                if finished:
                    status = query.status()
                else:
                    query.cancel()
                    finished = query.wait(max(0, deadline_ms - clock()))
                    if finished:
                        query.status()
                    raise Hold("DNS cancelled" if finished else "DNS termination unconfirmed")
            else:
                finished = True
            if status != 0 or clock() >= deadline_ms:
                raise Hold("DNS result unavailable inside deadline")
            return query.answers()
        finally:
            if finished:
                query.close()
            else:
                _quarantined = query
    finally:
        _owner.release()
