"""Pinned Codex review worker; run only inside the approved, owned child job."""
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from importlib.metadata import version
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from threading import Event, Thread
from typing import Protocol

from app_server_stdio import Child, Fault, ProtocolHold, Signal, StdioWire
from authorization import ExecutionPacket
from openai_codex.generated.v2_all import (
    AskForApprovalValue,
    GetAccountResponse,
    ReviewStartResponse,
    ThreadStartResponse,
    TurnInterruptResponse,
    TurnStatus,
)
from openai_codex.models import InitializeResponse, JsonObject
from review_paths import ReviewPathError, sanitize_review_paths
from snapshots import (
    SnapshotError,
    admit_review_input,
)

_SAFE_ENV = frozenset({
    "SYSTEMROOT", "WINDIR", "USERPROFILE", "HOME", "CODEX_HOME",
    "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "SYSTEMDRIVE",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
})
# The pinned App Server uses this display text when no review output exists.
_REVIEW_FALLBACK = "Reviewer failed to output a response."
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_RUNTIME_USER_AGENT = re.compile(
    r"(?P<product>[A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"(?P<build>(?:0|[1-9][0-9]*)(?:[.](?:0|[1-9][0-9]*)){2})"
    r"(?: [(][ -'*-~]+[)](?: [ -~]*)?)?"
)
_ORIGINS = {
    "https://github.com/craigholland/lighthouse",
    "https://github.com/craigholland/lighthouse.git",
}


class StartupOutcome(StrEnum):
    """Bounded operational evidence codes; never include provider exception text."""

    SNAPSHOT_VALIDATION_FAILED = auto()
    SDK_STARTING = auto()
    SDK_START_FAILED = auto()
    INITIALIZATION_STARTING = auto()
    INITIALIZATION_FAILED = auto()
    MANAGED_ACCOUNT_CHECKING = auto()
    MANAGED_ACCOUNT_FAILED = auto()
    THREAD_STARTING = auto()
    THREAD_START_FAILED = auto()
    THREAD_VALIDATING = auto()
    THREAD_POLICY_FAILED = auto()
    THREAD_VALIDATION_FAILED = auto()
    CHECKOUT_PROOF_CHECKING = auto()
    CHECKOUT_PROOF_FAILED = auto()
    GIT_IDENTITY_MISMATCH = auto()
    PRE_REVIEW_CHECKING = auto()
    REVIEW_DISPATCH_UNKNOWN = auto()
    REVIEW_DISPATCH_DEADLINE_ELAPSED = auto()
    REVIEW_DISPATCH_INTERRUPTED = auto()
    REVIEW_DISPATCH_FRAME_INVALID = auto()
    REVIEW_DISPATCH_BUFFER_OVERFLOW = auto()
    REVIEW_DISPATCH_TRANSPORT_LOST = auto()
    REVIEW_DISPATCH_SERVER_ERROR = auto()
    REVIEW_DISPATCH_ACK_INVALID = auto()
    COLLECTION_READ_FAILED = auto()
    COLLECTION_FRAME_INVALID = auto()
    COLLECTION_DEADLINE_ELAPSED = auto()
    COLLECTION_BUFFER_OVERFLOW = auto()
    COLLECTION_TRANSPORT_LOST = auto()
    COLLECTION_SERVER_ERROR = auto()
    COLLECTION_TERMINAL_CONFLICT = auto()
    COLLECTION_THREAD_ID_MISMATCH = auto()
    COLLECTION_THREAD_MODE_MISMATCH = auto()
    COLLECTION_TURN_COUNT_MISMATCH = auto()
    COLLECTION_TURN_ID_MISMATCH = auto()
    COLLECTION_TURN_DISAPPEARED = auto()
    COLLECTION_RUNTIME_FAILED = auto()
    COLLECTION_INTERRUPTED = auto()
    COLLECTION_OUTPUT_FAILED = auto()
    COLLECTION_PERMISSION_REQUESTED = auto()
    CLEANUP_STARTING = auto()
    CLEANUP_COMPLETED = auto()
    CLEANUP_FAILED = auto()
    PERMISSION_REQUESTED = auto()


