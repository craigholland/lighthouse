"""Exercise the deferred SDK worker through typed, synthetic App Server replies."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from openai_codex.generated.v2_all import (
    GetAccountResponse,
    ReviewStartResponse,
    ThreadReadResponse,
    ThreadStartResponse,
)
from openai_codex.models import InitializeResponse, JsonObject
from sdk_worker import Completion, ReviewHold, StartupOutcome, interrupt_known, review
from snapshots import CONTEXT_LIMIT, INSTRUCTIONS_LIMIT
from test_authorization import packet_for

_FIXTURE_AGENT = "codex_python_sdk/0.171.0 (Windows 10.0.0; x86_64) fixture/1.0"
_CONTEXT = b"Fixture diff. Evidence only."
_INSTRUCTIONS = b"Fixture operator policy."


class FakeClient:
    def __init__(self, root: Path, failure: str = "") -> None:
        self.root = root
        self.failure = failure
        self.events: list[str] = []

    def start(self) -> None:
        if self.failure == "sdk-start":
            raise OSError("private fixture path")

    def initialize(self) -> InitializeResponse:
        if self.failure == "initialize":
            raise OSError("private fixture path")
        if self.failure == "missing-runtime":
            return InitializeResponse.model_validate({"serverInfo": None})
        return InitializeResponse.model_validate({
            "userAgent": _FIXTURE_AGENT.replace("0.171.0", "0.170.0")
            if self.failure == "runtime" else _FIXTURE_AGENT,
            "platformFamily": "windows", "platformOs": "windows",
        })

    def account_read(self) -> GetAccountResponse:
        account = {"type": "apiKey"} if self.failure == "account" else {
            "type": "chatgpt", "email": None, "planType": "plus",
        }
        return GetAccountResponse.model_validate({"account": account, "requiresOpenaiAuth": True})

    def thread(self, turns: list[object]) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": "fixture-thread", "sessionId": "fixture-session", "createdAt": 0,
            "updatedAt": 0, "cwd": str(self.root), "cliVersion": "0.171.0", "ephemeral": self.failure == "ephemeral",
            "modelProvider": "openai", "preview": "", "source": "cli",
            "status": {"type": "idle"},
            "turns": turns,
            "gitInfo": {
                "sha": ("b" if self.failure == "head" else "a") * 40,
                "originUrl": "https://github.com/craigholland/lighthouse.git",
            },
        }
        if self.failure == "missing-git":
            del payload["gitInfo"]
        elif self.failure == "null-git":
            payload["gitInfo"] = None
        elif self.failure == "null-sha":
            payload["gitInfo"] = {"sha": None, "originUrl": "https://github.com/craigholland/lighthouse.git"}
        elif self.failure == "wrong-origin-no-sha":
            payload["gitInfo"] = {"originUrl": "https://github.com/fixture/other"}
        elif self.failure == "wrong-sha-no-origin":
            payload["gitInfo"] = {"sha": "b" * 40}
        elif self.failure == "empty-sha":
            payload["gitInfo"] = {"sha": ""}
        elif self.failure == "invalid-origin-type":
            payload["gitInfo"] = {"originUrl": ["unexpected"]}
        elif self.failure == "absent-git-fields":
            payload["gitInfo"] = {}
        elif self.failure == "null-origin":
            payload["gitInfo"] = {"sha": "a" * 40, "originUrl": None}
        return payload

    def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
        if self.failure == "thread-start":
            raise OSError("private fixture path")
        assert parameters["sandbox"] == "read-only"
        assert parameters["ephemeral"] is False
        assert parameters["approvalPolicy"] == "never"
        assert parameters["approvalsReviewer"] == "user"
        assert parameters["developerInstructions"] and _CONTEXT.decode() not in str(parameters)
        return ThreadStartResponse.model_validate({
            "cwd": str(self.root), "model": (
                "other" if self.failure == "model" else "fixture-model"
            ), "modelProvider": "openai",
            "approvalPolicy": "on-request" if self.failure == "policy" else "never",
            "approvalsReviewer": "user",
            "sandbox": {"type": "readOnly", "networkAccess": self.failure == "network"},
            "thread": self.thread([]),
        })

    def review_start(self, parameters: JsonObject) -> ReviewStartResponse:
        assert parameters["threadId"] == "fixture-thread"
        assert "untrusted evidence" in str(parameters["target"])
        assert self.events == ["intent"]
        self.events.append("start")
        if self.failure == "dropped-ack":
            raise OSError("private fixture path")
        return ReviewStartResponse.model_validate({
            "reviewThreadId": "different" if self.failure == "wrong-ack" else "fixture-thread",
            "turn": {"id": "fixture-turn", "status": "inProgress", "items": []},
        })

    def thread_read(self, thread_id: str) -> ThreadReadResponse:
        assert thread_id == "fixture-thread"
        assert "ack" in self.events
        item = {"id": "result", "type": "exitedReviewMode", "review": "Fixture result."}
        return ThreadReadResponse.model_validate({"thread": self.thread([{
            "id": "different" if self.failure == "wrong-result" else "fixture-turn",
            "status": "interrupted" if self.failure == "interrupted" else "completed",
            "items": [item, item] if self.failure == "duplicate-output" else [item],
        }])})

    def turn_interrupt(self, thread_id: str, turn_id: str) -> None:
        assert (thread_id, turn_id) == ("fixture-thread", "fixture-turn")
        self.events.append("requested-interrupt")

    def approval_requested(self) -> bool:
        return self.failure == "approval"

    def close(self) -> None:
        self.events.append("close")


def run_fake(
    root: Path, client: FakeClient, context: bytes = _CONTEXT, *,
    on_startup: Callable[[StartupOutcome], None] = lambda _outcome: None,
    verify_checkout: Callable[[], None] | None = lambda: None,
    on_factory: Callable[[], None] = lambda: None,
) -> Completion:
    packet = packet_for(root).model_copy(update={
        "context_sha256": hashlib.sha256(_CONTEXT).hexdigest(),
        "instructions_sha256": hashlib.sha256(_INSTRUCTIONS).hexdigest(),
    })

    def before(thread_id: str) -> None:
        assert thread_id == "fixture-thread"
        client.events.append("intent")

    def started(thread_id: str, turn_id: str) -> None:
        assert (thread_id, turn_id) == ("fixture-thread", "fixture-turn")
        client.events.append("ack")

    def factory(path: Path, env: dict[str, str], _attention: Callable[[], None]) -> FakeClient:
        assert path == root and not env
        on_factory()
        return client

    return review(
        packet, context, _INSTRUCTIONS, workspace=root, managed_env={},
        before_review=before, on_started=started, interrupted=lambda: False, factory=factory,
        on_startup=on_startup, verify_checkout=verify_checkout,
    )


def test_worker_preserves_attribution_and_keeps_output_out_of_repr(tmp_path: Path) -> None:
    client = FakeClient(tmp_path)
    completed = run_fake(tmp_path, client)
    assert completed == Completion("fixture-thread", "fixture-turn", "a" * 40, "Fixture result.")
    assert "Fixture result." not in repr(completed)
    assert client.events == ["intent", "start", "ack", "close"]


@pytest.mark.parametrize("failure", ["runtime", "account", "model", "policy", "head",
                                     "network", "approval"])
def test_failed_effective_gate_never_reaches_review(tmp_path: Path, failure: str) -> None:
    client = FakeClient(tmp_path, failure)
    with pytest.raises(ReviewHold):
        run_fake(tmp_path, client)
    assert client.events == ["close"]


@pytest.mark.parametrize("failure", ["dropped-ack", "wrong-ack", "wrong-result",
                                     "duplicate-output", "interrupted"])
def test_unattributed_or_ambiguous_results_hold_without_replay(
    tmp_path: Path, failure: str,
) -> None:
    client = FakeClient(tmp_path, failure)
    with pytest.raises(ReviewHold) as caught:
        run_fake(tmp_path, client)
    assert "private fixture path" not in str(caught.value)
    assert client.events.count("start") == 1
    assert client.events[-1] == "close"


def test_snapshot_mismatch_never_opens_client(tmp_path: Path) -> None:
    client = FakeClient(tmp_path)
    with pytest.raises(ReviewHold):
        run_fake(tmp_path, client, b"changed snapshot")
    assert not client.events


def test_interrupt_needs_both_known_ids(tmp_path: Path) -> None:
    client = FakeClient(tmp_path)
    with pytest.raises(ReviewHold):
        interrupt_known(client, "fixture-thread", "")
    assert not client.events
    interrupt_known(client, "fixture-thread", "fixture-turn")
    assert client.events == ["requested-interrupt"]



def test_cooperative_interrupt_targets_returned_run_only(tmp_path: Path) -> None:
    signal = Event()
    interrupt_sent = Event()

    class BlockingRead(FakeClient):
        def thread_read(self, thread_id: str) -> ThreadReadResponse:
            assert thread_id == "fixture-thread"
            signal.set()
            assert interrupt_sent.wait(2)
            return super().thread_read(thread_id)

        def turn_interrupt(self, thread_id: str, turn_id: str) -> None:
            super().turn_interrupt(thread_id, turn_id)
            interrupt_sent.set()

    client = BlockingRead(tmp_path)
    packet = packet_for(tmp_path).model_copy(update={
        "context_sha256": hashlib.sha256(_CONTEXT).hexdigest(),
        "instructions_sha256": hashlib.sha256(_INSTRUCTIONS).hexdigest(),
    })
    with pytest.raises(ReviewHold, match="remote outcome is unknown"):
        review(
            packet, _CONTEXT, _INSTRUCTIONS, workspace=tmp_path, managed_env={},
            before_review=lambda _thread: client.events.append("intent"),
            on_started=lambda _thread, _turn: client.events.append("ack"),
            interrupted=signal.is_set, factory=lambda _path, _env, _attention: client,
            verify_checkout=lambda: None,
        )
    assert client.events == ["intent", "start", "ack", "requested-interrupt", "close"]


def test_holds_before_review_if_recheck_denies(tmp_path: Path) -> None:
    client = FakeClient(tmp_path)
    packet = packet_for(tmp_path).model_copy(update={
        "context_sha256": hashlib.sha256(_CONTEXT).hexdigest(),
        "instructions_sha256": hashlib.sha256(_INSTRUCTIONS).hexdigest(),
    })

    def before(_thread: str) -> None:
        raise ReviewHold("The review authority changed.")

    with pytest.raises(ReviewHold, match="authority changed"):
        review(
            packet, _CONTEXT, _INSTRUCTIONS, workspace=tmp_path, managed_env={},
            before_review=before, on_started=lambda _thread, _turn: pytest.fail("dispatched"),
            interrupted=lambda: False, factory=lambda _path, _env, _attention: client,
            verify_checkout=lambda: None,
        )
    assert client.events == ["close"]



@pytest.mark.parametrize(("failure", "expected"), [
    ("sdk-start", StartupOutcome.SDK_START_FAILED),
    ("initialize", StartupOutcome.INITIALIZATION_FAILED),
    ("missing-runtime", StartupOutcome.INITIALIZATION_FAILED),
    ("runtime", StartupOutcome.INITIALIZATION_FAILED),
    ("account", StartupOutcome.MANAGED_ACCOUNT_FAILED),
    ("thread-start", StartupOutcome.THREAD_START_FAILED),
    ("model", StartupOutcome.THREAD_VALIDATION_FAILED),
    ("policy", StartupOutcome.THREAD_POLICY_FAILED),
    ("network", StartupOutcome.THREAD_POLICY_FAILED),
    ("wrong-origin-no-sha", StartupOutcome.GIT_IDENTITY_MISMATCH),
    ("wrong-sha-no-origin", StartupOutcome.GIT_IDENTITY_MISMATCH),
    ("empty-sha", StartupOutcome.GIT_IDENTITY_MISMATCH),
    ("invalid-origin-type", StartupOutcome.THREAD_START_FAILED),
    ("head", StartupOutcome.GIT_IDENTITY_MISMATCH),
    ("approval", StartupOutcome.PERMISSION_REQUESTED),
])
def test_worker_classifies_before_cleanup(
    tmp_path: Path, failure: str, expected: StartupOutcome,
) -> None:
    client = FakeClient(tmp_path, failure)

    def on_startup(outcome: StartupOutcome) -> None:
        client.events.append(outcome.value)

    with pytest.raises(ReviewHold) as caught:
        run_fake(tmp_path, client, on_startup=on_startup)
    assert "private fixture path" not in str(caught.value)
    assert client.events[-4:] == [
        expected.value, "cleanup_starting", "close", "cleanup_completed",
    ]
    assert "intent" not in client.events
    assert "start" not in client.events


def test_root_cause_persisted_before_failing_close(tmp_path: Path) -> None:
    class FailingClose(FakeClient):
        def close(self) -> None:
            assert self.events == [
                "checkout_proof_checking", "sdk_starting", "initialization_starting", "initialization_failed",
                "cleanup_starting",
            ]
            raise OSError("private fixture path")

    client = FailingClose(tmp_path, "runtime")

    with pytest.raises(ReviewHold, match="runtime does not match"):
        run_fake(tmp_path, client, on_startup=lambda stage: client.events.append(stage.value))
    assert client.events[-2:] == ["cleanup_starting", "cleanup_failed"]


def test_successful_run_records_checkpoints_without_adding_effects(tmp_path: Path) -> None:
    client = FakeClient(tmp_path)
    outcomes: list[StartupOutcome] = []
    run_fake(tmp_path, client, on_startup=outcomes.append)
    assert outcomes == [
        StartupOutcome.CHECKOUT_PROOF_CHECKING,
        StartupOutcome.SDK_STARTING,
        StartupOutcome.INITIALIZATION_STARTING,
        StartupOutcome.MANAGED_ACCOUNT_CHECKING,
        StartupOutcome.THREAD_STARTING,
        StartupOutcome.THREAD_VALIDATING,
        StartupOutcome.PRE_REVIEW_CHECKING,
        StartupOutcome.CLEANUP_STARTING,
        StartupOutcome.CLEANUP_COMPLETED,
    ]
    assert client.events == ["intent", "start", "ack", "close"]



@pytest.mark.parametrize("annotation", [
    "missing-git", "null-git", "null-sha", "null-origin", "absent-git-fields",
])
def test_review_requires_initial_proof_but_allows_absent_annotation(
    tmp_path: Path, annotation: str,
) -> None:
    class CheckedStart(FakeClient):
        def start(self) -> None:
            assert checks == ["checkout", "factory"]

    checks: list[str] = []
    client = CheckedStart(tmp_path, annotation)
    assert run_fake(
        tmp_path, client, verify_checkout=lambda: checks.append("checkout"),
        on_factory=lambda: checks.append("factory"),
    ).output == "Fixture result."
    assert checks == ["checkout", "factory"]


@pytest.mark.parametrize("configure_verifier", [False, True])
def test_failed_or_unconfigured_proof_stops_before_sdk_factory(
    tmp_path: Path, configure_verifier: bool,
) -> None:
    def deny() -> None:
        raise ValueError("private fixture details")

    client = FakeClient(tmp_path)
    outcomes: list[StartupOutcome] = []
    with pytest.raises(ReviewHold, match="Managed checkout proof failed") as caught:
        run_fake(
            tmp_path, client, on_startup=outcomes.append,
            verify_checkout=deny if configure_verifier else None,
            on_factory=lambda: pytest.fail("SDK constructed without checkout proof"),
        )
    assert not client.events
    assert outcomes == [
        StartupOutcome.CHECKOUT_PROOF_CHECKING,
        StartupOutcome.CHECKOUT_PROOF_FAILED,
    ]
    assert "private fixture details" not in str(caught.value)



@pytest.mark.parametrize(("field", "fixture"), [
    (field, fixture)
    for field in ("context", "instructions")
    for fixture in ("empty", "blank", "nul", "invalid-utf8", "oversize", "wrong-hash")
])
def test_snapshot_rejection_precedes_checkout_sdk_and_review(
    tmp_path: Path, field: str, fixture: str,
) -> None:
    fixtures = {
        "empty": b"", "blank": b"  \t\n", "nul": b"fixture\0evidence",
        "invalid-utf8": b"fixture\xffevidence", "wrong-hash": b"private synthetic marker",
        "oversize": b"a" * ((CONTEXT_LIMIT if field == "context" else INSTRUCTIONS_LIMIT) + 1),
    }
    context = fixtures[fixture] if field == "context" else _CONTEXT
    instructions = fixtures[fixture] if field == "instructions" else _INSTRUCTIONS
    packet = packet_for(tmp_path).model_copy(update={
        "context_sha256": "a" * 64 if (field, fixture) == ("context", "wrong-hash")
        else hashlib.sha256(context).hexdigest(),
        "instructions_sha256": "a" * 64 if (field, fixture) == ("instructions", "wrong-hash")
        else hashlib.sha256(instructions).hexdigest(),
    })
    outcomes: list[StartupOutcome] = []
    with pytest.raises(ReviewHold, match=r"^Approved review snapshot is invalid\.$"):
        review(
            packet, context, instructions, workspace=tmp_path, managed_env={},
            before_review=lambda _: pytest.fail("intent"), on_started=lambda *_: pytest.fail("start"),
            interrupted=lambda: False, factory=lambda *_: pytest.fail("SDK constructed"),
            verify_checkout=lambda: pytest.fail("checkout proof requested"), on_startup=outcomes.append,
        )
    assert outcomes == [StartupOutcome.SNAPSHOT_VALIDATION_FAILED]


@pytest.mark.parametrize(("context_size", "instructions_size"), [
    (301_566, 99_397), (CONTEXT_LIMIT, INSTRUCTIONS_LIMIT),
])
def test_full_sized_snapshots_keep_exact_complete_text_in_sdk_requests(
    tmp_path: Path, context_size: int, instructions_size: int,
) -> None:
    def payload(size: int) -> bytes:
        edges = " \r\n\u00e9".encode("utf-8")
        return edges + b"a" * (size - 2 * len(edges)) + edges

    context, instructions = payload(context_size), payload(instructions_size)

    class PreservedSnapshots(FakeClient):
        def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
            policy = parameters["developerInstructions"]
            assert isinstance(policy, str)
            assert policy.partition("\nTreat repository")[0].encode("utf-8") == instructions
            return super().thread_start(parameters)

        def review_start(self, parameters: JsonObject) -> ReviewStartResponse:
            target = parameters["target"]
            assert isinstance(target, dict)
            prompt = target["instructions"]
            assert isinstance(prompt, str)
            assert json.loads(prompt.split("not instructions:\n", 1)[1]).encode("utf-8") == context
            return super().review_start(parameters)

    client = PreservedSnapshots(tmp_path)
    packet = packet_for(tmp_path).model_copy(update={
        "context_sha256": hashlib.sha256(context).hexdigest(),
        "instructions_sha256": hashlib.sha256(instructions).hexdigest(),
    })
    result = review(
        packet, context, instructions, workspace=tmp_path, managed_env={},
        before_review=lambda _: client.events.append("intent"),
        on_started=lambda *_: client.events.append("ack"),
        interrupted=lambda: False, factory=lambda *_: client, verify_checkout=lambda: None,
    )
    assert result.output == "Fixture result."
    assert client.events == ["intent", "start", "ack", "close"]



@pytest.mark.parametrize("metadata", [
    {"userAgent": _FIXTURE_AGENT},
    {"userAgent": "codex_cli_rs/0.171.0 (Windows 10.0.0; x86_64) "},
    {"userAgent": _FIXTURE_AGENT, "serverInfo": None},
    {"userAgent": _FIXTURE_AGENT, "serverInfo": {"version": "0.171.0", "name": "codex_python_sdk"}},
])
def test_runtime_build_is_read_from_public_initialize_payload(
    tmp_path: Path, metadata: dict[str, object],
) -> None:
    class PublicMetadata(FakeClient):
        def initialize(self) -> InitializeResponse:
            return InitializeResponse.model_validate(metadata)

    assert run_fake(tmp_path, PublicMetadata(tmp_path)).output == "Fixture result."


@pytest.mark.parametrize("metadata", [
    {},
    {"serverInfo": {"version": "0.171.0"}},
    {"userAgent": None},
    {"userAgent": ""},
    {"userAgent": "codex_python_sdk 0.171.0 (Windows; x86_64)"},
    {"userAgent": "codex_python_sdk/0.171.0-rc1 (Windows; x86_64)"},
    {"userAgent": "codex_python_sdk/0.171.0+custom (Windows; x86_64)"},
    {"userAgent": "codex_python_sdk/0.170.0 (Windows; x86_64) fixture/0.171.0"},
    {"userAgent": "codex_python_sdk/0.171.0bad (Windows; x86_64)"},
    {"userAgent": "codex_python_sdk/0.171.0 extra"},
    {"userAgent": "codex_python_sdk/0.171.0 (Windows; x86_64)broken)"},
    {"userAgent": _FIXTURE_AGENT + "\n"},
    {"userAgent": _FIXTURE_AGENT, "serverInfo": {"version": "0.170.0"}},
    {"userAgent": _FIXTURE_AGENT, "serverInfo": {"version": ""}},
    {"userAgent": _FIXTURE_AGENT, "serverInfo": {"name": "other_product"}},
])
def test_invalid_runtime_metadata_stops_before_account_thread_and_review(
    tmp_path: Path, metadata: dict[str, object],
) -> None:
    class RejectedMetadata(FakeClient):
        def initialize(self) -> InitializeResponse:
            return InitializeResponse.model_validate(metadata)

        def account_read(self) -> GetAccountResponse:
            pytest.fail("account operation must not follow invalid initialization")

    client = RejectedMetadata(tmp_path)
    outcomes: list[StartupOutcome] = []
    with pytest.raises(ReviewHold, match=r"^Effective App Server runtime does not match\.$"):
        run_fake(tmp_path, client, on_startup=outcomes.append)
    assert outcomes == [
        StartupOutcome.CHECKOUT_PROOF_CHECKING,
        StartupOutcome.SDK_STARTING,
        StartupOutcome.INITIALIZATION_STARTING,
        StartupOutcome.INITIALIZATION_FAILED,
        StartupOutcome.CLEANUP_STARTING,
        StartupOutcome.CLEANUP_COMPLETED,
    ]
    assert client.events == ["close"]
