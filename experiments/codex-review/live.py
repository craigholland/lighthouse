"""Opt-in operator entry; no live jobs exist before structural validation."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from authorization import ExecutionPacket, canonical_packet, private_receipt_binding
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from snapshots import CONTEXT_LIMIT, INSTRUCTIONS_LIMIT, validate_snapshot
from supervisor import Action, Observation, Role, Supervisor

Stage = Role | Literal["reverify"]
_MANAGED_ENV = {"SystemRoot", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                "HOME", "TEMP", "TMP", "CODEX_HOME", "SystemDrive", "ProgramFiles",
                "ProgramFiles(x86)", "ProgramData"}
_PUBLIC_ENV = {"SystemRoot", "WINDIR", "TEMP", "TMP"}


class PrivateConfig(BaseModel):
    """Separately selected operator settings, never an authorization record."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    comment_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    receipt_root: str
    workspace: str
    git_executable: str
    verifier_jwt_file: str
    publisher_jwt_file: str


@dataclass(frozen=True, repr=False)
class Request:
    """Complete private packet; validated shape still does not authorize execution."""

    config: PrivateConfig
    packet: ExecutionPacket
    packet_bytes: bytes
    context: bytes
    instructions: bytes
    receipt_root: Path
    workspace: Path
    git_executable: Path
    digest: str


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if not value or len(value) > limit:
        raise ValueError("Invalid proof material size.")
    return value


def load_request(config_path: Path, command: str) -> Request:
    """Read private fixed-sibling inputs; malformed/policy-only never reaches a job."""
    config_path = config_path.resolve(strict=True)
    config = PrivateConfig.model_validate_json(_read(config_path, 16_384))
    source = config_path.parent
    packet_bytes = _read(source / "packet.json", 32_768)
    packet = ExecutionPacket.model_validate_json(packet_bytes)
    root = Path(config.receipt_root).resolve(strict=True)
    workspace = Path(config.workspace).resolve(strict=True)
    git_executable = Path(config.git_executable)
    dot_checkout = Path(__file__).resolve().parents[2]
    if (
        not workspace.is_dir() or workspace == dot_checkout
        or source.is_relative_to(workspace) or source.is_relative_to(dot_checkout)
        or root.is_relative_to(workspace) or root.is_relative_to(dot_checkout)
        or not git_executable.is_absolute()
        or git_executable.resolve(strict=True) != git_executable
        or not git_executable.is_file() or git_executable.suffix.lower() != ".exe"
        or any(git_executable.is_relative_to(untrusted) for untrusted in (
            workspace, dot_checkout, root, source,
        ))
        or not Path(config.verifier_jwt_file).is_absolute()
        or not Path(config.publisher_jwt_file).is_absolute()
        or packet.repository_id != config.repository_id
        or packet.command != command or packet.expires_at <= time.time()
        or packet.receipt_binding != private_receipt_binding(root)
        or canonical_packet(packet) != packet_bytes
    ):
        raise ValueError("Proof packet is not bound to this operator invocation.")
    context = _read(source / "context.txt", CONTEXT_LIMIT)
    instructions = _read(source / "instructions.txt", INSTRUCTIONS_LIMIT)
    validate_snapshot(context, packet.context_sha256, CONTEXT_LIMIT)
    validate_snapshot(instructions, packet.instructions_sha256, INSTRUCTIONS_LIMIT)
    return Request(config, packet, packet_bytes, context, instructions, root, workspace, git_executable,
                   hashlib.sha256(packet_bytes).hexdigest())


class ContainedProcess(Protocol):
    """Narrow native boundary; distinct owned job per role including re-verifier."""

    def start(self, role: Stage, control: Path, environment: dict[str, str]) -> None: ...
    def worker_exited(self) -> bool: ...
    def active_count(self) -> int: ...
    def force(self) -> None: ...
    def close(self) -> None: ...