class ReviewHold(RuntimeError):
    """Sanitized failure, never an assertion of remote cancellation."""


@dataclass(frozen=True)
class Completion:
    """Private completed review text attributed to one exact run and head."""

    thread_id: str
    turn_id: str
    head: str
    output: str = field(repr=False)


class ReviewClient(Protocol):
    """Narrow operations consumed by the supervised review child."""

    def start(self) -> None: ...
    def initialize(self) -> InitializeResponse: ...
    def account_read(self) -> GetAccountResponse: ...
    def thread_start(self, parameters: JsonObject) -> ThreadStartResponse: ...
    def review_start(self, parameters: JsonObject) -> ReviewStartResponse: ...
    def next_review_signals(self, count: int, stopped: Event) -> tuple[Signal, ...]: ...
    def final_review_signals(self) -> tuple[Signal, ...] | None: ...
    def turn_interrupt(self, thread_id: str, turn_id: str) -> None: ...
    def approval_requested(self) -> bool: ...
    def close(self) -> None: ...


def _launch_app_server(workspace: Path, managed_env: dict[str, str]) -> Child:
    """Launch only the pinned bundled executable on owned local stdio."""
    from codex_cli_bin import bundled_codex_path  # type: ignore[import-untyped]

    executable = bundled_codex_path()
    if not executable.is_absolute() or not executable.is_file():
        raise ProtocolHold(Fault.TRANSPORT)
    return Popen(
        [str(executable), "app-server", "--listen", "stdio://"],
        stdin=PIPE, stdout=PIPE, stderr=DEVNULL, cwd=workspace, env=managed_env,
    )


class _StdioClient:
    """Managed worker boundary; no SDK router or provider history access."""

    def __init__(self, workspace: Path, managed_env: dict[str, str],
                 on_attention: Callable[[], None], interrupted: Callable[[], bool]) -> None:
        home = managed_env.get("CODEX_HOME")
        if not home:
            raise ReviewHold("Dedicated managed review home unavailable.")
        managed_home = Path(home).resolve(strict=True)
        if not managed_home.is_dir() or managed_home.is_relative_to(workspace):
            raise ReviewHold("Dedicated managed review home unavailable.")
        if {key.upper() for key in os.environ} - _SAFE_ENV:
            raise ReviewHold("Review worker environment is not isolated.")
        if (
            version("openai-codex") != "0.171.0"
            or version("openai-codex-cli-bin") != "0.171.0"
        ):
            raise ReviewHold("Pinned SDK or runtime unavailable.")
        self._workspace = workspace
        self._env = managed_env
        self._attention = on_attention
        self._interrupted = interrupted
        self._wire: StdioWire | None = None

    @property
    def wire(self) -> StdioWire:
        if self._wire is None:
            raise ProtocolHold(Fault.TRANSPORT)
        return self._wire

    def start(self) -> None:
        if self._wire is not None:
            raise ProtocolHold(Fault.TRANSPORT)
        self._wire = StdioWire(_launch_app_server(self._workspace, self._env), self._attention,
                              cancelled=self._interrupted)

    def initialize(self) -> InitializeResponse:
        result = self.wire.request("initialize", {
            "clientInfo": {"name": "lighthouse_t01", "title": "Lighthouse T01", "version": "0.1.0"},
            "capabilities": {"experimentalApi": False},
        }, InitializeResponse)
        self.wire.initialized()
        return result

    def account_read(self) -> GetAccountResponse:
        return self.wire.request("account/read", {"refreshToken": False}, GetAccountResponse)

    def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
        return self.wire.request("thread/start", dict(parameters), ThreadStartResponse)

    def review_start(self, parameters: JsonObject) -> ReviewStartResponse:
        return self.wire.request("review/start", dict(parameters), ReviewStartResponse, capture=True)

    def next_review_signals(self, count: int, stopped: Event) -> tuple[Signal, ...]:
        self.wire.wait_for_change(count, stopped)
        return self.wire.snapshot(stopped)

    def final_review_signals(self) -> tuple[Signal, ...] | None:
        return self.wire.snapshot(Event())

    def turn_interrupt(self, thread_id: str, turn_id: str) -> None:
        self.wire.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id},
                          TurnInterruptResponse, allow_interrupt=True)

    def approval_requested(self) -> bool:
        return self._wire is not None and self.wire.requested_permission()

    def close(self) -> None:
        if self._wire is not None:
            self.wire.close()


