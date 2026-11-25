"""Pure parsing and canonical digest for the capture-only approval packet."""

from __future__ import annotations

import hashlib
import json
import ntpath
import re
from dataclasses import dataclass
from pathlib import PureWindowsPath

from t02_capture_evidence import SCOPE, CaptureApprovalTarget
from t02_event_rpc import SOURCE_PATH
from t02_event_types import EVENT, TOKEN, VERSION, Hold, decode

MAX_PACKET_BYTES = 8192
_DIGEST_DOMAIN = b"lighthouse-t02-callback-capture-only/packet-v1\x00"
_FIXED: dict[str, object] = {
    "version": 1, "scope": SCOPE, "repository": "craigholland/lighthouse",
    "issue": 5, "pull_request": 15, "protocol": VERSION, "host_ip": "127.0.0.1",
    "port": 8765, "source_path": SOURCE_PATH, "event": EVENT,
    "runtime": "tunnel-client-runtime/v0.0.21/windows-amd64",
}
_IDS = ("workspace", "dot_profile", "organization", "tunnel", "host", "proof_id", "principal", "operation_id")
_FILES = ("checkout", "runtime_archive", "runtime_executable", "platform_key", "loopback_bearer", "state")
_HASHES = ("runtime_archive_sha256", "runtime_executable_sha256")
_TIMES = ("activation_ms", "intake_cutoff_ms", "cleanup_cutoff_ms")


def _fixed_path(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 240 or not value.isascii():
        raise Hold("invalid capture packet path")
    path = PureWindowsPath(value)
    if (not re.fullmatch(r"[A-Z]:", path.drive) or not path.is_absolute() or len(path.parts) < 2
        or str(path) != value or any(
            not re.fullmatch(r"[A-Za-z0-9_ .-]+", part) or part.endswith((".", " "))
            or ntpath.isreserved(part) for part in path.parts[1:]
        )):
        raise Hold("invalid capture packet path")
    return value


@dataclass(frozen=True, repr=False)
class CapturePacket:
    """Canonical, private packet; parsing is not evidence about local files."""

    approval: CaptureApprovalTarget
    canonical: bytes
    intake_cutoff_ms: int
    proof_id: str
    principal: str

    @classmethod
    def parse(cls, data: bytes) -> CapturePacket:
        """Reject unknown fields; bind the full exact target into one v1 digest."""
        record = decode(data, MAX_PACKET_BYTES)
        keys = set(_FIXED) | set(_IDS) | set(_FILES) | set(_HASHES) | set(_TIMES) | {"head", "filter"}
        if set(record) != keys or any(
            type(record[key]) is not type(expected) or record[key] != expected for key, expected in _FIXED.items()
        ):
            raise Hold("unexpected capture packet schema")
        if any(not isinstance(part, str) or not TOKEN.fullmatch(part) for part in (record[key] for key in _IDS)):
            raise Hold("invalid capture packet identity")
        if record["filter"] != {"proof_id": record["proof_id"]}:
            raise Hold("invalid capture packet event filter")
        paths = [_fixed_path(record[key]) for key in _FILES]
        if len({path.casefold() for path in paths}) != len(paths):
            raise Hold("capture packet paths overlap")
        if any(not isinstance(part, str) or not re.fullmatch(r"[a-f0-9]{64}", part)
               for part in (record[key] for key in _HASHES)):
            raise Hold("invalid capture packet artifact digest")
        head = record["head"]
        start, intake, cleanup = (record[key] for key in _TIMES)
        if (not isinstance(head, str) or type(start) is not int or type(intake) is not int
            or type(cleanup) is not int or not 0 <= start < intake < cleanup
            or intake - start > 600_000 or cleanup - start > 900_000):
            raise Hold("invalid capture packet windows")
        proof_id, principal = record["proof_id"], record["principal"]
        assert isinstance(proof_id, str) and isinstance(principal, str)
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return cls(CaptureApprovalTarget(head, hashlib.sha256(_DIGEST_DOMAIN + canonical).hexdigest(), start, cleanup),
                   canonical, intake, proof_id, principal)
