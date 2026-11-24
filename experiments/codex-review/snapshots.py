"""Validate exact, approved, bounded UTF-8 evidence without I/O."""

from hashlib import sha256

CONTEXT_LIMIT = 524_288
INSTRUCTIONS_LIMIT = 262_144


class SnapshotError(ValueError):
    """The snapshot does not match its approved bytes or text contract."""


def validate_snapshot(data: bytes, digest: str, limit: int) -> str:
    """Return the complete decoded snapshot, or reject it without echoing data."""
    if not 0 < len(data) <= limit or sha256(data).hexdigest() != digest:
        raise SnapshotError("Approved review snapshot is invalid.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SnapshotError("Approved review snapshot is invalid.") from None
    if not text.strip() or "\0" in text:
        raise SnapshotError("Approved review snapshot is invalid.")
    return text
