"""Test the private permission disposition across SDK, child and parent boundaries."""

import hashlib
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
import sdk_worker
from authorization import canonical_packet
from live import Stage, run
from live_stage import CHALLENGE, read_signal, run_stage
from openai_codex.client import CodexConfig
from openai_codex.generated.v2_all import (
    GetAccountResponse,
    ReviewStartResponse,
    ThreadReadResponse,
    ThreadStartResponse,
)
from openai_codex.models import JsonObject
from supervisor import Role
from test_live import Job, _operator_request
from test_live_stage import ENV, _verify, _workspace
from test_sdk_worker import FakeClient


@pytest.mark.parametrize("permission", [True, False])
def test_composed_hold_records_only_permission_attention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permission: bool,
) -> None:
    env, _ = _operator_request(tmp_path)
    roles: list[Stage] = []
    actual_review = sdk_worker.review

    class Client(FakeClient):
        def close(self) -> None:
            if permission:
                [attention] = (tmp_path / "receipt").glob("*/review.attention.json")
                assert read_signal(attention)["reason"] == "permission-request"
            raise OSError("synthetic private provider detail")

    def fake_client(path: Path, _env: dict[str, str], _attention: Callable[[], None]) -> Client:
        return Client(path, "approval" if permission else "runtime")

    monkeypatch.setattr(sdk_worker, "review", partial(actual_review, factory=fake_client))

    class StageJob(Job):
        def start(self, role: Stage, control: Path, environment: dict[str, str]) -> None:
            if role not in (Role.VERIFIER, Role.REVIEW):
                pytest.fail("A held review cannot reach another role")
            self.roles.append(role)
            self.role, self.control = role, control
            if role == Role.REVIEW:
                primary = "permission request" if permission else "runtime does not match"
                with pytest.raises(sdk_worker.ReviewHold, match=primary):
                    run_stage("review", control, env=environment, clock=lambda: 0.0,
                              parent_pid=os.getpid)
            else:
                run_stage("verifier", control, env=environment, clock=lambda: 0.0,
                          parent_pid=os.getpid, verify_call=_verify)

        def worker_exited(self) -> bool:
            return True

    assert run(0, command="fixture-command", environ=env, clock=lambda: 0.0,
               sleep=lambda _: None, factory=lambda: StageJob(roles, True)) == 1
    assert roles == [Role.VERIFIER, Role.REVIEW]
    [control] = (tmp_path / "receipt").glob("t01-private-*")
    assert not (control / "review.result.json").exists()
    assert not (control / "review.shutdown.json").exists()
    primary_diagnostic = control / "review.startup.json"
    cleanup_diagnostic = control / "review.cleanup.json"
    startup = read_signal(primary_diagnostic)
    cleanup = read_signal(cleanup_diagnostic)
    assert startup["outcome"] == ("permission_requested" if permission else "initialization_failed")
    assert cleanup["outcome"] == "cleanup_failed"
    assert {k: v for k, v in startup.items() if k != "outcome"} == {
        k: v for k, v in cleanup.items() if k != "outcome"
    }
    assert all("private provider detail" not in path.read_text(encoding="utf-8")
               for path in (primary_diagnostic, cleanup_diagnostic))
    attention = control / "review.attention.json"
    assert attention.exists() == permission
    if permission:
        result = read_signal(attention)
        assert result["reason"] == "permission-request" and result["next_actor"] == "owner"
        assert "private provider detail" not in attention.read_text(encoding="utf-8")


@pytest.mark.parametrize("startup", [True, False])
def test_receiver_persists_attention_without_waiting_for_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, startup: bool,
) -> None:
    control, packet = _workspace(tmp_path)
    workspace = tmp_path / "verified"
    managed = tmp_path / "managed-fake"
    managed.mkdir()
    env = {**ENV, "CODEX_HOME": str(managed)}
    run_stage("verifier", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
              verify_call=_verify)

    blocked, release = Event(), Event()

    class Client(FakeClient):
        def __init__(
            self, config: CodexConfig, *,
            approval_handler: Callable[[str, JsonObject | None], JsonObject],
        ) -> None:
            assert config.cwd == str(workspace)
            super().__init__(workspace)
            self.receive_approval = approval_handler
            clients.append(self)

        def start(self) -> None:
            if startup:
                self.request_permission()
                assert (control / "review.attention.json").is_file()

        def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
            return super().thread_start(parameters).model_copy(update={"model": packet.model})

        def account_read(self, _parameters: JsonObject | None = None) -> GetAccountResponse:
            return super().account_read()

        def request(
            self, method: str, parameters: JsonObject, *, response_model: type[ReviewStartResponse],
        ) -> ReviewStartResponse:
            assert method == "review/start" and response_model is ReviewStartResponse
            return self.review_start(parameters)

        def review_start(self, parameters: JsonObject) -> ReviewStartResponse:
            self.events.append("intent")
            started = super().review_start(parameters)
            self.events.append("ack")
            return started

        def thread_read(self, thread_id: str, *, include_turns: bool = True) -> ThreadReadResponse:
            assert include_turns
            blocked.set()
            assert release.wait(5), "test must release its fake RPC"
            return super().thread_read(thread_id)

        def request_permission(self) -> None:
            assert self.receive_approval(
                "item/permissions/requestApproval", {"path": "private synthetic provider data"},
            ) == {"permissions": {}, "scope": "turn"}

    clients: list[Client] = []
    monkeypatch.setattr("openai_codex.client.CodexClient", Client)
    monkeypatch.setattr(sdk_worker, "os", SimpleNamespace(environ={}))

    def parent_handoff(_delay: float) -> None:
        run_stage("reverify", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                  verify_call=_verify)
        (control / "reverify.result.json").replace(control / "review.authority.json")

    def review_role() -> None:
        with pytest.raises(sdk_worker.ReviewHold, match="permission"):
            run_stage("review", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
                      sleep=parent_handoff)

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(review_role)
        try:
            if not startup:
                assert blocked.wait(2), "fake review did not reach its blocked synchronous RPC"
                assert not worker.done()
                assert not (control / "review.attention.json").exists()
                clients[0].request_permission()
                clients[0].request_permission()
                assert not worker.done() and not release.is_set()
            else:
                worker.result(timeout=2)
                assert not blocked.is_set()
            assert read_signal(control / "review.attention.json") == {
                "ok": True,
                "challenge": env[CHALLENGE],
                "head": packet.head,
                "packet_sha256": hashlib.sha256(canonical_packet(packet)).hexdigest(),
                "reason": "permission-request",
                "next_actor": "owner",
            }
            assert not (control / "review.result.json").exists()
        finally:
            release.set()
        worker.result(timeout=2)

    assert not (control / "review.result.json").exists()
    assert not (control / "publisher.result.json").exists()
