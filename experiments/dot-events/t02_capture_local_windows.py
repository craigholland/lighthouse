"""Local facts for dormant capture composition, with explicit I/O boundaries."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable
from pathlib import Path

from t02_capture_local import LocalCaptureObservation
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_event_types import Hold, decode

_MAX_ARTIFACT_BYTES = 128 * 1024 * 1024


def _canonical(path: Path, *, directory: bool) -> str:
    """Check exact path text and reject reparse points in every ancestor."""
    if str(path.resolve(strict=True)) != str(path):
        raise Hold("capture local path changed")
    for item in (path, *path.parents):
        info = item.lstat()
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise Hold("capture local reparse point held")
    if path.is_dir() if directory else path.is_file():
        return str(path)
    raise Hold("capture local object type held")


def _digest(path: Path, clock: Callable[[], int], deadline: int) -> str:
    before = path.stat()
    if not 0 < before.st_size <= _MAX_ARTIFACT_BYTES:
        raise Hold("capture artifact size held")
    checksum = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        while clock() < deadline:
            data = stream.read(min(1024 * 1024, _MAX_ARTIFACT_BYTES - read + 1))
            if not data:
                if (read == before.st_size and path.stat() == before
                    and _canonical(path, directory=False) == str(path) and clock() < deadline):
                    return checksum.hexdigest()
                break
            read += len(data)
            if read > _MAX_ARTIFACT_BYTES:
                break
            checksum.update(data)
    raise Hold("capture artifact inspection held")


def observe_local_capture(
    packet: CapturePacket,
    host_name: Callable[[], str],
    git_projection: Callable[[Path, int], tuple[str, str, bool]],
    clock: Callable[[], int],
    deadline: int,
    *, canonical: Callable[..., str] = _canonical,
    digest: Callable[[Path, Callable[[], int], int], str] = _digest,
) -> LocalCaptureObservation:
    """Observe only declared local paths; never read either private secret."""
    fields = decode(packet.canonical, MAX_PACKET_BYTES)

    def path(key: str) -> Path:
        value = fields[key]
        if clock() >= deadline or not isinstance(value, str):
            raise Hold("capture local observer held")
        return Path(value)

    checkout = canonical(path("checkout"), directory=True)
    root = Path(checkout)
    names = ("runtime_archive", "runtime_executable", "platform_key", "loopback_bearer", "state")
    entries = tuple(canonical(path(key), directory=False) for key in names)
    repo, head, clean = git_projection(root, deadline)
    archive, executable = (digest(Path(name), clock, deadline) for name in entries[:2])
    host = host_name()
    if clock() >= deadline:
        raise Hold("capture local observation expired")
    return LocalCaptureObservation(host, repo, checkout, head, clean, archive, executable, entries)
