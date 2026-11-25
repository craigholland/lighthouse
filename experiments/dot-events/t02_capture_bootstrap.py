"""Exact private capability descriptor for a fixed inherited Windows peer."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_event_types import Hold, decode, encode

ENVIRONMENT_KEY = "LIGHTHOUSE_T02_CAPTURE_BOOTSTRAP"
_MAX_DESCRIPTOR = 512


@dataclass(frozen=True, repr=False)
class InheritedCapture:
    """Only controller-owned capabilities and the approved operation projection."""

    peer: PeerBinding
    head: str
    packet_digest: str

    def verifies_packet_window(
        self, packet: CapturePacket, mono: Callable[[], int], wall: Callable[[], int],
    ) -> bool:
        """Bound inherited deadlines by the child's conservative wall/monotonic sample."""
        tick = mono()
        time = wall()
        target = packet.approval
        return (
            self.head == target.head and self.packet_digest == target.digest
            and target.activation_ms <= time < packet.intake_cutoff_ms
            and tick < self.peer.intake_ms <= tick + packet.intake_cutoff_ms - time
            and self.peer.intake_ms < self.peer.cleanup_ms <= tick + target.cutoff_ms - time
            and mono() < self.peer.intake_ms
        )

    def approval_deadline(self, packet: CapturePacket, mono: Callable[[], int], wall: Callable[[], int]) -> int:
        """Keep provider I/O inside both original intake time domains."""
        current_wall = wall()
        return min(packet.intake_cutoff_ms, current_wall + max(0, self.peer.intake_ms - mono()))

    def to_environment(self) -> dict[str, str]:
        """Export no file paths, credentials, role selection or executable names."""
        return {ENVIRONMENT_KEY: encode({
            "version": 1, "handles": self.peer.handles, "correlation": self.peer.correlation,
            "intake": self.peer.intake_ms, "cleanup": self.peer.cleanup_ms,
            "head": self.head, "digest": self.packet_digest,
        }).decode("ascii")}

    @classmethod
    def accept(
        cls, raw: str, clock: Callable[[], int],
        owns_pipe: Callable[[int], bool], owns_stop: Callable[[int], bool],
    ) -> InheritedCapture:
        """Fail closed unless the descriptor refers to exact inherited capabilities."""
        if len(raw) > _MAX_DESCRIPTOR or not raw.isascii():
            raise Hold("capture bootstrap descriptor held")
        data = decode(raw.encode("ascii"), _MAX_DESCRIPTOR)
        if (data.keys() != {"version", "handles", "correlation", "intake", "cleanup", "head", "digest"}
            or type(data["version"]) is not int or data["version"] != 1):
            raise Hold("capture bootstrap schema held")
        handles, intake, cleanup = data["handles"], data["intake"], data["cleanup"]
        correlation, head, digest = data["correlation"], data["head"], data["digest"]
        if (not isinstance(handles, list) or len(handles) != 3
            or any(type(item) is not int or not 0 < item < 2**63 for item in handles)
            or len(set(handles)) != 3 or type(intake) is not int or type(cleanup) is not int
            or not clock() < intake < cleanup <= clock() + 900_000
            or not isinstance(correlation, str) or not re.fullmatch(r"[a-f0-9]{64}", correlation)
            or not isinstance(head, str) or not re.fullmatch(r"[a-f0-9]{40}", head)
            or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise Hold("capture bootstrap binding held")
        read, write, stop = handles
        if not owns_pipe(read) or not owns_pipe(write) or not owns_stop(stop) or clock() >= intake:
            raise Hold("capture bootstrap capability unavailable")
        return cls(PeerBinding((read, write, stop), correlation, intake, cleanup), head, digest)
