"""Native overlapped endpoint for two already-owned private pipe handles."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast

from t02_event_types import Hold

_MAX_TRANSFER = 1028
_PENDING = 997
_WAIT_OBJECT_0 = 0


class _PendingIo(Protocol):
    @property
    def event(self) -> int: ...
    def GetOverlappedResult(self, wait: bool) -> tuple[int, int]: ...
    def getbuffer(self) -> bytes: ...
    def cancel(self) -> None: ...


class _PipeApi(Protocol):
    def ReadFile(self, handle: int, length: int, overlapped: bool) -> tuple[_PendingIo, int]: ...
    def WriteFile(self, handle: int, data: bytes, overlapped: bool) -> tuple[_PendingIo, int]: ...
    def WaitForSingleObject(self, handle: int, timeout_ms: int) -> int: ...
    def SetEvent(self, handle: int) -> None: ...
    def WaitForMultipleObjects(self, handles: list[int], wait_all: bool, timeout_ms: int) -> int: ...


class WindowsCapturePipe:
    """Use owned overlapped handles only; do not discover or open a named target."""

    def __init__(
        self, read_handle: int, write_handle: int, stop_event: int, clock: Callable[[], int],
        *, api: _PipeApi | None = None, supervisor: bool = False,
        on_stop: Callable[[], None] | None = None, cleanup_deadline: int = 0,
    ) -> None:
        if min(read_handle, write_handle, stop_event) <= 0 or len({read_handle, write_handle, stop_event}) != 3:
            raise Hold("invalid private pipe capability")
        self._read = read_handle
        self._write = write_handle
        self._stop = stop_event
        self._clock = clock
        self._api = api if api is not None else cast(_PipeApi, importlib.import_module("_winapi"))
        self._held = False
        self._supervisor = supervisor
        self._stop_seen = False
        self._on_stop = on_stop
        self._cleanup_deadline = cleanup_deadline
        self._quarantine: _PendingIo | None = None

    def terminal_deadline(self, normal: int) -> int:
        return self._cleanup_deadline if self._stop_seen and self._on_stop is not None else normal

    def _begin(
        self, start: Callable[[], tuple[_PendingIo, int]], deadline: int,
    ) -> tuple[_PendingIo, int]:
        deadline = self.terminal_deadline(deadline)
        now = self._clock()
        if self._held or not 0 < deadline - now <= 900_000:
            raise Hold("capture native pipe held")
        operation: _PendingIo | None = None
        try:
            operation, result = start()
            if result not in (0, _PENDING):
                raise Hold("capture native pipe start unknown")
            if result == _PENDING:
                delay = deadline - self._clock()
                if delay <= 0:
                    raise Hold("capture native pipe wait expired")
                if self._supervisor and not self._stop_seen:
                    state = self._api.WaitForMultipleObjects([operation.event, self._stop], False, delay)
                    if state == 1:
                        self._stop_seen = True
                        if self._on_stop is not None:
                            self._on_stop()
                            # Retain the same overlapped read; restarting would
                            # lose already-read frame bytes or consume a replay.
                            deadline = self._cleanup_deadline
                            delay = deadline - self._clock()
                            if delay <= 0:
                                raise Hold("capture terminal receipt deadline")
                            state = self._api.WaitForSingleObject(operation.event, delay)
                else:
                    state = self._api.WaitForSingleObject(operation.event, delay)
                if state != _WAIT_OBJECT_0:
                    raise Hold("capture native pipe wait unknown")
            transferred, terminal = operation.GetOverlappedResult(False)
            if terminal or self._clock() >= deadline:
                raise Hold("capture native pipe result unknown")
            return operation, transferred
        except (Hold, OSError):
            self._held = True
            if operation is not None:
                # Cancellation request is not confirmation. Keep the operation
                # (and its native storage) alive until the enclosing owner exits.
                self._quarantine = operation
                try:
                    operation.cancel()
                except OSError:
                    pass
            raise Hold("capture native pipe held") from None

    def read(self, count: int, deadline_ms: int) -> bytes:
        if not 0 < count <= _MAX_TRANSFER:
            raise Hold("capture native read size held")
        op, transferred = self._begin(lambda: self._api.ReadFile(self._read, count, True), deadline_ms)
        data = op.getbuffer()
        if not 0 < transferred <= count or len(data) != transferred:
            self._held = True
            raise Hold("capture native read count unknown")
        return data

    def write(self, data: bytes, deadline_ms: int) -> None:
        if not 0 < len(data) <= _MAX_TRANSFER:
            raise Hold("capture native write size held")
        _, transferred = self._begin(lambda: self._api.WriteFile(self._write, data, True), deadline_ms)
        if transferred != len(data):
            self._held = True
            raise Hold("capture native write count unknown")

    def stopped(self) -> bool:
        """Sample the out-of-band stop event without waiting."""
        if not self._stop_seen:
            value = self._api.WaitForSingleObject(self._stop, 0)
            if value not in (0, 258):
                raise Hold("capture native stop witness unknown")
            self._stop_seen = value == 0
        return self._stop_seen

    def signal_stop(self) -> None:
        """Independent native event, including when pipe cancellation is unknown."""
        try:
            self._api.SetEvent(self._stop)
        except OSError:
            raise Hold("capture native stop signal unknown") from None
