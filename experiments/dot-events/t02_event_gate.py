"""Exact packet authorization and bounded source/runtime lifecycle.

No provider credentials, process launcher or native adapter are supplied by this
offline slice. A later reviewed trusted boundary must supply those ports.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import astuple, dataclass
from typing import Protocol

from t02_event_types import VERSION, Hold, encode

OWNER = 12838844
LEAD = 359712317
LEAD_APP = 5869282
REPOSITORY = "craigholland/lighthouse"
SCOPE = "lighthouse-t02-worker-free-eligibility"
RUNTIME = "tunnel-client-runtime/v0.0.21/windows-amd64"
ARCHIVE_SHA256 = "d991623bd171049e2100b402d72af7ebc8edf558051ae8fc924173373d1611a8"


@dataclass(frozen=True)
class Packet:
    """Non-secret exact live binding; a proposal or caller boolean is no authority."""

    head: str
    workspace: str
    dot: str
    platform: str
    tunnel: str
    private_binding_digest: str
    runtime_binary_digest: str
    host: str
    activation_ms: int

    @property
    def digest(self) -> str:
        return hashlib.sha256(encode((
            REPOSITORY, SCOPE, VERSION, RUNTIME, ARCHIVE_SHA256, astuple(self),
        ))).hexdigest()


@dataclass(frozen=True)
class Evidence:
    """Evidence parsed by a trusted provider adapter, never by configuration."""

    repository: str
    issue: int
    pull_request: int
    actor: int
    app: int | None
    scope: str
    head: str
    digest: str
    not_before: int
    expires: int


@dataclass(frozen=True)
class Authority:
    head: str
    owner: Evidence
    lead: Evidence


class TrustedEvidence(Protocol):
    """Current provider evidence only; independent of local request/config data."""

    def current(self) -> Authority | None: ...


class Lifecycle(Protocol):
    """Fixed roles only. Adapter owns bounded waits and confirmed quiescence."""

    def verify_private_binding(self, packet: Packet, deadline_ms: int) -> bool: ...

    def verify_pinned_binary(self, packet: Packet, deadline_ms: int) -> bool: ...

    def start_source(self, packet: Packet, deadline_ms: int) -> bool: ...

    def start_runtime(self, packet: Packet, deadline_ms: int) -> bool: ...

    def measure_probe_window(self, deadline_ms: int) -> None: ...

    def confirm_runtime_stopped(self, deadline_ms: int) -> bool: ...

    def confirm_source_stopped(self, deadline_ms: int) -> bool: ...


class ProbeGate:
    """Verify all prerequisites before constructing any effect-side dependency."""

    def __init__(self, evidence: TrustedEvidence, clock: Callable[[], int]) -> None:
        self._evidence = evidence
        self._clock = clock

    def _authorizes(self, packet: Packet) -> bool:
        now = self._clock()
        if (
            not all(isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value))
                    for value in (packet.workspace, packet.dot, packet.platform, packet.tunnel, packet.host))
            or not re.fullmatch(r"[0-9a-f]{40}", packet.head)
            or not re.fullmatch(r"[0-9a-f]{64}", packet.private_binding_digest)
            or not re.fullmatch(r"[0-9a-f]{64}", packet.runtime_binary_digest)
            or type(packet.activation_ms) is not int or not packet.activation_ms <= now < packet.activation_ms + 600_000
        ):
            return False
        current = self._evidence.current()
        now = self._clock()  # The provider call may consume the remaining authorization window.
        if current is None or current.head != packet.head or not self._active(packet, now):
            return False
        for observed, actor, app in ((current.owner, OWNER, None), (current.lead, LEAD, LEAD_APP)):
            if (
                observed.repository != REPOSITORY or type(observed.actor) is not int
                or observed.issue != 5 or observed.pull_request != 15
                or observed.actor != actor or observed.app != app or observed.scope != SCOPE
                or observed.head != packet.head or observed.digest != packet.digest
                or not observed.not_before <= now < packet.activation_ms + 900_000 <= observed.expires
            ):
                return False
        return True

    @staticmethod
    def _active(packet: Packet, now: int) -> bool:
        return packet.activation_ms <= now < packet.activation_ms + 600_000

    def run(self, packet: Packet, construct: Callable[[], Lifecycle]) -> str:
        """Return evidence limited to operation/cleanup; never infer Dot receipt."""
        try:
            if not self._authorizes(packet) or not self._active(packet, self._clock()):
                return "held: exact approval unavailable"
        except (OSError, ValueError, TypeError, Hold):
            return "held: authority unavailable"
        total_stop = packet.activation_ms + 900_000
        active_stop = packet.activation_ms + 600_000
        active = False
        attempted_source = attempted_runtime = False
        source_down = runtime_down = True
        try:
            adapter = construct()
            if self._clock() >= active_stop or adapter.verify_private_binding(packet, active_stop) is not True:
                return "held: private source binding unverified"
            if self._clock() >= active_stop or adapter.verify_pinned_binary(packet, active_stop) is not True:
                return "held: candidate identity unverified"
            if not self._authorizes(packet) or not self._active(packet, self._clock()):
                return "held: approval unavailable before setup"
            attempted_source = True
            if adapter.start_source(packet, active_stop) is True and self._clock() < active_stop:
                if self._authorizes(packet) and self._active(packet, self._clock()):
                    attempted_runtime = True
                    if adapter.start_runtime(packet, active_stop) is True and self._clock() < active_stop:
                        if self._authorizes(packet) and self._active(packet, self._clock()):
                            adapter.measure_probe_window(active_stop)
                            active = self._clock() <= active_stop
        except (OSError, ValueError, TypeError, Hold):
            active = False
        finally:
            if attempted_source:
                try:
                    source_down = adapter.confirm_source_stopped(total_stop) is True
                except (OSError, ValueError, TypeError, Hold):
                    source_down = False
            if attempted_runtime:
                try:
                    runtime_down = adapter.confirm_runtime_stopped(total_stop) is True
                except (OSError, ValueError, TypeError, Hold):
                    runtime_down = False
        if not source_down or not runtime_down or self._clock() > total_stop:
            return "held: shutdown not confirmed within the original deadline"
        return "bounded source window observed; Dot receipt unverified" if active else "held: incomplete source window"
