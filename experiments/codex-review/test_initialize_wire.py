"""Exercise pinned initialize metadata through the public JSONL wire."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import sdk_worker
from authorization import canonical_packet
from live_stage import CHALLENGE, read_signal, run_stage
from test_collection_wire import InertChild, _item, _terminal
from test_live_stage import ENV, _verify, _workspace
from test_sdk_worker import FakeClient

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

    fixture = FakeClient(workspace, "null-git")
    child: InertChild

    def receive(message: dict[str, object]) -> None:
        method = message["method"]
        if method == "initialized":
            effects.append("initialized")
            return
        message_id = message["id"]
        params = message["params"]
        assert isinstance(params, dict)
        if method == "initialize":
            effects.append("initialize-rpc")
            assert params["clientInfo"]["version"] == "0.1.0"
            response = payload
        elif method == "account/read":
            effects.append("fake-account")
            response = fixture.account_read().model_dump(by_alias=True, mode="json")
        elif method == "thread/start":
            effects.append("fake-thread")
            thread = fixture.thread_start(params).model_copy(update={"model": packet.model})
            response = thread.model_dump(by_alias=True, mode="json")
        else:
            assert method == "review/start"
            effects.append("fake-dispatch")
            child.frame(_item("enteredReviewMode"))
            child.frame(_item("exitedReviewMode"))
            child.frame(_terminal())
            response = {"reviewThreadId": "fixture-thread",
                        "turn": {"id": "fixture-turn", "status": "inProgress", "items": []}}
        child.frame({"id": message_id, "result": response})

    def during_close() -> None:
        effects.append("fake-close")
        if not valid:
            assert read_signal(control / "review.startup.json")["outcome"] == "initialization_failed"

    child = InertChild(receive, during_close=during_close, close_fails=not valid)
    monkeypatch.setattr(sdk_worker, "_launch_app_server", lambda *_: child)
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
