"""Opt-in native fixture context; fixed harmless helper launches only."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_evidence import PREFIX, SCOPE, CaptureEvidence
from t02_capture_packet import CapturePacket
from t02_event_evidence import API_ROOT, MAX_PROVIDER_BYTES, ProviderReply
from t02_event_gate import LEAD, LEAD_APP, OWNER
from t02_event_types import Hold, encode
from t02_event_windows import _OwnedWindowsJob

FIXTURE_LEDGER = "LIGHTHOUSE_T02_FIXTURE_LEDGER"
FIXTURE_SCOPE = "selected-native-synthetic"
MODES = frozenset({"normal", "stall", "no-signal", "missing-root"})
REFS = (101, 102)
ACTIVATION = 1_700_000_001_000


def mono() -> int:
    return time.monotonic_ns() // 1_000_000


def write_marker(root: Path, name: str, fields: dict[str, object]) -> None:
    """Write only a single private fixed marker under the disposable root."""
    pending = root / (name + ".pending")
    with pending.open("x", encoding="ascii") as stream:
        json.dump(fields, stream, ensure_ascii=True, separators=(",", ":"))
    pending.rename(root / name)


def read_marker(root: Path, name: str) -> dict[str, object]:
    with (root / name).open("rb") as stream:
        raw = stream.read(32_769)
    if len(raw) > 32_768:
        raise Hold("fixture marker too large")
    data: object = json.loads(raw)
    if not isinstance(data, dict):
        raise Hold("fixture marker malformed")
    return dict(data)


@dataclass(frozen=True, repr=False)
class FixtureContext:
    root: Path
    mode: str
    python: Path
    started: int
    packet: CapturePacket

    @staticmethod
    def mono() -> int:
        return mono()

    def wall(self) -> int:
        return ACTIVATION + max(0, mono() - self.started)

    @classmethod
    def load(cls, root: Path, mode: str, python: Path) -> FixtureContext:
        if (not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir()
            or not root.name.startswith("lighthouse-native-") or mode not in MODES
            or not python.is_absolute() or python.name.casefold() != "pythonw.exe"):
            raise Hold("synthetic capture fixture held")
        record = read_marker(root, "setup.json")
        if set(record) != {"scope", "mode", "started", "packet"} or (
            record["scope"] != FIXTURE_SCOPE or record["mode"] != mode
        ):
            raise Hold("synthetic setup mismatch")
        started, raw = record["started"], record["packet"]
        if type(started) is not int or not 0 <= mono() - started < 20_000 or not isinstance(raw, str):
            raise Hold("synthetic setup bounds held")
        packet = CapturePacket.parse(raw.encode("ascii"))
        fields: object = json.loads(packet.canonical)
        if (
            not isinstance(fields, dict) or fields.get("state") != str(root / "capture.db")
            or fields.get("proof_id") != "synthetic-native-proof"
            or packet.approval.activation_ms != ACTIVATION
            or not 0 < packet.approval.cutoff_ms - packet.approval.activation_ms <= 18_000
        ):
            raise Hold("synthetic capture identity held")
        return cls(root, mode, python, started, packet)

    def exact(self, packet: CapturePacket, deadline: int) -> bool:
        return packet == self.packet and mono() < deadline

    def evidence(self) -> CaptureEvidence:
        return CaptureEvidence(_SyntheticGitHub(self), self.wall)


class _SyntheticGitHub:
    """Return exact fake owner/Lead records at the production parser boundary."""

    def __init__(self, context: FixtureContext) -> None:
        self._context = context

    def read(self, path: str, *, deadline_ms: int, limit: int) -> ProviderReply:
        fixture = self._context
        packet = fixture.packet
        target = packet.approval
        if limit != MAX_PROVIDER_BYTES or not fixture.wall() < deadline_ms <= packet.intake_cutoff_ms:
            raise Hold("synthetic approval deadline")
        if path == API_ROOT + "/issues/5":
            value: dict[str, object] = {"number": 5, "state": "open", "labels": []}
        elif path == API_ROOT + "/pulls/15":
            value = {"number": 15, "state": "open", "draft": True, "merged": False,
                     "head": {"sha": target.head}, "base": {"ref": "development"}}
        elif path in tuple(API_ROOT + f"/issues/comments/{ref}" for ref in REFS):
            ref = int(path.rsplit("/", 1)[1])
            owner = ref == REFS[0]
            created = "2023-11-14T22:13:19Z" if owner else "2023-11-14T22:13:20Z"
            value = {
                "id": ref, "user": {"id": OWNER if owner else LEAD, "type": "User" if owner else "Bot"},
                "issue_url": "https://api.github.com" + API_ROOT + "/issues/5",
                "performed_via_github_app": None if owner else {"id": LEAD_APP},
                "created_at": created, "updated_at": created,
                "body": PREFIX + encode({"head": target.head, "digest": target.digest, "scope": SCOPE,
                                        "not_before": target.activation_ms, "expires": target.cutoff_ms}).decode("ascii"),
            }
        else:
            raise Hold("synthetic approval route held")
        return ProviderReply(200, encode(value))


def spawn_fixture(
    host: _OwnedWindowsJob, context: FixtureContext, role: str, descriptor: InheritedCapture,
    *, jobs: tuple[int, ...] = (), preowned_job: int | None = None,
    before_resume: Callable[[int, int], None] | None = None,
) -> bool:
    """Start one of two exact harness entries; no caller-supplied executable or script."""
    if role not in {"coordinator", "supervisor"} or len(jobs) != (2 if role == "supervisor" else 0):
        raise Hold("synthetic helper role held")
    script = Path(__file__).with_name("t02_selected_native_fixture.py")
    raw = descriptor.to_environment()
    ledger = encode({
        "role": role, "descriptor": raw[ENVIRONMENT_KEY], "jobs": jobs,
    }).decode("ascii")
    return host._start_owned(
        context.python, ["-I", "-S", str(script), role, str(context.root), context.mode],
        raw | {FIXTURE_LEDGER: ledger}, descriptor.peer.intake_ms,
        before_resume=before_resume, bind_at_creation=True, inherited=(*descriptor.peer.handles, *jobs),
        preowned_job=preowned_job,
    )