def open_review_client(workspace: Path, managed_env: dict[str, str],
                       on_attention: Callable[[], None], interrupted: Callable[[], bool]) -> ReviewClient:
    """Construct, but do not start, the pinned client inside the authorized child."""
    return _StdioClient(workspace, managed_env, on_attention, interrupted)


def _verify_runtime(info: InitializeResponse, expected: str) -> None:
    """Require the pinned build in the public initialize response's product token."""
    match = _RUNTIME_USER_AGENT.fullmatch(info.userAgent or "")
    server = info.serverInfo
    if (
        match is None or match["build"] != expected
        or (server is not None and (
            (server.version is not None and server.version != match["build"])
            or (server.name is not None and server.name != match["product"])
        ))
    ):
        raise ReviewHold("Effective App Server runtime does not match.")


class _ThreadHold(ReviewHold):
    def __init__(self, outcome: StartupOutcome) -> None:
        super().__init__("Effective review settings or checkout identity do not match.")
        self.outcome = outcome


def _verify_thread(response: ThreadStartResponse, packet: ExecutionPacket, workspace: Path) -> str:
    sandbox = response.sandbox.root
    git = response.thread.git_info
    if (
        sandbox.type != "readOnly" or sandbox.network_access is not False
        or response.approval_policy.root != AskForApprovalValue.never
        or response.approvals_reviewer.value != "user"
    ):
        raise _ThreadHold(StartupOutcome.THREAD_POLICY_FAILED)
    if (
        response.model != packet.model or response.model_provider != "openai"
        or Path(response.cwd.root).resolve() != workspace
        or Path(response.thread.cwd.root).resolve() != workspace
        or response.thread.ephemeral is not False
        or response.thread.turns
        or not _ID.fullmatch(response.thread.id)
    ):
        raise _ThreadHold(StartupOutcome.THREAD_VALIDATION_FAILED)
    # The independent checkout proof is mandatory. Any non-null identity
    # annotation the SDK supplies must also agree, even if the other is absent.
    if git is not None and (
        (git.sha is not None and (not isinstance(git.sha, str) or git.sha != packet.head))
        or (git.origin_url is not None
            and (not isinstance(git.origin_url, str) or git.origin_url not in _ORIGINS))
    ):
        raise _ThreadHold(StartupOutcome.GIT_IDENTITY_MISMATCH)
    return response.thread.id


def interrupt_known(client: ReviewClient, thread_id: str, turn_id: str) -> None:
    """Request interruption of exactly the known run; do not infer success."""
    if not _ID.fullmatch(thread_id) or not _ID.fullmatch(turn_id):
        raise ReviewHold("Cannot interrupt an unidentified review.")
    client.turn_interrupt(thread_id, turn_id)


