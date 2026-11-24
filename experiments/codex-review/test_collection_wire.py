"""Offline persistent-history tests through the installed read method and real worker."""
import hashlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import sdk_worker
from authorization import canonical_packet
from live_stage import CHALLENGE, read_signal, run_stage
from openai_codex.client import CodexClient, CodexConfig
from openai_codex.errors import InvalidRequestError, TransportClosedError
from openai_codex.generated.v2_all import (
    GetAccountResponse,
    ReviewStartResponse,
    ThreadReadResponse,
    ThreadStartResponse,
)
from openai_codex.models import JsonObject
from test_live_stage import ENV, _verify, _workspace
from test_sdk_worker import FakeClient

_READ = CodexClient.thread_read


@pytest.mark.parametrize(("case", "expected"), (
    ("legacy", None),
    ("paginated", None),
    ("visibility-timeout", "collection_output_failed"),
    ("effective-ephemeral", None),
    ("rpc-ephemeral-rejection", "collection_read_failed"),
    ("transport-loss", "collection_read_failed"),
    ("foreign", "collection_thread_id_mismatch"),
    ("history-mode-mismatch", "collection_thread_mode_mismatch"),
    ("extra", "collection_turn_count_mismatch"),
    ("wrong-turn", "collection_turn_id_mismatch"),
    ("disappeared", "collection_turn_disappeared"),
    ("dematerialized", "collection_turn_disappeared"),
    ("late-permission", "collection_thread_id_mismatch"),
    ("runtime", "collection_runtime_failed"),
    ("interrupted", "collection_interrupted"),
    ("ambiguous-output", "collection_output_failed"),
    ("provider-fallback", "collection_output_failed"),
    ("permission", "collection_permission_requested"),
))
def test_actual_read_wrapper_preserves_one_attributed_review_and_fixed_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, expected: str | None,
) -> None:
    control, packet = _workspace(tmp_path)
    workspace = tmp_path / "verified"
    managed = tmp_path / "synthetic-private-home"
    managed.mkdir()
    env = {**ENV, "CODEX_HOME": str(managed)}
    run_stage("verifier", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
              verify_call=_verify)
    effects: list[str] = []

    class InertRPC(FakeClient):
        def __init__(
            self, config: CodexConfig, *, approval_handler: Callable[[str, JsonObject], JsonObject],
        ) -> None:
            super().__init__(workspace, "null-git")
            assert config.cwd == str(workspace)
            self.reads = 0
            self.receive_approval = approval_handler

        def account_read(self, _params: JsonObject | None = None) -> GetAccountResponse:
            return super().account_read()

        def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
            assert parameters["ephemeral"] is False
            result = super().thread_start(parameters)
            if case == "effective-ephemeral":
                result.thread.ephemeral = True
            return result.model_copy(update={"model": packet.model})

        def thread_read(self, thread_id: str, *, include_turns: bool = False) -> ThreadReadResponse:
            return _READ(cast(CodexClient, self), thread_id, include_turns=include_turns)

        def request(
            self, method: str, params: JsonObject | None, *,
            response_model: type[ThreadReadResponse] | type[ReviewStartResponse],
        ) -> ThreadReadResponse | ReviewStartResponse:
            if method == "review/start":
                assert params is not None and response_model is ReviewStartResponse
                effects.append("start")
                self.events.append("intent")
                assert params["delivery"] == "inline" and params["threadId"] == "fixture-thread"
                self.review_start(params)
                self.events.append("ack")
                return response_model.model_validate({
                    "reviewThreadId": "fixture-thread",
                    "turn": {"id": "fixture-turn", "status": "inProgress", "rootTurnId": None,
                             "items": [{"type": "userMessage", "id": "fixture-turn", "content": [
                                 {"type": "text", "text": "Fixture review", "text_elements": []},
                             ]}]},
                })
            assert method == "thread/read" and response_model is ThreadReadResponse
            assert params == {"threadId": "fixture-thread", "includeTurns": True}
            effects.append("read")
            self.reads += 1
            if case == "rpc-ephemeral-rejection":
                raise InvalidRequestError(-32600, "ephemeral threads do not support includeTurns")
            if case == "transport-loss":
                raise TransportClosedError("synthetic private text")
            if (case == "legacy" and self.reads == 1) or (case == "dematerialized" and self.reads == 2):
                raise InvalidRequestError(
                    -32600, "thread fixture-thread is not materialized yet; "
                    "includeTurns is unavailable before first user message",
                )
            thread = self.thread([])
            thread["historyMode"] = "paginated" if case == "paginated" else "legacy"
            entered = {"id": "entered-fixture", "type": "enteredReviewMode", "review": "Fixture review"}
            result = {"id": "result", "type": "exitedReviewMode", "review": "Fixture result."}
            if case == "provider-fallback":
                result["review"] = "Reviewer failed to output a response."
            current = {
                "id": "fixture-turn", "status": "completed", "itemsView": "full",
                "items": [entered, result],
            }
            thread["turns"] = [current]
            pending = (
                (case in ("paginated", "disappeared", "dematerialized") and self.reads == 1)
                or (case == "legacy" and self.reads == 3)
            )
            if pending:
                current.update(status="inProgress", items=[entered])
                thread["status"] = {"type": "active", "activeFlags": []}
            if case == "visibility-timeout" or (case == "legacy" and self.reads == 2):
                thread["turns"] = []
            if case in ("foreign", "late-permission"):
                thread["id"] = "unrelated-thread-not-retained"
            if case == "history-mode-mismatch":
                thread["ephemeral"] = True
            if case == "wrong-turn":
                current["id"] = "unrelated-turn-not-retained"
            if case == "extra":
                thread["turns"] = [current, {**current, "id": "unrelated-turn-not-retained"}]
            if case == "disappeared" and self.reads == 2:
                thread["turns"] = []
            if case == "runtime":
                thread["status"] = {"type": "systemError"}
            if case == "interrupted":
                current["status"] = "interrupted"
            if case == "ambiguous-output":
                current["items"] = [entered, result, {**result, "id": "extra-result"}]
            if case == "permission":
                thread["status"] = {"type": "active", "activeFlags": ["waitingOnApproval"]}
            return response_model.model_validate({"thread": thread, "readState": None})

        def close(self) -> None:
            effects.append("close")
            if expected:
                assert read_signal(control / "review.collection.json")["outcome"] == expected
                if case == "late-permission":
                    assert self.receive_approval("item/commandExecution/requestApproval", {}) == {"decision": "decline"}
                    assert read_signal(control / "review.attention.json")["reason"] == "permission-request"
                raise OSError("synthetic private cleanup text")

    monkeypatch.setattr("openai_codex.client.CodexClient", InertRPC)
    monkeypatch.setattr(sdk_worker, "os", SimpleNamespace(environ={}))

    def parent_handoff(_delay: float) -> None:
        run_stage("reverify", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                  verify_call=_verify)
        (control / "reverify.result.json").replace(control / "review.authority.json")

    def stage() -> None:
        run_stage("review", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                  sleep=parent_handoff, checkout_call=lambda *_: None)

    if case in ("legacy", "paginated"):
        stage()
        assert effects == ["start", *(["read"] * (4 if case == "legacy" else 2)), "close"]
        outcome = read_signal(control / "review.result.json")
        assert outcome["turn_id"] == "fixture-turn" and outcome["output"] == "Fixture result."
    else:
        with pytest.raises(sdk_worker.ReviewHold):
            stage()
        assert not (control / "review.result.json").exists()
        if case == "effective-ephemeral":
            assert effects == ["close"]
            assert not (control / "review.intent.json").exists()
        else:
            assert effects.count("start") == 1
            if case == "visibility-timeout":
                assert effects.count("read") == 20
            assert read_signal(control / "review.collection.json") == {
                "challenge": env[CHALLENGE], "head": packet.head,
                "dispatch_id": packet.dispatch_id, "thread_id": "fixture-thread",
                "turn_id": "fixture-turn", "outcome": expected,
                "packet_sha256": hashlib.sha256(canonical_packet(packet)).hexdigest(),
            }
            assert read_signal(control / "review.cleanup.json")["outcome"] == "cleanup_failed"
        assert (control / "review.attention.json").exists() == (case in ("permission", "late-permission"))
        claim = control.parent / "t01-55.claim"
        original = claim.read_bytes()
        with pytest.raises(RuntimeError, match="already claimed"):
            run_stage("verifier", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                      verify_call=_verify)
        assert claim.read_bytes() == original and effects.count("start") <= 1
    assert not (control / "publisher.result.json").exists()
