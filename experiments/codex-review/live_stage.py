"""Private, contained child roles; the public CLI never imports provider clients here."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from authorization import ExecutionPacket, VerifiedExecution
    from sdk_worker import StartupOutcome

Role = Literal["verifier", "review", "reverify", "publisher"]
ROLES = frozenset(("verifier", "review", "reverify", "publisher"))
CHALLENGE = "LIGHTHOUSE_STAGE_CHALLENGE"
PARENT = "LIGHTHOUSE_STAGE_PARENT_PID"
JWT_FILE = "LIGHTHOUSE_STAGE_JWT_FILE"
MANAGED = frozenset(
    ("SYSTEMROOT", "WINDIR", "USERPROFILE", "HOME", "CODEX_HOME", "APPDATA", "LOCALAPPDATA",
     "TEMP", "TMP", "SYSTEMDRIVE", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA")
)
LIMIT = 1_048_576


class StageHold(RuntimeError):
    """A generic failure that must not render private state."""


class HistoricalPublication(StageHold):
    """A matched prior receipt, not a successful current-stage publication."""

    def __init__(self, review_id: int) -> None:
        super().__init__("Original COMMENT receipt found; current proof remains held.")
        self.review_id = review_id


def read_bounded(path: Path, limit: int = LIMIT) -> bytes:
    """Read only a small regular private file; do not follow symlinks."""
    if path.is_symlink() or not path.is_file():
        raise StageHold("Private stage input unavailable.")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise StageHold("Private stage input exceeded its limit.")
    return data


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate key.")
        result[key] = value
    return result


def read_signal(path: Path) -> dict[str, object]:
    """Read one private JSON signal without accepting ambiguous duplicate keys."""
    data: object = json.loads(read_bounded(path).decode("utf-8"), object_pairs_hook=_unique)
    if not isinstance(data, dict):
        raise StageHold("Malformed private stage signal.")
    return dict(data)


def write_signal(path: Path, data: dict[str, object]) -> None:
    """Commit a one-writer, bounded JSON signal atomically."""
    content = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(content) > LIMIT:
        raise StageHold("Private stage result exceeded its limit.")
    pending = path.with_name(path.name + ".pending")
    with pending.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def _absolute(value: object) -> Path:
    if not isinstance(value, str):
        raise StageHold("Invalid private path.")
    path = Path(value)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise StageHold("Private path must already be canonical.")
    return path


@dataclass(frozen=True)
class Request:
    """Input bound by the parent to the private receipt root and this trial."""

    comment_id: int
    repository_id: int
    receipt_root: Path
    workspace: Path
    git_executable: Path
    started_at: float

    @classmethod
    def read(cls, control: Path, now: float) -> Request:
        """Accept only the exact request schema and a physically scoped control path."""
        item = read_signal(control / "request.json")
        if set(item) != {
            "comment_id", "repository_id", "receipt_root", "workspace", "git_executable", "started_at",
        }:
            raise StageHold("Malformed stage request.")
        comment, repo, start = item["comment_id"], item["repository_id"], item["started_at"]
        root, workspace = _absolute(item["receipt_root"]), _absolute(item["workspace"])
        git_executable = _absolute(item["git_executable"])
        if (
            type(comment) is not int or comment <= 0 or type(repo) is not int or repo <= 0
            or not isinstance(start, (int, float)) or isinstance(start, bool)
            or not math.isfinite(start) or not 0 <= now - start < 900
            or root != control.parent or not control.is_dir() or not workspace.is_dir()
            or root.is_relative_to(workspace)
            or not git_executable.is_file() or git_executable.suffix.lower() != ".exe"
            or git_executable.is_relative_to(workspace) or git_executable.is_relative_to(root)
        ):
            raise StageHold("Malformed or expired stage request.")
        return cls(comment, repo, root, workspace, git_executable, float(start))


class CompletionLike(Protocol):
    """Authorized review worker result before private recording."""

    @property
    def thread_id(self) -> str: ...
    @property
    def turn_id(self) -> str: ...
    @property
    def head(self) -> str: ...
    @property
    def output(self) -> str: ...


class ReviewCall(Protocol):
    """Injected deferred review, not bound at module import."""

    def __call__(
        self, packet: ExecutionPacket, context: bytes, instructions: bytes, /, *,
        workspace: Path, managed_env: dict[str, str],
        before_review: Callable[[str], None], on_started: Callable[[str, str], None],
        interrupted: Callable[[], bool], on_attention: Callable[[], None],
        on_startup: Callable[[StartupOutcome], None], verify_checkout: Callable[[], None],
    ) -> CompletionLike: ...


class CheckoutCall(Protocol):
    """Independent local checkout proof with the existing stage time budget."""
    def __call__(
        self, executable: Path, workspace: Path, packet: ExecutionPacket,
        remaining: Callable[[], float], /,
    ) -> None: ...


class VerifyCall(Protocol):
    """Trusted separate verification inside a bounded stage."""

    def __call__(self, packet: bytes, request: Request, remaining: Callable[[], float], /) -> VerifiedExecution: ...


class PublishCall(Protocol):
    """Separate authenticated publisher following exact review provenance."""

    def __call__(
        self, authority: VerifiedExecution, result: dict[str, object], request: Request,
        remaining: Callable[[], float], validate_current: Callable[[], VerifiedExecution], /,
    ) -> int: ...


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value):
        raise StageHold("Malformed review identifier.")
    return value


def _default_verify(env: Mapping[str, str]) -> VerifyCall:
    def deferred(packet: bytes, request: Request, remaining: Callable[[], float]) -> VerifiedExecution:
        from authorization import verify
        from github_transport import GithubTransport

        transport = GithubTransport(
            jwt=lambda: _jwt(env), repository_id=request.repository_id,
            remaining=remaining, scope="verifier",
        )
        return verify(
            packet, comment_id=request.comment_id, repository_id=request.repository_id,
            transport=transport, now=datetime.now(UTC),
        )

    return deferred


def _jwt(env: Mapping[str, str]) -> str:
    """Read a managed role-only JWT only when the verified App request needs one."""
    path = _absolute(env.get(JWT_FILE))
    try:
        token = read_bounded(path, 16_384).decode("ascii").strip()
    except (OSError, UnicodeError):
        raise StageHold("Managed Lead setting unavailable.") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise StageHold("Managed Lead setting unavailable.")
    return token


def _default_publish(env: Mapping[str, str]) -> PublishCall:
    def deferred(
        authority: VerifiedExecution, result: dict[str, object], request: Request,
        remaining: Callable[[], float], validate_current: Callable[[], VerifiedExecution],
    ) -> int:
        from authorization import Denied
        from github_transport import CommentPublisher, CompletedReview, GithubTransport

        output = result.get("output")
        if not isinstance(output, str):
            raise StageHold("Private review result missing.")
        completed = CompletedReview(
            authority.packet_sha256, authority.packet.head, _identifier(result.get("thread_id")),
            _identifier(result.get("turn_id")), output,
        )
        transport = GithubTransport(
            jwt=lambda: _jwt(env), repository_id=request.repository_id,
            remaining=remaining, scope="publisher",
        )
        publisher = CommentPublisher(transport, authority, request.receipt_root)
        try:
            return publisher.publish(completed, validate_current).review_id
        except (Denied, OSError):
            # reconcile() validates the original durable intent before any lookup.
            # No callback can retry the POST or advance to another head.
            if remaining() > 0:
                try:
                    historical = publisher.reconcile()
                except (Denied, OSError):
                    raise StageHold("Private COMMENT outcome unconfirmed.") from None
                if historical is not None:
                    raise HistoricalPublication(historical.review_id) from None
            raise StageHold("Private COMMENT outcome unconfirmed.") from None

    return deferred


def _default_review(
    packet: ExecutionPacket, context: bytes, instructions: bytes, *,
    workspace: Path, managed_env: dict[str, str], before_review: Callable[[str], None],
    on_started: Callable[[str, str], None], interrupted: Callable[[], bool],
    on_attention: Callable[[], None], on_startup: Callable[[StartupOutcome], None],
    verify_checkout: Callable[[], None],
) -> CompletionLike:
    from sdk_worker import review

    # Isolated, one-role child only; do not give the SDK internal control markers.
    os.environ.pop(CHALLENGE, None)
    os.environ.pop(PARENT, None)
    return review(
        packet, context, instructions, workspace=workspace, managed_env=managed_env,
        before_review=before_review, on_started=on_started, interrupted=interrupted,
        on_attention=on_attention, on_startup=on_startup, verify_checkout=verify_checkout,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_stage(
    role: Role, control: Path, *, env: Mapping[str, str],
    clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
    parent_pid: Callable[[], int] = os.getppid, verify_call: VerifyCall | None = None,
    review_call: ReviewCall | None = None, publish_call: PublishCall | None = None,
    utc_now: Callable[[], datetime] = _utc_now, checkout_call: CheckoutCall | None = None,
) -> None:
    """Run one job role, with all provider construction deferred and injectable."""
    from authorization import (
        ExecutionPacket,
        canonical_packet,
        claim,
        private_receipt_binding,
    )

    challenge = env.get(CHALLENGE, "")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", challenge) or env.get(PARENT) != str(parent_pid())
        or not control.is_absolute() or control.resolve(strict=True) != control
        or role not in ROLES or (role == "review" and JWT_FILE in env)
    ):
        raise StageHold("Private stage parent not verified.")
    start = clock()
    request = Request.read(control, start)
    deadline = request.started_at + (
        30 if role == "verifier" else 870 if role == "publisher" else 780
    )

    def remaining() -> float:
        return deadline - clock()

    if remaining() <= 0 or (role == "publisher" and start >= request.started_at + 840):
        raise StageHold("Private stage deadline elapsed.")
    packet_bytes = read_bounded(control / "packet.json", 32_768)
    packet = ExecutionPacket.model_validate_json(packet_bytes)
    digest = hashlib.sha256(canonical_packet(packet)).hexdigest()
    def require_unexpired() -> None:
        observed = utc_now()
        if observed.utcoffset() is None or observed.timestamp() >= packet.expires_at:
            raise StageHold("Private execution packet expired.")

    require_unexpired()
    if packet.repository_id != request.repository_id or (
        private_receipt_binding(request.receipt_root) != packet.receipt_binding
    ):
        raise StageHold("Private stage target changed.")
    base: dict[str, object] = {"challenge": challenge, "packet_sha256": digest, "head": packet.head}

    def result(name: str, **extra: object) -> None:
        write_signal(control / name, {**base, "ok": True, **extra})

    def require(name: str) -> dict[str, object]:
        item = read_signal(control / name)
        if item.get("ok") is not True or any(item.get(k) != v for k, v in base.items()):
            raise StageHold("Private stage result not correlated.")
        return item

    def checked() -> VerifiedExecution:
        require_unexpired()
        verifier = verify_call or _default_verify(env)
        authority = verifier(packet_bytes, request, remaining)
        # Reads can outlast the signed authorization.
        require_unexpired()
        if authority.packet_sha256 != digest or authority.packet != packet or (
            authority.comment_id != request.comment_id or remaining() <= 0
        ):
            raise StageHold("Private stage authority changed.")
        return authority

    if role != "verifier":
        expected_claim = f"{digest}\n{packet.dispatch_id}\n".encode("ascii")
        if read_bounded(request.receipt_root / f"t01-{request.comment_id}.claim", 1024) != expected_claim:
            raise StageHold("Private review allowance not confirmed.")

    if role == "verifier":
        authority = checked()
        require_unexpired()
        claim(authority, request.receipt_root)
        require_unexpired()
        if remaining() <= 0:
            raise StageHold("Private stage deadline elapsed.")
        result("verifier.result.json", verified_at=clock())
    elif role == "reverify":
        require("verifier.result.json")
        ready = require("review.ready.json")
        checked()
        result("reverify.result.json", verified_at=clock(), thread_id=_identifier(ready.get("thread_id")))
    elif role == "review":
        require("verifier.result.json")
        context = read_bounded(control / "context.txt")
        instructions = read_bounded(control / "instructions.txt")
        if hashlib.sha256(context).hexdigest() != packet.context_sha256 or (
            hashlib.sha256(instructions).hexdigest() != packet.instructions_sha256
        ):
            raise StageHold("Private review inputs changed.")
        matched_thread: str | None = None
        matched_turn: str | None = None

        def verify_checkout() -> None:
            def require_budget() -> None:
                require_unexpired()
                if remaining() <= 0:
                    raise StageHold("Private review deadline elapsed.")

            require_budget()
            proof = checkout_call
            if proof is None:
                from checkout_proof import verify_checkout as prove
                proof = prove
            proof(request.git_executable, request.workspace, packet, remaining)
            require_budget()

        def before_review(thread: str) -> None:
            nonlocal matched_thread
            if matched_thread is not None:
                raise StageHold("Private review start already requested.")
            matched_thread = _identifier(thread)
            result("review.ready.json", thread_id=thread)
            while remaining() > 0:
                if (control / "review.authority.json").is_file():
                    fresh = require("review.authority.json")
                    verified_at = fresh.get("verified_at")
                    if (
                        fresh.get("thread_id") != thread or not isinstance(verified_at, (int, float))
                        or isinstance(verified_at, bool) or not 0 <= clock() - verified_at <= 5
                    ):
                        raise StageHold("Fresh review authority not verified.")
                    verify_checkout()
                    if not 0 <= clock() - verified_at <= 5:
                        raise StageHold("Fresh review authority elapsed during checkout proof.")
                    result("review.intent.json", thread_id=thread)
                    require_unexpired()
                    if remaining() <= 0 or not 0 <= clock() - verified_at <= 5:
                        raise StageHold("Private review authority elapsed before dispatch.")
                    return
                sleep(min(0.05, max(0, remaining())))
            raise StageHold("Fresh review authority was not received.")

        def on_started(thread: str, turn: str) -> None:
            nonlocal matched_turn
            if matched_thread != thread or matched_turn is not None:
                raise StageHold("Private review identity changed.")
            matched_turn = _identifier(turn)
            result("review.started.json", thread_id=thread, turn_id=turn)

        def interrupted() -> bool:
            marker = control / "review.interrupt.json"
            return marker.is_file() and read_signal(marker).get("challenge") == challenge

        require_unexpired()
        attention_lock = Lock()
        attention_recorded = False

        def on_attention() -> None:
            nonlocal attention_recorded
            with attention_lock:
                if not attention_recorded:
                    result("review.attention.json", reason="permission-request", next_actor="owner")
                    attention_recorded = True

        diagnostic_lock = Lock()

        def on_startup(outcome: StartupOutcome) -> None:
            # A diagnostic is evidence only: it is never an authority or success receipt.
            from sdk_worker import StartupOutcome

            if not isinstance(outcome, StartupOutcome):
                raise StageHold("Unknown private startup outcome.")
            name = "review.cleanup.json" if outcome.value.startswith("cleanup_") else "review.startup.json"
            with diagnostic_lock:
                write_signal(control / name, {
                    **base, "dispatch_id": packet.dispatch_id, "outcome": outcome.value,
                })

        completed = (review_call or _default_review)(
            packet, context, instructions, workspace=request.workspace,
            managed_env={key.upper(): value for key, value in env.items() if key.upper() in MANAGED},
            before_review=before_review, on_started=on_started, interrupted=interrupted,
            on_attention=on_attention, on_startup=on_startup, verify_checkout=verify_checkout,
        )
        if (
            matched_thread is None or matched_turn is None or completed.thread_id != matched_thread
            or completed.turn_id != matched_turn or completed.head != packet.head or remaining() <= 0
        ):
            raise StageHold("Private review completion not attributed.")
        result(
            "review.result.json", thread_id=completed.thread_id, turn_id=completed.turn_id,
            output=completed.output,
        )
    else:
        require("verifier.result.json")
        completed_result = require("review.result.json")
        started = require("review.started.json")
        stopped = require("review.shutdown.json")
        if any(completed_result.get(key) != started.get(key) for key in ("thread_id", "turn_id")):
            raise StageHold("Private review completion not attributed.")
        if (stopped.get("worker_exited") is not True or type(stopped.get("active")) is not int
                or stopped.get("active") != 0):
            raise StageHold("Local review job shutdown not confirmed.")
        authority = checked()
        try:
            require_unexpired()
            review_id = (publish_call or _default_publish(env))(
                authority, completed_result, request, remaining, checked
            )
        except HistoricalPublication as prior:
            if remaining() > 0 and type(prior.review_id) is int and prior.review_id > 0:
                write_signal(control / "publisher.reconciled.json", {
                    **base, "ok": False, "historical": True, "review_id": prior.review_id,
                })
            raise
        if type(review_id) is not int or review_id <= 0 or remaining() <= 0:
            raise StageHold("Private publication outcome unconfirmed.")
        result("publisher.result.json", review_id=review_id)


def main() -> int:
    """Private executable: only the owned, role-scoped parent starts it."""
    if not sys.flags.isolated or len(sys.argv) != 3 or sys.argv[1] not in ROLES:
        return 2
    from typing import cast

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        run_stage(cast(Role, sys.argv[1]), Path(sys.argv[2]), env=os.environ)
    except (RuntimeError, ValueError, OSError, KeyError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