class _CollectionHold(ReviewHold):
    """A fixed collection disposition, not a claim of completion or cancellation."""

    def __init__(self, outcome: StartupOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome


_COLLECTION_CODES = {
    Fault.TIMEOUT: StartupOutcome.COLLECTION_DEADLINE_ELAPSED,
    Fault.FRAME: StartupOutcome.COLLECTION_FRAME_INVALID,
    Fault.OVERFLOW: StartupOutcome.COLLECTION_BUFFER_OVERFLOW,
    Fault.TRANSPORT: StartupOutcome.COLLECTION_TRANSPORT_LOST,
    Fault.SERVER: StartupOutcome.COLLECTION_SERVER_ERROR,
    Fault.PERMISSION: StartupOutcome.COLLECTION_PERMISSION_REQUESTED,
    Fault.INTERRUPTED: StartupOutcome.COLLECTION_INTERRUPTED,
    Fault.THREAD: StartupOutcome.COLLECTION_THREAD_ID_MISMATCH,
    Fault.TURN: StartupOutcome.COLLECTION_TURN_ID_MISMATCH,
    Fault.TERMINAL: StartupOutcome.COLLECTION_TERMINAL_CONFLICT,
    Fault.OUTPUT: StartupOutcome.COLLECTION_OUTPUT_FAILED,
}
_DISPATCH_CODES = {
    Fault.INTERRUPTED: StartupOutcome.REVIEW_DISPATCH_INTERRUPTED,
    Fault.TIMEOUT: StartupOutcome.REVIEW_DISPATCH_DEADLINE_ELAPSED,
    Fault.FRAME: StartupOutcome.REVIEW_DISPATCH_FRAME_INVALID,
    Fault.OVERFLOW: StartupOutcome.REVIEW_DISPATCH_BUFFER_OVERFLOW,
    Fault.TRANSPORT: StartupOutcome.REVIEW_DISPATCH_TRANSPORT_LOST,
    Fault.SERVER: StartupOutcome.REVIEW_DISPATCH_SERVER_ERROR,
    Fault.ACK: StartupOutcome.REVIEW_DISPATCH_ACK_INVALID,
    Fault.PERMISSION: StartupOutcome.PERMISSION_REQUESTED,
}


def _check_attention(client: ReviewClient, stopped: Event, on_attention: Callable[[], None]) -> None:
    if client.approval_requested():
        on_attention()
        raise _CollectionHold(StartupOutcome.COLLECTION_PERMISSION_REQUESTED,
                              "Review needs permission attention.")
    if stopped.is_set():
        raise _CollectionHold(StartupOutcome.COLLECTION_INTERRUPTED,
                              "Review interrupted locally; remote outcome is unknown.")


def _attributed_output(signals: tuple[Signal, ...], thread: str, turn: str) -> str | None:
    output: str | None = None
    entered = False
    terminal = False
    for signal in signals:
        if signal.thread != thread:
            raise ProtocolHold(Fault.THREAD)
        if signal.turn != turn:
            raise ProtocolHold(Fault.TURN)
        if terminal:
            raise ProtocolHold(Fault.TERMINAL)
        if signal.kind == "enteredReviewMode":
            if entered or output is not None:
                raise ProtocolHold(Fault.OUTPUT)
            entered = True
        elif signal.kind == "exitedReviewMode":
            if output is not None or not entered:
                raise ProtocolHold(Fault.OUTPUT)
            output = signal.value
        elif signal.kind == "terminal":
            if signal.value == "interrupted":
                raise _CollectionHold(StartupOutcome.COLLECTION_INTERRUPTED,
                                      "Provider interruption was observed for the known review.")
            if signal.value == "failed":
                raise _CollectionHold(StartupOutcome.COLLECTION_RUNTIME_FAILED,
                                      "Provider reported a failed review.")
            if signal.value != "completed":
                raise ProtocolHold(Fault.TERMINAL)
            terminal = True
            if (output is None or len(output) > 60_000 or output.strip() in ("", _REVIEW_FALLBACK)
                or any(ord(char) < 32 and char not in "\r\n\t" for char in output)):
                raise ProtocolHold(Fault.OUTPUT)
        else:
            raise ProtocolHold(Fault.FRAME)
    return output if terminal else None


def _review_result(client: ReviewClient, packet: ExecutionPacket,
                   thread: str, turn: str, stopped: Event, on_attention: Callable[[], None],
                   checkout: Path) -> Completion:
    count = 0
    while True:
        _check_attention(client, stopped, on_attention)
        signals = client.next_review_signals(count, stopped)
        count = len(signals)
        _check_attention(client, stopped, on_attention)
        output = _attributed_output(signals, thread, turn)
        if output is not None:
            try:
                safe_output = sanitize_review_paths(output, checkout)
            except ReviewPathError:
                raise _CollectionHold(
                    StartupOutcome.COLLECTION_OUTPUT_FAILED, "Review contains an unapproved machine path.",
                ) from None
            _check_attention(client, stopped, on_attention)
            return Completion(thread, turn, packet.head, safe_output)


def review(
    packet: ExecutionPacket, context: bytes, instructions: bytes, *, workspace: Path,
    managed_env: dict[str, str], before_review: Callable[[str], None],
    on_started: Callable[[str, str], None], interrupted: Callable[[], bool],
    factory: Callable[[Path, dict[str, str], Callable[[], None]], ReviewClient] | None = None,
    on_attention: Callable[[], None] = lambda: None,
    on_startup: Callable[[StartupOutcome], None] = lambda _outcome: None,
    verify_checkout: Callable[[], None] | None = None,
) -> Completion:
    """Review once, with a pre-effect authority callback and private attribution."""
    try:
        material = admit_review_input(packet, workspace, context, instructions)
    except SnapshotError:
        on_startup(StartupOutcome.SNAPSHOT_VALIDATION_FAILED)
        raise ReviewHold("Approved review snapshot is invalid.") from None

    try:
        if {key.upper() for key in managed_env} - _SAFE_ENV or interrupted():
            raise ReviewHold("Managed review environment or deadline is invalid.")
        root = workspace.resolve(strict=True)
    except ReviewHold:
        raise
    except Exception:
        raise ReviewHold("Managed review initialization failed.") from None

    on_startup(StartupOutcome.CHECKOUT_PROOF_CHECKING)
    try:
        if verify_checkout is None:
            raise ReviewHold("Managed checkout verification is not configured.")
        verify_checkout()
    except Exception:
        on_startup(StartupOutcome.CHECKOUT_PROOF_FAILED)
        raise ReviewHold("Managed checkout proof failed.") from None

    if interrupted():
        raise ReviewHold("Managed review deadline expired before SDK startup.")

    acknowledged = Event()

    def permission_attention() -> None:
        # Preserve the existing permission marker even if diagnostics fail.
        try:
            on_attention()
        finally:
            on_startup(
                StartupOutcome.COLLECTION_PERMISSION_REQUESTED if acknowledged.is_set()
                else StartupOutcome.PERMISSION_REQUESTED,
            )

    on_startup(StartupOutcome.SDK_STARTING)
    try:
        client = (factory(root, managed_env, permission_attention) if factory is not None
                  else open_review_client(root, managed_env, permission_attention, interrupted))
    except Exception:
        on_startup(StartupOutcome.SDK_START_FAILED)
        raise ReviewHold("Managed SDK startup failed.") from None

    stop = Event()
    done = Event()
    failure: StartupOutcome | None = StartupOutcome.SDK_START_FAILED
    operation_failed = False

    def hold_for_permission() -> None:
        nonlocal failure
        if client.approval_requested():
            failure = None
            permission_attention()
            raise ReviewHold("Review paused at a permission request.")

    try:
        client.start()
        hold_for_permission()
        failure = StartupOutcome.INITIALIZATION_FAILED
        on_startup(StartupOutcome.INITIALIZATION_STARTING)
        info = client.initialize()
        hold_for_permission()
        _verify_runtime(info, packet.runtime)
        failure = StartupOutcome.MANAGED_ACCOUNT_FAILED
        on_startup(StartupOutcome.MANAGED_ACCOUNT_CHECKING)
        account = client.account_read()
        hold_for_permission()
        if account.account is None or account.account.root.type != "chatgpt":
            raise ReviewHold("Existing managed ChatGPT account is unavailable.")
        failure = StartupOutcome.THREAD_START_FAILED
        on_startup(StartupOutcome.THREAD_STARTING)
        response = client.thread_start(material.thread)
        hold_for_permission()
        failure = StartupOutcome.THREAD_VALIDATION_FAILED
        on_startup(StartupOutcome.THREAD_VALIDATING)
        thread = _verify_thread(response, packet, root)
        failure = None
        hold_for_permission()
        if interrupted():
            raise ReviewHold("Managed review needs attention before dispatch.")
        on_startup(StartupOutcome.PRE_REVIEW_CHECKING)
        before_review(thread)
        hold_for_permission()
        if interrupted():
            raise ReviewHold("Review deadline or permission hold reached before dispatch.")
        failure = StartupOutcome.REVIEW_DISPATCH_UNKNOWN
        started = client.review_start(material.review(thread))
        turn = started.turn.id
        if (started.review_thread_id != thread or not _ID.fullmatch(turn)
            or started.turn.status != TurnStatus.in_progress):
            raise ProtocolHold(Fault.ACK)
        del started  # The pinned ack can echo the full target; retain only its binding.
        on_started(thread, turn)
        acknowledged.set()
        failure = StartupOutcome.COLLECTION_RUNTIME_FAILED

        def monitor() -> None:
            while not done.wait(0.05):
                try:
                    if not interrupted():
                        continue
                    stop.set()
                    interrupt_known(client, thread, turn)
                except Exception:
                    stop.set()
                return

        Thread(target=monitor, daemon=True, name="lighthouse-review-interrupt").start()
        completed = _review_result(client, packet, thread, turn, stop, permission_attention, root)
    except ProtocolHold as exc:
        operation_failed = True
        if acknowledged.is_set():
            code = _COLLECTION_CODES.get(exc.fault, StartupOutcome.COLLECTION_RUNTIME_FAILED)
        elif failure == StartupOutcome.REVIEW_DISPATCH_UNKNOWN:
            code = _DISPATCH_CODES.get(exc.fault, failure)
        else:
            code = failure or StartupOutcome.INITIALIZATION_FAILED
        on_startup(code)
        if exc.fault == Fault.PERMISSION:
            raise ReviewHold("Review paused at a permission request.") from None
        raise ReviewHold("Managed review protocol held; acceptance may be unknown.") from None
    except ReviewHold as exc:
        operation_failed = True
        if isinstance(exc, (_ThreadHold, _CollectionHold)):
            failure = exc.outcome
        if failure is not None:
            on_startup(failure)
        raise
    except Exception:
        operation_failed = True
        if failure is not None:
            on_startup(failure)
        raise ReviewHold("Managed review failed or its acceptance is unknown.") from None
    finally:
        done.set()
        try:
            try:
                on_startup(StartupOutcome.CLEANUP_STARTING)
            finally:
                client.close()
            on_startup(StartupOutcome.CLEANUP_COMPLETED)
        except Exception:
            try:
                on_startup(StartupOutcome.CLEANUP_FAILED)
            except Exception:
                # Do not replace an already recorded primary failure.
                pass
            if not operation_failed:
                raise ReviewHold("Managed review local shutdown is not confirmed.") from None

    try:
        _check_attention(client, stop, permission_attention)
        if interrupted():
            raise ProtocolHold(Fault.INTERRUPTED)
        final = client.final_review_signals()
        if final is not None and _attributed_output(final, completed.thread_id, completed.turn_id) is None:
            raise ProtocolHold(Fault.OUTPUT)
    except ProtocolHold as exc:
        on_startup(_COLLECTION_CODES.get(exc.fault, StartupOutcome.COLLECTION_RUNTIME_FAILED))
        raise ReviewHold("Managed review protocol held during shutdown.") from None
    except _CollectionHold as exc:
        on_startup(exc.outcome)
        raise
    return completed
