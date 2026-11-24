"""Bounded, single-reader JSONL wire for the one managed App Server child."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from json import dumps, loads
from subprocess import TimeoutExpired
from threading import Condition, Event, Lock, Thread
from time import monotonic
from typing import IO, Protocol

from pydantic import BaseModel

FRAME_BYTES = 1_048_576
REQUEST_BYTES = 4_194_304
EVENT_BYTES = 262_144
EVENT_COUNT = 16
_PERMISSION_REPLIES: dict[str, dict[str, object]] = {
    "item/commandExecution/requestApproval": {"decision": "decline"},
    "item/fileChange/requestApproval": {"decision": "decline"},
    "item/permissions/requestApproval": {"permissions": {}, "scope": "turn"},
    "item/tool/requestUserInput": {"answers": {}},
    "execCommandApproval": {"decision": "denied"},
    "applyPatchApproval": {"decision": "denied"},
}


class Fault(StrEnum):
    """Fixed transport failures; never contain provider data."""

    FRAME = "frame_invalid"
    OVERFLOW = "buffer_overflow"
    TRANSPORT = "transport_lost"
    SERVER = "server_error"
    PERMISSION = "permission_requested"
    INTERRUPTED = "interrupted"
    TIMEOUT = "deadline_elapsed"
    ACK = "ack_invalid"
    THREAD = "thread_id_mismatch"
    TURN = "turn_id_mismatch"
    TERMINAL = "terminal_conflict"
    OUTPUT = "output_failed"


class ProtocolHold(RuntimeError):
    """Fail closed without revealing wire content or inferring cancellation."""

    def __init__(self, fault: Fault) -> None:
        super().__init__("Managed App Server protocol held.")
        self.fault = fault


class Child(Protocol):
    """Owned subprocess and the two injected wire streams."""

    @property
    def stdin(self) -> IO[bytes] | None: ...

    @property
    def stdout(self) -> IO[bytes] | None: ...

    def wait(self, timeout: float) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise ValueError("Non-finite JSON value.")


@dataclass(frozen=True)
class Signal:
    """Minimal explicit lifecycle projection; no full provider messages retained."""

    thread: str
    turn: str
    kind: str
    value: str = field(repr=False)


class StdioWire:
    """One reader, bounded lifecycle capture and fixed fail-closed routing."""

    def __init__(self, child: Child, attention: Callable[[], None], *,
                 clock: Callable[[], float] = monotonic, timeout: float = 900,
                 cancelled: Callable[[], bool] = lambda: False) -> None:
        if child.stdin is None or child.stdout is None:
            raise ProtocolHold(Fault.TRANSPORT)
        self._clock = clock
        self._cancelled = cancelled
        self._deadline = clock() + timeout
        self._child = child
        self._stdin, self._stdout = child.stdin, child.stdout
        self._attention = attention
        self._state = Condition()
        self._writer = Lock()
        self._permission = False
        self._closing = False
        self._eof = False
        self._fault: Fault | None = None
        self._next_id = 0
        self._pending: set[int] = set()
        self._responses: dict[int, object] = {}
        self._armed = False
        self._signals: list[Signal] = []
        self._signal_bytes = 0
        self._reader = Thread(target=self._read, daemon=True, name="lighthouse-stdio-reader")
        self._reader.start()

    def requested_permission(self) -> bool:
        with self._state:
            return self._permission

    def _hold(self, fault: Fault) -> None:
        with self._state:
            if self._fault is None:
                self._fault = fault
            self._state.notify_all()

    def _guard(self, stopped: Event | None = None, *, ignore_permission: bool = False) -> None:
        if self._permission and not ignore_permission:
            raise ProtocolHold(Fault.PERMISSION)
        if (stopped is not None and stopped.is_set()) or (
            not ignore_permission and self._cancelled()
        ):
            raise ProtocolHold(Fault.INTERRUPTED)
        if self._fault is not None:
            raise ProtocolHold(self._fault)
        if self._clock() >= self._deadline:
            raise ProtocolHold(Fault.TIMEOUT)

    def _write(self, message: dict[str, object]) -> None:
        try:
            data = (dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
            if len(data) > REQUEST_BYTES:
                raise ProtocolHold(Fault.OVERFLOW)
            with self._writer:
                view = memoryview(data)
                while view:
                    count = self._stdin.write(view)
                    if count is None or not 0 < count <= len(view):
                        raise OSError("Incomplete JSONL write.")
                    view = view[count:]
                self._stdin.flush()
        except ProtocolHold:
            raise
        except (OSError, ValueError, TypeError):
            self._hold(Fault.TRANSPORT)
            raise ProtocolHold(Fault.TRANSPORT) from None

    def request[T: BaseModel](
        self, method: str, parameters: dict[str, object], model: type[T], *,
        capture: bool = False, allow_interrupt: bool = False,
    ) -> T:
        with self._state:
            self._guard(ignore_permission=allow_interrupt)
            if self._closing or self._eof or len(self._pending) >= 2:
                raise ProtocolHold(Fault.TRANSPORT)
            if capture:
                if self._armed:
                    raise ProtocolHold(Fault.ACK)
                self._armed = True
            self._next_id += 1
            request_id = self._next_id
            self._pending.add(request_id)
        try:
            self._write({"id": request_id, "method": method, "params": parameters})
            with self._state:
                while request_id not in self._responses:
                    self._guard(ignore_permission=allow_interrupt)
                    if self._eof:
                        raise ProtocolHold(Fault.TRANSPORT)
                    self._state.wait(min(0.05, max(0, self._deadline - self._clock())))
                result = self._responses[request_id]
                if method != "review/start":
                    self._guard(ignore_permission=allow_interrupt)
            return model.model_validate(result)
        except ValueError:
            raise ProtocolHold(Fault.ACK if capture else Fault.FRAME) from None
        finally:
            with self._state:
                self._pending.discard(request_id)
                self._responses.pop(request_id, None)

    def initialized(self) -> None:
        self._write({"method": "initialized"})

    def snapshot(self, stopped: Event) -> tuple[Signal, ...]:
        """Return captured typed signals; only the caller binds them to the ack."""
        with self._state:
            self._guard(stopped)
            return tuple(self._signals)

    def wait_for_change(self, count: int, stopped: Event) -> None:
        with self._state:
            self._guard(stopped)
            if not self._eof and len(self._signals) == count:
                self._state.wait(0.05)
            self._guard(stopped)
            if self._eof and len(self._signals) == count:
                raise ProtocolHold(Fault.TRANSPORT)

    def close(self) -> None:
        """Bound the owned child shutdown and drain its sole reader to EOF."""
        with self._state:
            self._closing = True
        try:
            self._stdin.close()
            try:
                self._child.wait(timeout=0.5)
            except TimeoutExpired:
                self._child.terminate()
                try:
                    self._child.wait(timeout=1)
                except TimeoutExpired:
                    self._child.kill()
                    self._child.wait(timeout=1)
        finally:
            self._reader.join(timeout=0.5)
            if self._reader.is_alive():
                raise ProtocolHold(Fault.TRANSPORT)
            self._stdout.close()

    def _read(self) -> None:
        try:
            while True:
                frame = self._stdout.readline(FRAME_BYTES + 1)
                if not frame:
                    with self._state:
                        self._eof = True
                        if not self._closing and self._fault is None:
                            self._fault = Fault.TRANSPORT
                        self._state.notify_all()
                    return
                if len(frame) > FRAME_BYTES:
                    raise ProtocolHold(Fault.OVERFLOW)
                if not frame.endswith(b"\n"):
                    raise ProtocolHold(Fault.FRAME)
                message = loads(frame.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
                if not isinstance(message, dict):
                    raise ProtocolHold(Fault.FRAME)
                self._route(message, len(frame))
        except ProtocolHold as exc:
            self._hold(exc.fault)
        except (ValueError, RecursionError, TypeError):
            self._hold(Fault.FRAME)
        except OSError:
            self._hold(Fault.TRANSPORT)

    def _route(self, message: dict[str, object], frame_bytes: int) -> None:
        if "jsonrpc" in message and message["jsonrpc"] != "2.0":
            raise ProtocolHold(Fault.FRAME)
        method = message.get("method")
        params = message.get("params")
        if "method" in message:
            if ("result" in message or "error" in message or not isinstance(method, str)
                or ("params" in message and not isinstance(params, dict))):
                raise ProtocolHold(Fault.FRAME)
            if "id" in message:
                request_id = message["id"]
                if type(request_id) is not int and (
                    not isinstance(request_id, str) or not 0 < len(request_id) <= 128
                ):
                    raise ProtocolHold(Fault.FRAME)
                self._server_request(method, request_id)
            elif isinstance(params, dict):
                self._notification(method, params, frame_bytes)
            elif method in ("item/completed", "turn/completed", "error"):
                raise ProtocolHold(Fault.FRAME)
            return
        response_id = message.get("id")
        if type(response_id) is not int or ("result" in message) == ("error" in message):
            raise ProtocolHold(Fault.FRAME)
        with self._state:
            if response_id not in self._pending or response_id in self._responses:
                raise ProtocolHold(Fault.FRAME)
            if "error" in message:
                raise ProtocolHold(Fault.SERVER)
            self._responses[response_id] = message["result"]
            self._state.notify_all()

    def _server_request(self, method: str, request_id: object) -> None:
        # Unknown server requests never receive a useful permission or input grant.
        reply = _PERMISSION_REPLIES.get(method)
        with self._state:
            self._permission = True
        try:
            self._attention()
        except (OSError, RuntimeError):
            pass
        try:
            if reply is None:
                self._write({"id": request_id, "error": {"code": -32601, "message": "Request denied"}})
            else:
                self._write({"id": request_id, "result": reply})
        finally:
            with self._state:
                self._state.notify_all()

    def _notification(self, method: str, params: dict[str, object], frame_bytes: int) -> None:
        from openai_codex.generated.v2_all import (
            ItemCompletedNotification,
            TurnCompletedNotification,
        )

        with self._state:
            armed = self._armed
        if not armed or method not in ("item/completed", "turn/completed", "error"):
            return
        if method == "error":
            raise ProtocolHold(Fault.SERVER)
        if method == "item/completed":
            item = params.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ProtocolHold(Fault.FRAME)
            if item["type"] not in ("enteredReviewMode", "exitedReviewMode"):
                return
            event = ItemCompletedNotification.model_validate(params)
            value = event.item.root
            if value.type not in ("enteredReviewMode", "exitedReviewMode"):
                raise ProtocolHold(Fault.FRAME)
            signal = Signal(event.thread_id, event.turn_id, value.type,
                            value.review if value.type == "exitedReviewMode" else "")
        else:
            terminal = TurnCompletedNotification.model_validate(params)
            signal = Signal(terminal.thread_id, terminal.turn.id, "terminal",
                            "failed" if terminal.turn.error is not None else terminal.turn.status.value)
        with self._state:
            if len(self._signals) >= EVENT_COUNT or self._signal_bytes + frame_bytes > EVENT_BYTES:
                raise ProtocolHold(Fault.OVERFLOW)
            self._signals.append(signal)
            self._signal_bytes += frame_bytes
            self._state.notify_all()
