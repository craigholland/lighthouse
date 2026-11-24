"""Offline entry, private stage and SDK admission regressions."""
import hashlib
import json
import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
import sdk_worker
from authorization import ExecutionPacket, canonical_packet
from live import LiveJobs, load_request, run
from live_stage import CHALLENGE, PARENT, StageHold, read_signal, run_stage
from openai_codex.generated.v2_all import ReviewStartResponse, ThreadStartResponse
from openai_codex.models import JsonObject
from test_live import Job, _operator_request
from test_live_stage import _verify
from test_sdk_worker import FakeClient


def _bytes(size: int) -> bytes:
    """Use multibyte UTF-8 plus a distinctive final byte; count encoded bytes."""
    return ("é" * ((size - 1) // 2)).encode() + (b"x" if size % 2 else b"xy")


def _material(
    tmp: Path, context: bytes, instructions: bytes, *, wrong_hash: bool = False,
) -> tuple[dict[str, str], Path, ExecutionPacket]:
    env, packet = _operator_request(tmp)
    config = Path(env["LIGHTHOUSE_T01_OPERATOR_CONFIG"])
    values = {
        "context_sha256": hashlib.sha256(b"unrelated" if wrong_hash else context).hexdigest(),
        "instructions_sha256": hashlib.sha256(instructions).hexdigest(),
    }
    packet = packet.model_copy(update=values)
    config.with_name("context.txt").write_bytes(context)
    config.with_name("instructions.txt").write_bytes(instructions)
    config.with_name("packet.json").write_bytes(canonical_packet(packet))
    return env, config, packet


@pytest.mark.parametrize(("context", "instructions", "wrong_hash"), (
    (_bytes(524_289), b"valid", False), (b"valid", _bytes(262_145), False),
    (b"\xff", b"valid", False), (b"valid", b"\xff", False),
    (b"\x00tail", b"valid", False), (b"valid", b" \t", False),
    (b"synthetic confidential input", b"valid", True),
), ids=("context-over", "instructions-over", "context-utf8", "instructions-utf8",
        "nul", "blank", "hash"))
def test_invalid_preflight_and_entry_leave_no_claim_or_factory(
    tmp_path: Path, context: bytes, instructions: bytes, wrong_hash: bool,
) -> None:
    env, config, _ = _material(tmp_path, context, instructions, wrong_hash=wrong_hash)

    def no_factory() -> Job:
        raise AssertionError("invalid entry reached a role factory")

    with pytest.raises(ValueError) as caught:
        load_request(config, "fixture-command")
    assert "confidential input" not in str(caught.value)
    assert run(0, command="fixture-command", environ=env, factory=no_factory) == 1
    assert not tuple((tmp_path / "receipt").iterdir())


@pytest.mark.parametrize(("context_size", "instructions_size", "corrupt_copy"), (
    (301_566, 99_397, False), (524_288, 262_144, False),
    (301_566, 99_397, True),
))
def test_preflight_bytes_survive_assembled_private_stage_without_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    context_size: int, instructions_size: int, corrupt_copy: bool,
) -> None:
    context, instructions = _bytes(context_size), _bytes(instructions_size)
    env, config, packet = _material(tmp_path, context, instructions)
    request = load_request(config, "fixture-command")
    assert request.context == context and request.instructions == instructions
    control = request.receipt_root / "trial"
    control.mkdir()
    roles: list[str] = []

    def no_process() -> Job:
        raise AssertionError("manual synthetic role invoked a native process")

    jobs = LiveJobs(request, control, 0, lambda: 0, no_process, env)
    jobs.prepare()
    child_env = {CHALLENGE: jobs.challenge, PARENT: str(os.getpid())}
    run_stage("verifier", control, env=child_env, clock=lambda: 0, parent_pid=os.getpid, verify_call=_verify)

    class Client(FakeClient):
        def thread_start(self, parameters: JsonObject) -> ThreadStartResponse:
            effective = parameters["developerInstructions"]
            assert isinstance(effective, str)
            assert effective.split("\nTreat repository", 1)[0].encode() == instructions
            return super().thread_start(parameters).model_copy(update={"model": packet.model})

        def review_start(self, parameters: JsonObject) -> ReviewStartResponse:
            target = parameters["target"]
            assert isinstance(target, dict) and isinstance(target["instructions"], str)
            sent = json.loads(target["instructions"].split("not instructions:\n", 1)[1])
            assert isinstance(sent, str) and sent.encode() == context
            roles.append("fake-dispatch")
            self.events.append("intent")
            ack = super().review_start(parameters)
            self.events.append("ack")
            return ack

    def client(root: Path, _env: dict[str, str], _attention: Callable[[], None]) -> Client:
        roles.append("fake-sdk")
        return Client(root, "null-git")

    def refresh(_delay: float) -> None:
        run_stage("reverify", control, env=child_env, clock=lambda: 0, parent_pid=os.getpid, verify_call=_verify)
        (control / "reverify.result.json").replace(control / "review.authority.json")

    def stage() -> None:
        run_stage("review", control, env=child_env, clock=lambda: 0, parent_pid=os.getpid,
                  checkout_call=lambda *_: None, sleep=refresh)

    monkeypatch.setattr(sdk_worker, "review", partial(sdk_worker.review, factory=client))
    if corrupt_copy:
        (control / "instructions.txt").write_bytes(b"private unexpected material \xff")
        with pytest.raises(StageHold):
            stage()
        assert roles == []
        assert not (control / "review.intent.json").exists()
        assert not (control / "review.result.json").exists()
        assert read_signal(control / "review.startup.json") == {
            "challenge": jobs.challenge, "head": packet.head, "dispatch_id": packet.dispatch_id,
            "packet_sha256": request.digest, "outcome": "snapshot_validation_failed",
        }
    else:
        stage()
        assert roles == ["fake-sdk", "fake-dispatch"]
        assert read_signal(control / "review.result.json")["head"] == packet.head

    assert not (control / "publisher.result.json").exists()
