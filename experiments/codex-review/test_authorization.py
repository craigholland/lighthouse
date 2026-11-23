"""Exercise T01 exact-head authorization from synthetic GitHub facts."""
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from authorization import (
    MARKER,
    CommentFact,
    Denied,
    ExecutionPacket,
    PullFact,
    Target,
    canonical_packet,
    claim,
    private_receipt_binding,
    verify,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeGithub:
    def __init__(self, packet: ExecutionPacket) -> None:
        body = packet.model_dump(include=set(Target.model_fields))
        body["state"] = "owner-approved-lead-ready"
        body["packet_sha256"] = hashlib.sha256(canonical_packet(packet)).hexdigest()
        self.record: CommentFact | None = CommentFact(
            17, 123, 4, 359712317, 5869282,
            MARKER + "\n" + json.dumps(body), NOW, NOW,
        )
        self.pr: PullFact | None = PullFact(
            123, "craigholland/lighthouse", 14, "development", "a" * 40, 359713928, True,
        )
        self.reads = 0

    def comment(self, comment_id: int) -> CommentFact | None:
        self.reads += 1
        assert comment_id == 17
        return self.record

    def pull(self) -> PullFact | None:
        self.reads += 1
        return self.pr


def packet_for(root: Path, *, expiry: int | None = None) -> ExecutionPacket:
    return ExecutionPacket.model_validate({
        "repository_id": 123, "repository": "craigholland/lighthouse",
        "issue": 4, "pr": 14, "base": "development", "head": "a" * 40,
        "dot_actor": 359713928, "lead_actor": 359712317, "lead_app": 5869282,
        "dispatch_id": "fixture-1", "owner_decision": "fixture-approved",
        "expires_at": int(NOW.timestamp()) + 60 if expiry is None else expiry,
        "maximum_elapsed": 900, "review_attempts": 1, "comment_attempts": 1,
        "context_sha256": "b" * 64, "instructions_sha256": "c" * 64,
        "sdk": "0.171.0", "runtime": "0.171.0", "model": "fixture-model",
        "account_policy": "existing-managed", "access": "read-only",
        "approval": "deny-all", "action": "COMMENT", "command": "fixture command",
        "receipt_binding": private_receipt_binding(root),
    })


def test_canonical_matches_key_order_and_atomic_claim(tmp_path: Path) -> None:
    packet = packet_for(tmp_path)
    ordered = canonical_packet(packet)
    reversed_fields = dict(reversed(tuple(packet.model_dump().items())))
    request = json.dumps(reversed_fields, indent=2).encode()
    github = FakeGithub(packet)
    approved = verify(request, comment_id=17, repository_id=123, transport=github, now=NOW)
    assert approved.packet_sha256 == hashlib.sha256(ordered).hexdigest()
    assert github.reads == 2
    first_claim = claim(approved, tmp_path)
    assert first_claim.read_text(encoding="ascii").splitlines() == [
        approved.packet_sha256, packet.dispatch_id,
    ]
    with pytest.raises(Denied, match="already claimed"):
        claim(approved, tmp_path)
    different_root = tmp_path / "alternate"
    different_root.mkdir()
    with pytest.raises(Denied, match="approved binding"):
        claim(approved, different_root)
    assert not list(different_root.iterdir())


@pytest.mark.parametrize("raw", [b"", b"{}", b'{"issue":4,"issue":5}', b'{"day": NaN}'])
def test_invalid_packet_never_reaches_transport(tmp_path: Path, raw: bytes) -> None:
    github = FakeGithub(packet_for(tmp_path))
    with pytest.raises(Denied):
        verify(raw, comment_id=17, repository_id=123, transport=github, now=NOW)
    assert github.reads == 0


@pytest.mark.parametrize("condition", [
    "missing", "wrong-app", "missing-app", "wrong-actor", "wrong-repo",
    "edited", "policy-only", "wrong-digest", "wrong-head", "expired",
])
def test_verification_holds_on_untrusted_or_stale_evidence(
    tmp_path: Path, condition: str,
) -> None:
    packet = packet_for(tmp_path)
    github = FakeGithub(packet)
    record = github.record
    assert record is not None and github.pr is not None
    now = NOW
    if condition == "missing":
        github.record = None
    elif condition == "wrong-app":
        github.record = replace(record, app_id=1)
    elif condition == "missing-app":
        github.record = replace(record, app_id=None)
    elif condition == "wrong-actor":
        github.record = replace(record, author_id=1)
    elif condition == "wrong-repo":
        github.record = replace(record, repository_id=124)
    elif condition == "edited":
        github.record = replace(record, updated_at=NOW + timedelta(seconds=1))
    elif condition == "policy-only":
        github.record = replace(record, body="Policy-only approval " + MARKER)
    elif condition == "wrong-digest":
        digest = hashlib.sha256(canonical_packet(packet)).hexdigest()
        github.record = replace(record, body=record.body.replace(digest, "d" * 64))
    elif condition == "wrong-head":
        github.pr = replace(github.pr, head="b" * 40)
    else:
        now += timedelta(seconds=60)
    with pytest.raises(Denied):
        verify(canonical_packet(packet), comment_id=17, repository_id=123, transport=github, now=now)

def test_changed_dispatch_and_boolean_limits_are_not_authority(tmp_path: Path) -> None:
    packet = packet_for(tmp_path)
    github = FakeGithub(packet)
    bits = packet.model_dump()
    bits["review_attempts"] = True
    invalid = json.dumps(bits).encode()
    with pytest.raises(Denied):
        verify(invalid, comment_id=17, repository_id=123, transport=github, now=NOW)
    assert github.reads == 0
    bits["review_attempts"] = 1
    bits["dispatch_id"] = "fixture-2"
    with pytest.raises(Denied, match="does not match"):
        verify(json.dumps(bits).encode(), comment_id=17, repository_id=123, transport=github, now=NOW)
    assert github.reads == 1
