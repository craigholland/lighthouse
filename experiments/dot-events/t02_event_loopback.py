"""Dormant, single-request-at-a-time loopback listener for the T02 source."""

from __future__ import annotations

import re
import socket
from collections.abc import Callable
from contextlib import suppress
from threading import Event, Thread

from t02_event_assembly import LoopbackHttp
from t02_event_https import remaining
from t02_event_rpc import RpcResponse
from t02_event_types import MAX_BODY, Hold

_BIND = ("127.0.0.1", 8765)
_HEADER_LIMIT = 8192
_TOKEN = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def serve_one(
    conn: socket.socket, peer: str, handler: LoopbackHttp, clock: Callable[[], int], deadline: int,
) -> None:
    """Read one bounded request, never pipeline or accept transfer encodings."""
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        if len(buf) == _HEADER_LIMIT:
            return
        conn.settimeout(remaining(clock, deadline))
        data = conn.recv(min(1024, _HEADER_LIMIT - len(buf)))
        if not data:
            return
        buf.extend(data)
    raw, body = bytes(buf).split(b"\r\n\r\n", 1)
    first, *fields = raw.split(b"\r\n")
    parts = first.split(b" ")
    if len(parts) != 3 or parts[2] != b"HTTP/1.1" or len(fields) > 32:
        return
    method, target = (part.decode("ascii") for part in parts[:2])
    headers: dict[str, str] = {}
    for field in fields:
        key, delimiter, value = field.partition(b":")
        if not delimiter or not _TOKEN.fullmatch(key) or any(c < 32 or c > 126 for c in value):
            return
        name = key.decode("ascii").lower()
        if name in headers:
            return
        headers[name] = value.decode("ascii").strip()
    size = headers.get("content-length", "0")
    if (
        "transfer-encoding" in headers or "expect" in headers
        or not re.fullmatch(r"[0-9]{1,4}", size) or int(size) > MAX_BODY or len(body) > int(size)
    ):
        return
    while len(body) < int(size):
        conn.settimeout(remaining(clock, deadline))
        data = conn.recv(int(size) - len(body))
        if not data:
            return
        body += data
    remaining(clock, deadline)
    reply = handler.respond(peer, method, target, headers, body) if peer == _BIND[0] else RpcResponse(403)
    conn.settimeout(remaining(clock, deadline))
    header = (
        f"HTTP/1.1 {reply.status} Lighthouse\r\n"
        f"Connection: close\r\nContent-Length: {len(reply.body)}\r\n"
        "Content-Type: application/json\r\n\r\n"
    ).encode("ascii")
    conn.sendall(header + reply.body)


class LoopbackRole:
    """Own just one fixed loopback socket and the handler thread."""

    def __init__(
        self, host: str, port: int, handler: LoopbackHttp, clock: Callable[[], int],
    ) -> None:
        if (host, port) != _BIND:
            raise Hold("loopback outside fixed binding")
        self._handler = handler
        self._clock = clock
        self._stop = Event()
        self._listener: socket.socket | None = None
        self._thread: Thread | None = None
        self._restart_attempted = False

    def restart_once(self, deadline_ms: int) -> bool:
        """Replace only this listener after proving the original handler stopped."""
        if self._restart_attempted or self._listener is None:
            return False
        self._restart_attempted = True
        self.request_stop(deadline_ms)
        if not self.confirmed_quiescent(deadline_ms):
            return False
        self._listener = None
        self._thread = None
        self._stop = Event()
        return self.start(deadline_ms)

    def start(self, deadline_ms: int) -> bool:
        if self._listener is not None or self._stop.is_set():
            return False
        remaining(self._clock, deadline_ms)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener = listener
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(_BIND)
        listener.listen(1)
        listener.settimeout(0.1)
        remaining(self._clock, deadline_ms)
        thread = Thread(target=self._serve, args=(listener, deadline_ms), daemon=True)
        self._thread = thread
        thread.start()
        return thread.is_alive()

    def _serve(self, listener: socket.socket, deadline_ms: int) -> None:
        with listener:
            while not self._stop.is_set() and self._clock() < deadline_ms:
                try:
                    conn, peer = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with conn, suppress(OSError, Hold, UnicodeError):
                    if not self._stop.is_set():
                        serve_one(conn, peer[0], self._handler, self._clock,
                                  min(deadline_ms, self._clock() + 1000))

    def request_stop(self, deadline_ms: int) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()

    def confirmed_quiescent(self, deadline_ms: int) -> bool:
        thread = self._thread
        if thread is not None and thread.ident is not None and thread.is_alive():
            thread.join(remaining(self._clock, deadline_ms))
        return (
            self._stop.is_set() and (thread is None or not thread.is_alive())
            and (self._listener is None or self._listener.fileno() == -1)
            and self._clock() <= deadline_ms
        )
