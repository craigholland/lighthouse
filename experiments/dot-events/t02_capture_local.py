"""Compare a capture packet with a typed local observation, without doing I/O."""

from dataclasses import dataclass

from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_event_types import decode


@dataclass(frozen=True, repr=False)
class LocalCaptureObservation:
    """Projections from a future fixed local checkout and artifact observer."""

    host: str
    repository: str
    checkout: str
    head: str
    tracked_clean: bool
    archive_sha256: str
    executable_sha256: str
    canonical_non_reparse_files: tuple[str, ...]


def matches_local_capture(packet: CapturePacket, observed: LocalCaptureObservation) -> bool:
    """Check facts, not a local boolean or a provider-supplied checkout path."""
    expected = decode(packet.canonical, MAX_PACKET_BYTES)
    files = tuple(expected[key] for key in (
        "runtime_archive", "runtime_executable", "platform_key", "loopback_bearer", "state",
    ))
    return (
        observed.host == expected["host"] and observed.repository == expected["repository"]
        and observed.checkout == expected["checkout"] and observed.head == packet.approval.head
        and observed.tracked_clean is True and observed.archive_sha256 == expected["runtime_archive_sha256"]
        and observed.executable_sha256 == expected["runtime_executable_sha256"]
        and observed.canonical_non_reparse_files == files
    )
