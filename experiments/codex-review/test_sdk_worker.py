"""Exercise the deferred SDK worker through typed, synthetic App Server replies."""

import hashlib
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
from sdk_worker import Completion, ReviewHold, interrupt_known, review
from test_authorization import packet_for

_CONTEXT = b"Fixture diff. Evidence only."
_INSTRUCTIONS = b"Fixture operator policy."


class FakeClient:
    def __init__(self, root: Path, failure: str = "") -> None:
        self.root = root
        self.failure = failure
        self.events: list[str] = []

    def initialize(self) -> InitializeResponse:
        return InitializeResponse.model_validate({"serverInfo": {
            "version": "0.170.0" if self.failure == "runtime" else "0.171.0",
        }})

    def account_read(self) -> GetAccountResponse:
        account = {"type": "apiKey"} if self.failure == "account" else {
            "type": "chatgpt", "email": None, "planType": "plus",
        }
        return GetAccountResponse.model_validate({"account": account, "requiresOpenaiAuth": True})

    def thread(self, turns: list[object]) -> dict[str, object]:
        return {
            "id": "fixture-thread", "sessionId": "fixture-session", "createdAt": 0,
            "updatedAt": 0, "cwd": str(self.root), "cliVersion": "0.171.0", "ephemeral": True,
            "modelProvider": "openai", "preview": "", "source": "cli",
            "status": {"type": "idle"},
            "turns": turns,
            "gitInfo": {
                "sha": ("b" if self.failure == "head" else "a") * 40,
                "originUrl": "https://github.com/craigholland/lighthouse.git",
            },
        }

    def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
        assert parameters["sandbox"] == "read-only"
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


def run_fake(root: Path, client: FakeClient, context: bytes = _CONTEXT) -> Completion:
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

    def factory(path: Path, env: dict[str, str]) -> FakeClient:
        assert path == root and not env
        return client

    return review(
        packet, context, _INSTRUCTIONS, workspace=root, managed_env={},
        before_review=before, on_started=started, interrupted=lambda: False, factory=factory,
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
    with pytest.raises(ReviewHold, match="attention"):
        review(
            packet, _CONTEXT, _INSTRUCTIONS, workspace=tmp_path, managed_env={},
            before_review=lambda _thread: client.events.append("intent"),
            on_started=lambda _thread, _turn: client.events.append("ack"),
            interrupted=signal.is_set, factory=lambda _path, _env: client,
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
            interrupted=lambda: False, factory=lambda _path, _env: client,
        )
    assert client.events == ["close"]
