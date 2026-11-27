"""Dormant stdlib HTTPS adapters for the worker-free probe; no import-time I/O."""

from __future__ import annotations

import http.client
import io
import ipaddress
import re
import socket
import ssl
from collections.abc import Buffer, Callable, Mapping
from typing import BinaryIO

from t02_event_dns import resolve
from t02_event_evidence import API_ROOT, MAX_PROVIDER_BYTES, ProviderReply
from t02_event_types import HOST, MAX_BODY, MAX_RESPONSE, Hold, Reply

_API = "api.github.com"
_PATH = re.compile(re.escape(API_ROOT) + r"/(?:issues/5|pulls/15|issues/comments/[1-9][0-9]{0,18})")


def remaining(clock: Callable[[], int], deadline: int) -> float:
    value = deadline - clock()
    if value <= 0:
        raise Hold("HTTP deadline closed")
    return value / 1000


class _DeadlineRaw(io.RawIOBase):
    """Give the stdlib HTTP parser absolute bounds on every raw read."""

    def __init__(
        self, sock: socket.socket, clock: Callable[[], int], deadline: int, lifetime: BinaryIO,
    ) -> None:
        self._sock = sock
        self._lifetime = lifetime
        self._clock = clock
        self._deadline = deadline

    def close(self) -> None:
        self._lifetime.close()
        super().close()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        self._sock.settimeout(remaining(self._clock, self._deadline))
        count = self._sock.recv_into(buffer)
        remaining(self._clock, self._deadline)
        return count


def _numeric(ip: str, port: int, clock: Callable[[], int], deadline: int) -> socket.socket:
    address = ipaddress.ip_address(ip)
    if (
        not address.is_global or address.is_multicast or address.is_reserved
        or (isinstance(address, ipaddress.IPv6Address) and (address.ipv4_mapped or address.scope_id))
    ):
        raise Hold("HTTPS address not public")
    raw = socket.socket(socket.AF_INET if address.version == 4 else socket.AF_INET6, socket.SOCK_STREAM)
    try:
        raw.settimeout(remaining(clock, deadline))
        raw.connect((ip, port) if address.version == 4 else (ip, port, 0, 0))
        raw.settimeout(remaining(clock, deadline))
        return raw
    except BaseException:
        raw.close()
        raise


def _bounded(
    connection: http.client.HTTPConnection, *, clock: Callable[[], int], deadline: int, limit: int,
) -> Reply:
    sock = connection.sock
    if sock is None:
        raise Hold("HTTP connection not established")
    sock.settimeout(remaining(clock, deadline))
    class DeadlineResponse(http.client.HTTPResponse):
        def __init__(self, transport: socket.socket, *args: object, method: str | None = None) -> None:
            # HTTPResponse's only socket operation during construction is
            # makefile; take ownership of this adapter-owned read buffer.
            super().__init__(transport, method=method)
            assert self.fp is not None
            self.fp = io.BufferedReader(_DeadlineRaw(transport, clock, deadline, self.fp))

    connection.response_class = DeadlineResponse
    with connection.getresponse() as response:
        if 300 <= response.status < 400:
            raise Hold("HTTP redirects are disabled")
        chunks = bytearray()
        while True:
            sock.settimeout(remaining(clock, deadline))
            block = response.read1(min(1024, limit + 1 - len(chunks)))
            chunks.extend(block)
            if len(chunks) > limit:
                raise Hold("HTTP response exceeded bound")
            if not block:
                remaining(clock, deadline)
                return Reply(response.status, bytes(chunks))


