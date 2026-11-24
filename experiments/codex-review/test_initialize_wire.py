"""Exercise the pinned SDK initialize method against an inert RPC double."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import sdk_worker
from authorization import canonical_packet
from live_stage import CHALLENGE, read_signal, run_stage
from openai_codex.client import CodexClient, CodexConfig
from openai_codex.generated.v2_all import (
    GetAccountResponse,
    ReviewStartResponse,
    ThreadReadResponse,
    ThreadStartResponse,
)
from openai_codex.models import InitializeResponse, JsonObject
from test_live_stage import ENV, _verify, _workspace
from test_sdk_worker import FakeClient

_INITIALIZE = CodexClient.initialize
_UA = "codex_python_sdk/0.171.0 (Windows 10.0.0; x86_64) fixture/1.0"


@pytest.mark.parametrize(("ua", "server", "valid"), (
    (_UA, None, True),
    (_UA, {"name": "codex_python_sdk", "version": "0.171.0"}, True),
    (None, {"name": "codex_python_sdk", "version": "0.171.0"}, False),
    ("fixture/7.7.7 (Windows 10.0.0; x86_64) fixture/1.0", None, False),
    ("fixture/0.171.0-alpha.1 (Windows 10.0.0; x86_64) fixture/1.0", None, False),
    ("fixture/0.171.0+metadata (Windows 10.0.0; x86_64) fixture/1.0", None, False),
    ("fixture 0.171.0", None, False),
    (_UA, {"name": "codex_python_sdk", "version": "0.170.0"}, False),
), ids=("raw-wire", "consistent-supplement", "missing-ua", "echoed-client", "prerelease",
        "build-suffix", "malformed", "conflicting-version"))
def test_pinned_initialize_method_and_worker_share_effective_runtime_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ua: str | None,
    server: dict[str, str] | None, valid: bool,
) -> None:
    control, packet = _workspace(tmp_path)
    workspace = tmp_path / "verified"
    managed = tmp_path / "synthetic-managed-home"
    managed.mkdir()
    env = {**ENV, "CODEX_HOME": str(managed)}
    run_stage("verifier", control, env=env, clock=lambda: 102, parent_pid=lambda: 123,
              verify_call=_verify)
    effects: list[str] = []
    payload: dict[str, object] = {
        "codexHome": str(managed), "platformFamily": "windows", "platformOs": "windows",
    }
    if ua is not None:
        payload["userAgent"] = ua
    if server is not None:
        payload["serverInfo"] = server

    class InertRPC(FakeClient):
        def __init__(self, config: CodexConfig, **_unused: object) -> None:
            super().__init__(workspace, "null-git")
            self.config = config
            self.config.client_version = "7.7.7"

        def initialize(self) -> InitializeResponse:
            return _INITIALIZE(cast(CodexClient, self))

        def request(
            self, method: str, params: JsonObject | None, *,
            response_model: type[InitializeResponse] | type[ReviewStartResponse],
        ) -> InitializeResponse | ReviewStartResponse:
            if method == "initialize":
                assert response_model is InitializeResponse and params is not None
                assert isinstance(params["clientInfo"], dict)
                assert params["clientInfo"]["version"] == "7.7.7"
                effects.append("initialize-rpc")
                return response_model.model_validate(payload)
            assert method == "review/start" and response_model is ReviewStartResponse
            assert params is not None
            effects.append("fake-dispatch")
            self.events.append("intent")
            ack = self.review_start(params)
            self.events.append("ack")
            return ack

        def notify(self, method: str, params: JsonObject | None) -> None:
            assert method == "initialized" and params is None
            effects.append("initialized")

        def account_read(self, _params: JsonObject | None = None) -> GetAccountResponse:
            effects.append("fake-account")
            return super().account_read()

        def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
            effects.append("fake-thread")
            return super().thread_start(parameters).model_copy(update={"model": packet.model})

        def thread_read(self, thread_id: str, *, include_turns: bool = True) -> ThreadReadResponse:
            assert include_turns
            return super().thread_read(thread_id)

        def close(self) -> None:
            effects.append("fake-close")
            if not valid:
                assert read_signal(control / "review.startup.json")["outcome"] == "initialization_failed"
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

    if valid:
        stage()
        assert effects == ["initialize-rpc", "initialized", "fake-account", "fake-thread",
                           "fake-dispatch", "fake-close"]
        assert read_signal(control / "review.result.json")["head"] == packet.head
    else:
        with pytest.raises(sdk_worker.ReviewHold):
            stage()
        assert effects == ["initialize-rpc", "initialized", "fake-close"]
        assert read_signal(control / "review.startup.json") == {
            "challenge": env[CHALLENGE], "head": packet.head, "dispatch_id": packet.dispatch_id,
            "packet_sha256": hashlib.sha256(canonical_packet(packet)).hexdigest(),
            "outcome": "initialization_failed",
        }
        assert read_signal(control / "review.cleanup.json")["outcome"] == "cleanup_failed"
        assert not any((control / name).exists() for name in (
            "review.ready.json", "review.intent.json", "review.started.json", "review.result.json",
        ))
    assert not (control / "publisher.result.json").exists()
