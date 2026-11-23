"""Drive the actual operator composition with owned job doubles and no provider."""

import hashlib
import json
import time
from pathlib import Path

from authorization import ExecutionPacket, canonical_packet, private_receipt_binding
from live import Stage, run
from supervisor import Role


def _operator_request(tmp_path: Path) -> tuple[dict[str, str], ExecutionPacket]:
    source = tmp_path / "operator"
    source.mkdir()
    receipt = tmp_path / "receipt"
    receipt.mkdir()
    workspace = tmp_path / "lead-checkout"
    workspace.mkdir()
    context = b"synthetic approved context"
    instructions = b"synthetic instruction snapshot"
    packet = ExecutionPacket(
        repository_id=123, repository="craigholland/lighthouse", issue=4, pr=14,
        base="development", head="a" * 40, dot_actor=359713928, lead_actor=359712317,
        lead_app=5869282, dispatch_id="fixture-1", owner_decision="fixture-owner-decision",
        expires_at=int(time.time()) + 60, maximum_elapsed=900, review_attempts=1,
        comment_attempts=1, context_sha256=hashlib.sha256(context).hexdigest(),
        instructions_sha256=hashlib.sha256(instructions).hexdigest(), sdk="0.171.0",
        runtime="0.171.0", model="fixture-model", account_policy="existing-managed",
        access="read-only", approval="deny-all", action="COMMENT", command="fixture-command",
        receipt_binding=private_receipt_binding(receipt),
    )
    config = source / "operator.json"
    config.write_text(json.dumps({
        "comment_id": 100, "repository_id": 123, "receipt_root": str(receipt),
        "workspace": str(workspace), "verifier_jwt_file": str(source / "read-fake.jwt"),
        "publisher_jwt_file": str(source / "write-fake.jwt"),
    }), encoding="utf-8")
    (source / "context.txt").write_bytes(context)
    (source / "instructions.txt").write_bytes(instructions)
    (source / "packet.json").write_bytes(canonical_packet(packet))
    return {"LIGHTHOUSE_T01_OPERATOR_CONFIG": str(config), "API_SECRET": "synthetic"}, packet


def test_invalid_config_cannot_construct_stage(tmp_path: Path) -> None:
    """Malformed and unselected inputs cannot reach any child process factory."""
    env, _ = _operator_request(tmp_path)

    def forbidden() -> Job:
        raise AssertionError("job factory ran before shape validation")

    assert run(0, environ={}, factory=forbidden) == 2
    assert run(0, command="wrong-command", environ=env, factory=forbidden) == 1
    path = Path(env["LIGHTHOUSE_T01_OPERATOR_CONFIG"]).with_name("packet.json")
    path.write_text('{"owner-approved":true}', encoding="utf-8")
    assert run(0, command="fixture-command", environ=env, factory=forbidden) == 1


class Job:
    """Drive the operator's actual filesystem protocol with synthetic child outputs."""

    def __init__(self, all_roles: list[Stage], approved: bool) -> None:
        self.roles = all_roles
        self.control = Path()
        self.role: Stage = Role.VERIFIER
        self.echo: dict[str, object] = {}
        self.approved = approved
        self.closed = False

    def start(self, role: Stage, control: Path, environment: dict[str, str]) -> None:
        assert "API_SECRET" not in environment
        assert ("LIGHTHOUSE_STAGE_JWT_FILE" in environment) == (role != Role.REVIEW)
        self.control, self.role = control, role
        self.roles.append(role)
        raw = (control / "packet.json").read_bytes()
        packet = ExecutionPacket.model_validate_json(raw)
        self.echo = {
            "challenge": environment["LIGHTHOUSE_STAGE_CHALLENGE"], "ok": self.approved,
            "packet_sha256": hashlib.sha256(raw).hexdigest(), "head": packet.head,
        }
        if role == Role.REVIEW:
            self._put("review.ready.json", {**self.echo, "thread_id": "fake-thread"})
        if role == Role.VERIFIER:
            self._put("verifier.result.json", self.echo)
        if role == "reverify":
            self._put("reverify.result.json", {**self.echo, "verified_at": 0.0,
                                               "thread_id": "fake-thread"})
        if role == Role.PUBLISHER:
            assert (control / "review.shutdown.json").is_file()
            self._put("publisher.result.json", {**self.echo, "review_id": 1})

    def _put(self, name: str, value: dict[str, object]) -> None:
        (self.control / name).write_text(json.dumps(value), encoding="utf-8")

    def worker_exited(self) -> bool:
        if self.role == Role.REVIEW:
            if not (self.control / "review.authority.json").is_file():
                return False
            self._put("review.result.json", {**self.echo, "thread_id": "fake-thread",
                                             "turn_id": "fake-turn", "output": "fictional"})
        return True

    def active_count(self) -> int:
        return 0 if self.worker_exited() else 1

    def force(self) -> None:
        raise AssertionError("healthy synthetic stage should not be forced")

    def close(self) -> None:
        self.closed = True


def test_actual_composed_role_order_and_inert_denial(tmp_path: Path) -> None:
    """Fresh authority, cleanup, and credential isolation control later roles."""
    env, _ = _operator_request(tmp_path)
    roles: list[Stage] = []
    assert run(0, command="fixture-command", environ=env, clock=lambda: 0.0,
               sleep=lambda _: None, factory=lambda: Job(roles, False)) == 1
    assert roles == [Role.VERIFIER]
    roles.clear()
    assert run(0, command="fixture-command", environ=env, clock=lambda: 0.0,
               sleep=lambda _: None, factory=lambda: Job(roles, True)) == 0
    assert roles == [Role.VERIFIER, Role.REVIEW, "reverify", Role.PUBLISHER]