class GitHubHttps:
    """Fixed public, credentialless GitHub GETs with verified TLS and no redirects."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock

    def read(self, path: str, *, deadline_ms: int, limit: int) -> ProviderReply:
        if not _PATH.fullmatch(path) or not 0 < limit <= MAX_PROVIDER_BYTES:
            raise Hold("GitHub request outside the probe scope")
        connection = http.client.HTTPSConnection(
            _API, 443, context=ssl.create_default_context(),
            timeout=remaining(self._clock, deadline_ms),
        )
        try:
            def connect_numeric(
                endpoint: tuple[str, int], timeout: object, address: object,
            ) -> socket.socket:
                if endpoint != (_API, 443) or address is not None:
                    raise Hold("unexpected public HTTPS endpoint")
                answers = resolve(_API, deadline_ms, self._clock)
                if not answers:
                    raise Hold("public GitHub DNS unavailable")
                return _numeric(answers[0], 443, self._clock, deadline_ms)

            setattr(connection, "_create_connection", connect_numeric)
            connection.connect()
            if connection.sock is None:
                raise Hold("GitHub connection unavailable")
            connection.sock.settimeout(remaining(self._clock, deadline_ms))
            connection.request("GET", path, headers={
                "Accept": "application/vnd.github+json", "Connection": "close",
                "User-Agent": "Lighthouse-T02-probe",
            })
            result = _bounded(connection, clock=self._clock, deadline=deadline_ms, limit=limit)
            return ProviderReply(result.status, result.body)
        except (OSError, http.client.HTTPException, ValueError):
            raise Hold("public GitHub HTTPS unavailable") from None
        finally:
            connection.close()


class _PinnedConnection:
    """HTTP over an already connected numeric peer with verified hostname."""

    def __init__(
        self, connection: http.client.HTTPConnection, clock: Callable[[], int],
    ) -> None:
        self._connection = connection
        self._clock = clock

    def post(
        self, target: str, headers: Mapping[str, str], body: bytes, *, limit: int, deadline_ms: int,
    ) -> Reply:
        if (
            not re.fullmatch(r"/[a-zA-Z0-9/_-]{1,255}", target) or "//" in target
            or not 0 < limit <= MAX_RESPONSE or len(body) > MAX_BODY
            or any(name.lower() in {"host", "connection", "content-length", "transfer-encoding"}
                   for name in headers)
        ):
            raise Hold("invalid callback HTTP envelope")
        try:
            sock = self._connection.sock
            if sock is None:
                raise Hold("callback TLS connection unavailable")
            # http.client otherwise writes the headers and bytes in separate
            # sendall calls under one inactivity timeout. Treat each as an
            # independent write under the same absolute cutoff.
            conn = self._connection
            conn.putrequest("POST", target)
            for name, value in headers.items():
                conn.putheader(name, value)
            conn.putheader("Connection", "close")
            conn.putheader("Content-Length", str(len(body)))
            sock.settimeout(remaining(self._clock, deadline_ms))
            conn.endheaders()
            if body:
                sock.settimeout(remaining(self._clock, deadline_ms))
                conn.send(body)
            return _bounded(self._connection, clock=self._clock, deadline=deadline_ms, limit=limit)
        except (OSError, http.client.HTTPException, ValueError):
            raise Hold("callback HTTPS unavailable") from None

    def close(self) -> None:
        self._connection.close()


class CallbackSockets:
    """Resolve a bound hostname; TLS dials only the exact validated numeric IP."""

    def __init__(self, hostname: str, clock: Callable[[], int]) -> None:
        if not HOST.fullmatch(hostname):
            raise Hold("invalid callback host binding")
        self._hostname = hostname
        self._clock = clock

    def addresses(self, hostname: str, deadline_ms: int) -> tuple[str, ...]:
        if hostname != self._hostname:
            raise Hold("callback host mismatch")
        return resolve(hostname, deadline_ms, self._clock)

    def open_verified_tls(
        self, *, ip: str, port: int, hostname: str, deadline_ms: int,
    ) -> _PinnedConnection:
        if hostname != self._hostname or port != 443:
            raise Hold("callback TLS outside the binding")
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            raise Hold("invalid callback address") from None
        if (
            not address.is_global or address.is_multicast or address.is_reserved or str(address) != ip
            or (isinstance(address, ipaddress.IPv6Address) and (address.ipv4_mapped or address.scope_id))
        ):
            raise Hold("callback address not public or canonical")
        timeout = remaining(self._clock, deadline_ms)
        raw = socket.socket(socket.AF_INET if address.version == 4 else socket.AF_INET6, socket.SOCK_STREAM)
        tls: ssl.SSLSocket | None = None
        try:
            raw.settimeout(timeout)
            raw.connect((ip, port) if address.version == 4 else (ip, port, 0, 0))
            raw.settimeout(remaining(self._clock, deadline_ms))
            tls = ssl.create_default_context().wrap_socket(raw, server_hostname=hostname)
            remaining(self._clock, deadline_ms)
            connection = http.client.HTTPConnection(hostname, port)
            connection.auto_open = 0
            connection.sock = tls
            return _PinnedConnection(connection, self._clock)
        except (OSError, ValueError):
            raise Hold("callback TLS unavailable") from None
        finally:
            if tls is None:
                raw.close()
            elif self._clock() >= deadline_ms:
                tls.close()
