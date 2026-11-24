"""Offline parent-to-worker verification for pre-dispatch diagnostic holds."""

import hashlib
import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
import sdk_worker
from authorization import ExecutionPacket, VerifiedExecution, canonical_packet
from live import Stage, run
from live_stage import CHALLENGE, Request, read_signal, run_stage
from openai_codex.generated.v2_all import ReviewStartResponse, ThreadStartResponse
from openai_codex.models import JsonObject
from supervisor import Role
from test_live import Job, _operator_request
from test_live_stage import ENV, _verify, _workspace
from test_sdk_worker import FakeClient


def test_startup_hold_survives_worker_cleanup_and_blocks_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env, packet = _operator_request(tmp_path)
    env["Path"] = "synthetic broad operator environment"
    roles: list[Stage] = []
    started: list[tuple[Path, str]] = []
    sdk_calls: list[str] = []

    class Client(FakeClient):
        def close(self) -> None:
            control, _ = started[-1]
            diagnostic = read_signal(control / "review.startup.json")
            assert diagnostic["outcome"] == "initialization_failed"
            sdk_calls.append("close-with-prior-failure")
            raise OSError("synthetic SDK detail disallowed from receipt")

    def factory(path: Path, managed_env: dict[str, str],
                _on_attention: Callable[[], None]) -> Client:
        assert "PATH" not in managed_env
        sdk_calls.append("construct-fake")
        return Client(path, "runtime")

    monkeypatch.setattr(sdk_worker, "review", partial(sdk_worker.review, factory=factory))

    class FixtureJob(Job):
        def start(self, role: Stage, control: Path, environment: dict[str, str]) -> None:
            assert "PATH" not in {key.upper() for key in environment}
            assert role in (Role.VERIFIER, Role.REVIEW), "early hold reached later role"
            self.roles.append(role)
            if role == Role.REVIEW:
                started.append((control, environment[CHALLENGE]))
            try:
                run_stage("verifier" if role == Role.VERIFIER else "review", control,
                          env=environment, clock=lambda: 0, parent_pid=os.getpid,
                          verify_call=_verify, checkout_call=lambda *_: None)
            except (RuntimeError, OSError):
                # A failed synthetic role exits, just as the private main returns 1.
                pass

        def worker_exited(self) -> bool:
            return True

    def run_fixture() -> int:
        return run(0, command="fixture-command", environ=env, clock=lambda: 0,
                   sleep=lambda _: None, factory=lambda: FixtureJob(roles, True))

    assert run_fixture() == 1
    assert roles == [Role.VERIFIER, Role.REVIEW]
    assert sdk_calls == ["construct-fake", "close-with-prior-failure"]
    [(control, challenge)] = started
    correlation = {
        "challenge": challenge, "head": packet.head, "dispatch_id": packet.dispatch_id,
        "packet_sha256": hashlib.sha256(canonical_packet(packet)).hexdigest(),
    }
    assert read_signal(control / "review.startup.json") == {
        **correlation, "outcome": "initialization_failed",
    }
    assert read_signal(control / "review.cleanup.json") == {
        **correlation, "outcome": "cleanup_failed",
    }
    assert not any((control / name).exists() for name in (
        "review.ready.json", "review.intent.json", "review.started.json", "review.result.json",
        "review.shutdown.json", "publisher.result.json",
    ))

    assert run_fixture() == 1
    assert roles == [Role.VERIFIER, Role.REVIEW, Role.VERIFIER]
    assert len(started) == 1 and len(sdk_calls) == 2


@pytest.mark.parametrize("drift", (False, True))
def test_typed_null_annotation_uses_both_proofs_at_real_stage_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: bool,
) -> None:
    control, packet = _workspace(tmp_path)
    run_stage("verifier", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
              verify_call=_verify)
    events: list[str] = []

    class Client(FakeClient):
        def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
            events.append("thread")
            return super().thread_start(parameters).model_copy(update={"model": packet.model})

        def review_start(self, parameters: JsonObject) -> ReviewStartResponse:
            assert events == ["proof", "construct", "thread", "fresh-authority", "proof"]
            assert (control / "review.intent.json").is_file()
            events.append("dispatch")
            self.events.append("intent")
            ack = super().review_start(parameters)
            self.events.append("ack")
            return ack

    def factory(path: Path, _env: dict[str, str], _attention: Callable[[], None]) -> Client:
        assert events == ["proof"]
        events.append("construct")
        return Client(path, "null-git")

    def checkout(_exe: Path, _root: Path, _packet: ExecutionPacket,
                 remaining: Callable[[], float]) -> None:
        assert remaining() > 0 and not (control / "review.intent.json").exists()
        if events:
            assert events[-1] == "fresh-authority"
            if drift:
                raise RuntimeError("synthetic drift")
        events.append("proof")

    def refresh(_sleep: float) -> None:
        def verify(data: bytes, request: Request, remaining: Callable[[], float]) -> VerifiedExecution:
            events.append("fresh-authority")
            return _verify(data, request, remaining)

        run_stage("reverify", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
                  verify_call=verify)
        (control / "reverify.result.json").replace(control / "review.authority.json")

    def review() -> None:
        run_stage("review", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
                  sleep=refresh, checkout_call=checkout)

    monkeypatch.setattr(sdk_worker, "review", partial(sdk_worker.review, factory=factory))
    if drift:
        with pytest.raises(sdk_worker.ReviewHold):
            review()
        assert events == ["proof", "construct", "thread", "fresh-authority"]
        assert not (control / "review.intent.json").exists()
        assert not (control / "review.result.json").exists()
    else:
        review()
        assert events == ["proof", "construct", "thread", "fresh-authority", "proof", "dispatch"]
        assert read_signal(control / "review.result.json")["head"] == packet.head

    assert not (control / "publisher.result.json").exists()