class LiveJobs:
    """Map private child observations to the reviewed supervising role policy."""

    def __init__(
        self, request: Request, control: Path, entered: float, clock: Callable[[], float],
        factory: Callable[[], ContainedProcess], environ: Mapping[str, str],
    ) -> None:
        self.request = request
        self.control = control
        self.entered = entered
        self.clock = clock
        self.factory = factory
        self.environ = environ
        self.challenge = secrets.token_hex(32)
        self.jobs: dict[Stage, ContainedProcess] = {}
        self.refresh_started: float | None = None
        self.refresh_promoted = False
        self.review_shutdown_recorded = False

    def prepare(self) -> None:
        """Initialize private bounded control files; neither a claim nor authority."""
        config = self.request.config
        (self.control / "packet.json").write_bytes(self.request.packet_bytes)
        (self.control / "context.txt").write_bytes(self.request.context)
        (self.control / "instructions.txt").write_bytes(self.request.instructions)
        self._write("request.json", {
            "comment_id": config.comment_id, "repository_id": config.repository_id,
            "receipt_root": str(self.request.receipt_root), "workspace": str(self.request.workspace),
            "git_executable": str(self.request.git_executable), "started_at": self.entered,
        })

    def _write(self, name: str, value: dict[str, object]) -> None:
        path = self.control / name
        tmp = path.with_suffix(".pending")
        with tmp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)

    def _read_echo(self, name: str) -> dict[str, object] | None:
        try:
            payload = json.loads(_read(self.control / name, 262_144))
        except (FileNotFoundError, ValueError):
            return None
        if (
            not isinstance(payload, dict) or payload.get("challenge") != self.challenge
            or payload.get("packet_sha256") != self.request.digest
            or payload.get("head") != self.request.packet.head
        ):
            return None
        return dict(payload)

    def _environment(self, stage: Stage) -> dict[str, str]:
        allowed = _MANAGED_ENV if stage == Role.REVIEW else _PUBLIC_ENV
        env = {key: self.environ[key] for key in allowed if key in self.environ}
        env["LIGHTHOUSE_STAGE_CHALLENGE"] = self.challenge
        env["LIGHTHOUSE_STAGE_PARENT_PID"] = str(os.getpid())
        if stage != Role.REVIEW:
            config = self.request.config
            env["LIGHTHOUSE_STAGE_JWT_FILE"] = (
                config.publisher_jwt_file if stage == Role.PUBLISHER else config.verifier_jwt_file
            )
        return env

    def start(self, role: Role) -> None:
        """Roles can be launched only once, with explicit environments."""
        self._start(role)

    def _start(self, stage: Stage) -> None:
        if stage in self.jobs:
            raise RuntimeError("Unexpected repeated proof phase.")
        child = self.factory()
        self.jobs[stage] = child
        child.start(stage, self.control, self._environment(stage))

    def owner_attention(self) -> bool:
        """Recognize only a correlated fixed permission reason, never provider text."""
        signal = self._read_echo("review.attention.json")
        return signal is not None and (
            signal.get("ok") is True and signal.get("reason") == "permission-request"
            and signal.get("next_actor") == "owner"
        )

    def snapshot(self, role: Role) -> Observation:
        """Read bounded local files and account for both review-side jobs."""
        job = self.jobs[role]
        elapsed = self.clock() - self.entered
        if role == Role.REVIEW and elapsed < 780:
            self._reverify_if_requested()
        exited, active = job.worker_exited(), job.active_count()
        refresh = self.jobs.get("reverify") if role == Role.REVIEW else None
        if refresh is not None:
            exited = refresh.worker_exited() and exited
            active += refresh.active_count()
        outcome = self._read_echo(f"{role.value}.result.json")
        complete = outcome is not None and outcome.get("ok") is True
        if role == Role.REVIEW:
            complete = (
                complete and not self.owner_attention() and self.refresh_promoted and outcome is not None
                and all(isinstance(outcome.get(key), str) and outcome[key]
                        for key in ("thread_id", "turn_id", "output"))
            )
        if (
            role == Role.REVIEW and complete and exited and active == 0
            and not self.review_shutdown_recorded
        ):
            self._write("review.shutdown.json", {
                "challenge": self.challenge, "ok": True, "head": self.request.packet.head,
                "packet_sha256": self.request.digest, "worker_exited": True, "active": 0,
            })
            self.review_shutdown_recorded = True
        if role == Role.PUBLISHER:
            receipt = outcome.get("review_id") if outcome is not None else None
            complete = complete and type(receipt) is int and receipt > 0
        return Observation(exited, active, complete)

    def _reverify_if_requested(self) -> None:
        if self.refresh_promoted or self._read_echo("review.ready.json") is None:
            return
        if "reverify" not in self.jobs:
            self.refresh_started = self.clock()
            self._start("reverify")
            return
        current = self.jobs["reverify"]
        if not (current.worker_exited() and current.active_count() == 0):
            if self.refresh_started is not None and self.clock() - self.refresh_started >= 30:
                raise RuntimeError("Fresh authority verifier exceeded its bounded interval.")
            return
        result = self._read_echo("reverify.result.json")
        if result is None or result.get("ok") is not True:
            raise RuntimeError("Fresh authority was not verified.")
        self._write("review.authority.json", result)
        self.refresh_promoted = True

    def known_turn(self) -> bool:
        """Only a correlated private started observation permits interrupt."""
        try:
            return self._read_echo("review.started.json") is not None
        except OSError:
            return False

    def request_interrupt(self, role: Role) -> None:
        """Nonblocking private signal; never wait for an SDK acknowledgement."""
        if role == Role.REVIEW:
            self._write("review.interrupt.json", {"challenge": self.challenge})

    def force(self, role: Role) -> None:
        """Force only owned jobs; try both even when one native operation fails."""
        stages: tuple[Stage, ...] = (role, "reverify") if role == Role.REVIEW else (role,)
        failed = False
        for stage in stages:
            child = self.jobs.get(stage)
            if child is not None:
                try:
                    if not (child.worker_exited() and child.active_count() == 0):
                        child.force()
                except (OSError, RuntimeError):
                    try:
                        child.force()
                    except (OSError, RuntimeError):
                        failed = True
        if failed:
            raise RuntimeError("Owned proof job termination was unconfirmed.")

    def close(self) -> None:
        """Close retained handles as fail-safe, not as verified shutdown evidence."""
        for job in self.jobs.values():
            job.close()


def run(
    entered: float, *, environ: Mapping[str, str] = os.environ,
    factory: Callable[[], ContainedProcess] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    command: str | None = None,
) -> int:
    """Explicit operator-only entry; no live proof is enabled by default."""
    path = environ.get("LIGHTHOUSE_T01_OPERATOR_CONFIG")
    if not path or not Path(path).is_absolute():
        return 2
    try:
        request = load_request(
            Path(path), command if command is not None else
            subprocess.list2cmdline([sys.executable, *sys.argv]),
        )
        if clock() - entered >= 30:
            return 1
        if factory is None:
            from windows_job import StageJob

            factory = StageJob
        control = Path(tempfile.mkdtemp(prefix="t01-private-", dir=request.receipt_root))
        jobs = LiveJobs(request, control, entered, clock, factory, environ)
        supervisor = Supervisor(clock, jobs, entered_at=entered)
        try:
            jobs.prepare()
            supervisor.start()
            while True:
                action = supervisor.tick(known_active_turn=jobs.known_turn())
                if supervisor.terminal:
                    return 0 if action == Action.ADVANCE else 1
                sleep(0.04)
        finally:
            jobs.close()
    except (OSError, RuntimeError, ValueError, ValidationError):
        return 1
