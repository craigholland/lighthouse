"""Shared narrow types for the worker-free private Events source."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

VERSION = "2025-11-25"
EVENT = "lighthouse.t02.probe"
MARKER = "lighthouse-t02-coordinator-receipt"
MAX_BODY = 4096
MAX_RESPONSE = 1024
WINDOW_MS = 900_000
SEND_MS = 600_000
HTTP_MS = 5_000
TOKEN = re.compile(r"[a-zA-Z0-9_-]{12,128}\Z")
HOST = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}\Z")


class Hold(Exception):
    """Sanitized fail-closed result; never include inputs in exceptions."""


def encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def decode(body: bytes, limit: int = MAX_BODY) -> dict[str, object]:
    """Accept a bounded strict object, with no duplicate fields or nonfinite values."""
    def pairs(entries: list[tuple[str, object]]) -> dict[str, object]:
        if len(dict(entries)) != len(entries):
            raise Hold("duplicate fields")
        return dict(entries)

    def reject(_: str) -> object:
        raise Hold("nonfinite JSON")

    if len(body) > limit:
        raise Hold("body too large")
    try:
        result: object = json.loads(
            body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise Hold("invalid JSON") from None
    if not isinstance(result, dict):
        raise Hold("expected JSON object")
    return result


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Binding:
    """Private proof configuration; callback hostname/path cannot vary."""

    proof_id: str
    principal: str
    callback_host: str
    callback_path: str
    activation_ms: int

    def __post_init__(self) -> None:
        if (
            not TOKEN.fullmatch(self.proof_id) or not TOKEN.fullmatch(self.principal)
            or not HOST.fullmatch(self.callback_host)
            or not re.fullmatch(r"/[a-zA-Z0-9/_-]{1,255}", self.callback_path)
            or "//" in self.callback_path
            or type(self.activation_ms) is not int or not 0 < self.activation_ms <= 4_102_444_800_000
        ):
            raise Hold("invalid private binding")

    @property
    def deadline(self) -> int:
        return self.activation_ms + WINDOW_MS

    @property
    def send_until(self) -> int:
        return self.activation_ms + SEND_MS


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes


@dataclass(frozen=True)
class Request:
    """Only the pinned IP is dialed; preserve TLS SNI and validated host."""

    ip: str
    tls_hostname: str
    target: str
    headers: Mapping[str, str]
    body: bytes
    deadline_ms: int
    response_limit: int = MAX_RESPONSE


class Network(Protocol):
    """Adapter MUST use exact IP, trusted TLS hostname, deadlines and no redirects."""

    def resolve(self, hostname: str, deadline_ms: int) -> tuple[str, ...]: ...

    def post(self, request: Request) -> Reply: ...


def verified_secret(value: object) -> bytes:
    if not isinstance(value, str) or not value.startswith("whsec_") or len(value) > 100:
        raise Hold("invalid signing secret")
    try:
        key = base64.b64decode(value[6:], validate=True)
    except (ValueError, binascii.Error):
        raise Hold("invalid signing secret") from None
    if not 24 <= len(key) <= 64 or base64.b64encode(key).decode() != value[6:]:
        raise Hold("invalid signing secret")
    return key


def fixed_url(binding: Binding, value: object) -> str:
    expected = "https://" + binding.callback_host + binding.callback_path
    if not isinstance(value, str) or value != expected:
        raise Hold("callback does not match the private binding")
    return expected


class Callback:
    """Validates every DNS observation and signs the exact transmitted bytes."""

    def __init__(self, network: Network, clock: Callable[[], int]) -> None:
        self._network = network
        self._clock = clock

    def send(
        self, binding: Binding, url: str, secret: str, subscription: str,
        message_id: str, body: bytes, until: int,
    ) -> Reply:
        fixed_url(binding, url)
        if not TOKEN.fullmatch(message_id) or not TOKEN.fullmatch(subscription) or len(body) > MAX_BODY:
            raise Hold("invalid callback frame")
        stop = min(self._clock() + HTTP_MS, until)
        if self._clock() >= stop:
            raise Hold("callback deadline expired")
        try:
            answers = self._network.resolve(binding.callback_host, stop)
            if not 1 <= len(answers) <= 8:
                raise Hold("invalid DNS answers")
            addresses = [ipaddress.ip_address(value) for value in answers]
            if any(
                not ip.is_global or ip.is_multicast or ip.is_reserved
                or (isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.scope_id))
                for ip in addresses
            ):
                raise Hold("nonpublic DNS answers")
            if self._clock() >= stop:
                raise Hold("callback deadline expired")
            timestamp = str(self._clock() // 1000)
            signed = f"{message_id}.{timestamp}.".encode("ascii") + body
            mac = hmac.digest(verified_secret(secret), signed, hashlib.sha256)
            reply = self._network.post(Request(
                str(addresses[0]), binding.callback_host, urlsplit(url).path,
                {"Content-Type": "application/json", "webhook-id": message_id,
                 "webhook-timestamp": timestamp,
                 "webhook-signature": "v1," + base64.b64encode(mac).decode("ascii"),
                 "X-MCP-Subscription-Id": subscription},
                body, stop,
            ))
        except (OSError, ValueError):
            raise Hold("callback transport uncertain") from None
        if self._clock() >= stop or len(reply.body) > MAX_RESPONSE:
            raise Hold("callback response outside bounds")
        if type(reply.status) is not int or not 100 <= reply.status <= 599 or 300 <= reply.status < 400:
            raise Hold("callback refused or redirected")
        return reply
