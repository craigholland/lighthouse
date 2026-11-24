"""Offline exercise of the private child-role contract with fake dependencies."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from authorization import (
    ExecutionPacket,
    VerifiedExecution,
    canonical_packet,
    private_receipt_binding,
)
from live_stage import (
    CHALLENGE,
    JWT_FILE,
    PARENT,
    HistoricalPublication,
    Request,
    StageHold,
    read_signal,
    run_stage,
    write_signal,
)
from sdk_worker import StartupOutcome

NONCE = "b" * 64
ENV = {CHALLENGE: NONCE, PARENT: "123", "SYSTEMROOT": "windows"}


@dataclass(frozen=True)
class Completed:
    """Synthetic safe review completion."""

    thread_id: str
    turn_id: str
    head: str
    output: str


def _workspace(tmp_path: Path) -> tuple[Path, ExecutionPacket]:
    root = tmp_path / "receipts"
    control = root / "trial"
    workspace = tmp_path / "verified"
    control.mkdir(parents=True)
    workspace.mkdir()
    context = b"synthetic review snapshot"
    instructions = b"synthetic review instructions"
    packet = ExecutionPacket(
        repository_id=42, repository="craigholland/lighthouse", issue=4, pr=14,
        base="development", head="a" * 40,
        dot_actor=359713928, lead_actor=359712317, lead_app=5869282,
        dispatch_id="synthetic", owner_decision="synthetic", expires_at=4_000_000_000,
        maximum_elapsed=900, review_attempts=1, comment_attempts=1,
        context_sha256=hashlib.sha256(context).hexdigest(),
        instructions_sha256=hashlib.sha256(instructions).hexdigest(),
        sdk="0.171.0", runtime="0.171.0", model="synthetic", account_policy="existing-managed",
        access="read-only", approval="deny-all", action="COMMENT", command="synthetic",
        receipt_binding=private_receipt_binding(root),
    )
    write_signal(control / "request.json", {
        "comment_id": 55, "repository_id": 42, "started_at": 100,
        "receipt_root": str(root.resolve()), "workspace": str(workspace.resolve()),
    })
    (control / "packet.json").write_bytes(canonical_packet(packet))
    (control / "context.txt").write_bytes(context)
    (control / "instructions.txt").write_bytes(instructions)
    return control.resolve(), packet


def _verify(data: bytes, request: Request, remaining: Callable[[], float]) -> VerifiedExecution:
    assert remaining() > 0
    packet = ExecutionPacket.model_validate_json(data)
    return VerifiedExecution(packet, request.comment_id, hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize('historical', (False, True))
def test_stage_chain_uses_one_claim_fresh_thread_authority_and_separate_publish(
    tmp_path: Path, historical: bool,
) -> None:
    control, packet = _workspace(tmp_path)
    run_stage(
        "verifier", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
        verify_call=_verify,
    )

    def parent_reverify(delay: float) -> None:
        assert delay > 0
        run_stage(
            "reverify", control, env=ENV, clock=lambda: 103, parent_pid=lambda: 123,
            verify_call=_verify,
        )
        authority = read_signal(control / "reverify.result.json")
        write_signal(control / "review.authority.json", authority)

    def review(
        p: ExecutionPacket, context: bytes, instructions: bytes, *,
        workspace: Path, managed_env: dict[str, str], before_review: Callable[[str], None],
        on_started: Callable[[str, str], None], interrupted: Callable[[], bool],
        on_attention: Callable[[], None], on_startup: Callable[[StartupOutcome], None],
    ) -> Completed:
        assert p == packet
        assert workspace == (tmp_path / "verified").resolve()
        assert context and instructions
        assert managed_env == {"SYSTEMROOT": "windows"}
        assert not interrupted() and callable(on_attention) and callable(on_startup)
        before_review("thread")
        on_started("thread", "turn")
        return Completed("thread", "turn", packet.head, "Synthetic findings")

    run_stage(
        "review", control, env={**ENV, "UNRELATED": "opaque"}, clock=lambda: 103,
        parent_pid=lambda: 123, sleep=parent_reverify, review_call=review,
    )
    assert read_signal(control / "review.result.json")["output"] == "Synthetic findings"

    def publish(
        authority: VerifiedExecution, result: dict[str, object], request: Request,
        remaining: Callable[[], float], validate_current: Callable[[], VerifiedExecution],
    ) -> int:
        assert authority == validate_current()
        assert authority.comment_id == request.comment_id
        assert result["turn_id"] == "turn"
        assert remaining() > 0
        if historical:
            raise HistoricalPublication(77)
        return 77

    with pytest.raises((OSError, StageHold)):
        run_stage(
            "publisher", control, env=ENV, clock=lambda: 104, parent_pid=lambda: 123,
            verify_call=_verify, publish_call=publish,
        )
    known = read_signal(control / "review.result.json")
    write_signal(control / "review.shutdown.json", {
        key: known[key] for key in ("ok", "challenge", "packet_sha256", "head")
    } | {"worker_exited": True, "active": 0})
    def publish_stage() -> None:
        run_stage(
            "publisher", control, env=ENV, clock=lambda: 105, parent_pid=lambda: 123,
            verify_call=_verify, publish_call=publish,
        )

    if historical:
        with pytest.raises(HistoricalPublication):
            publish_stage()
        prior = read_signal(control / "publisher.reconciled.json")
        assert prior["review_id"] == 77 and prior["ok"] is False
        assert not (control / "publisher.result.json").exists()
    else:
        publish_stage()
        assert read_signal(control / "publisher.result.json")["review_id"] == 77
    with pytest.raises(RuntimeError, match="already claimed"):
        run_stage(
            "verifier", control, env=ENV, clock=lambda: 106, parent_pid=lambda: 123,
            verify_call=_verify,
        )


def test_startup_failure_survives_separate_cleanup_without_unlocking_effects(tmp_path: Path) -> None:
    control, packet = _workspace(tmp_path)
    run_stage(
        "verifier", control, env=ENV, clock=lambda: 102, parent_pid=lambda: 123,
        verify_call=_verify,
    )

    def failed_review(
        _packet: ExecutionPacket, _context: bytes, _instructions: bytes, /, *,
        on_startup: Callable[[StartupOutcome], None], **_kwargs: object,
    ) -> Completed:
        on_startup(StartupOutcome("thread_start_failed"))
        primary = read_signal(control / "review.startup.json")
        for observation in ("cleanup_starting", "cleanup_failed"):
            on_startup(StartupOutcome(observation))
        assert read_signal(control / "review.startup.json") == primary
        raise StageHold("Fake startup failed.")

    with pytest.raises(StageHold, match="Fake startup failed"):
        run_stage(
            "review", control, env=ENV, clock=lambda: 103, parent_pid=lambda: 123,
            review_call=failed_review,
        )

    binding = {
        "challenge": NONCE, "head": packet.head, "dispatch_id": packet.dispatch_id,
        "packet_sha256": hashlib.sha256(canonical_packet(packet)).hexdigest(),
    }
    assert read_signal(control / "review.startup.json") == {**binding, "outcome": "thread_start_failed"}
    assert read_signal(control / "review.cleanup.json") == {**binding, "outcome": "cleanup_failed"}
    for name in ("ready", "intent", "started", "result"):
        assert not (control / f"review.{name}.json").exists()

    def forbidden_publish(*_: object, **__: object) -> int:
        pytest.fail("A diagnostic must not unlock publishing.")

    with pytest.raises(StageHold, match="unavailable"):
        run_stage(
            "publisher", control, env=ENV, clock=lambda: 104, parent_pid=lambda: 123,
            verify_call=_verify, publish_call=forbidden_publish,
        )
    assert not (control / "publisher.result.json").exists()


def test_private_role_rejects_missing_parent_or_review_credential_pointer(tmp_path: Path) -> None:
    control, _ = _workspace(tmp_path)

    def unreachable(*_: object, **__: object) -> VerifiedExecution:
        pytest.fail("External factory reached before stage gate.")
    with pytest.raises(StageHold, match="parent"):
        run_stage(
            "verifier", control, env=ENV, parent_pid=lambda: 999, verify_call=unreachable,
        )
    with pytest.raises(StageHold, match="parent"):
        run_stage(
            "review", control, env={**ENV, JWT_FILE: "opaque"}, parent_pid=lambda: 123,
            verify_call=unreachable,
        )


def test_request_cannot_expire_into_transport(tmp_path: Path) -> None:
    control, _ = _workspace(tmp_path)

    def unreachable(*_: object, **__: object) -> VerifiedExecution:
        pytest.fail("Expired stage reached a transport.")
    with pytest.raises(StageHold, match="deadline"):
        run_stage(
            "verifier", control, env=ENV, parent_pid=lambda: 123,
            clock=lambda: 130, verify_call=unreachable,
        )
