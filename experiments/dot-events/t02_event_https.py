"""Dormant stdlib HTTPS adapters for the worker-free probe; no import-time I/O."""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from collections.abc import Callable, Mapping

from t02_event_evidence import API_ROOT, MAX_PROVIDER_BYTES, ProviderReply
from t02_event_types import HOST, MAX_BODY, MAX_RESPONSE, Hold, Reply

_API = "api.github.com"
_PATH = re.compile(re.escape(API_ROOT) + r"/(?:issues/5|pulls/15|issues/comments/[1-9][0-9]{0,18})")


def remaining(clock: Callable[[], int], deadline: int) -> float:
    value = deadline - clock()
    if value <= 0:
        raise Hold("HTTP deadline closed")
    return value / 1000


def _bounded(
    connection: http.client.HTTPConnection, *, clock: Callable[[], int], deadline: int, limit: int,
) -> Reply:
    sock = connection.sock
    if sock is None:
        raise Hold("HTTP connection not established")
    sock.settimeout(remaining(clock, deadline))
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
            sock.settimeout(remaining(self._clock, deadline_ms))
            self._connection.request("POST", target, body, dict(headers) | {"Connection": "close"})
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
        remaining(self._clock, deadline_ms)
        try:
            answers = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise Hold("callback DNS unavailable") from None
        remaining(self._clock, deadline_ms)
        if not 0 < len(answers) <= 16:
            raise Hold("callback DNS answer count outside bound")
        return tuple(dict.fromkeys(str(row[4][0]) for row in answers))

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
