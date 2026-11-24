"""Exact-head execution authority for the contained T01 experiment."""
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MARKER = "lighthouse-t01-execution-authorization-v1"
REPOSITORY = "craigholland/lighthouse"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Head = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Nonempty = Annotated[str, Field(min_length=1, max_length=2048)]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")]
Positive = Annotated[int, Field(gt=0)]


class Denied(RuntimeError):
    """Sanitized hold; raw packet or provider output is never exposed."""


class Target(BaseModel):
    """Fields bound to both the private packet and the trusted attestation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)
    repository_id: Positive
    repository: Literal["craigholland/lighthouse"]
    issue: Literal[4]
    pr: Literal[14]
    base: Literal["development"]
    head: Head
    dot_actor: Literal[359713928]
    lead_actor: Literal[359712317]
    lead_app: Literal[5869282]
    dispatch_id: Identifier
    owner_decision: Nonempty
    expires_at: Positive
    maximum_elapsed: Literal[900]
    review_attempts: Literal[1]
    comment_attempts: Literal[1]

    @field_validator(
        "repository_id", "issue", "pr", "dot_actor", "lead_actor", "lead_app",
        "expires_at", "maximum_elapsed", "review_attempts", "comment_attempts", mode="before",
    )
    @classmethod
    def require_json_integer(cls, value: object) -> int:
        """Do not let JSON booleans satisfy an integer-valued literal."""
        if type(value) is not int:
            raise ValueError("required integer")
        return value


class ExecutionPacket(Target):
    """Complete, privately stored operator proposal; never authority by itself."""

    context_sha256: Digest
    instructions_sha256: Digest
    sdk: Literal["0.171.0"]
    runtime: Literal["0.171.0"]
    model: Nonempty
    account_policy: Literal["existing-managed"]
    access: Literal["read-only"]
    approval: Literal["deny-all"]
    action: Literal["COMMENT"]
    command: Nonempty
    receipt_binding: Digest


class Attestation(Target):
    """Schema of an exact marker-backed owner decision and renewed Lead readiness."""

    state: Literal["owner-approved-lead-ready"]
    packet_sha256: Digest


@dataclass(frozen=True)
class CommentFact:
    """Metadata normalized by the configured authenticated GitHub transport."""

    comment_id: int
    repository_id: int
    issue: int
    author_id: int
    app_id: int | None
    body: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PullFact:
    """Fresh target state returned exclusively by the trusted transport."""

    repository_id: int
    repository: str
    pr: int
    base: str
    head: str
    author_id: int
    open: bool


class TrustedGithub(Protocol):
    """Configured read-only transport, never a caller-provided API host or cache."""

    def comment(self, comment_id: int) -> CommentFact | None: ...
    def pull(self) -> PullFact | None: ...


@dataclass(frozen=True, repr=False)
class VerifiedExecution:
    """Internal evidence; not a serialized grant or session token."""

    packet: ExecutionPacket
    comment_id: int
    packet_sha256: str


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _discard_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _decode(data: bytes) -> object:
    if not 0 < len(data) <= 32_768:
        raise Denied("Malformed execution record.")
    try:
        decoded: object = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_discard_constant
        )
        return decoded
    except (UnicodeError, ValueError, RecursionError):
        raise Denied("Malformed execution record.") from None


def canonical_packet(packet: ExecutionPacket) -> bytes:
    """Hash UTF-8 JSON with sorted keys, separators, and no non-finite numbers."""
    return json.dumps(
        packet.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def verify(
    packet_bytes: bytes, *, comment_id: int, repository_id: int,
    transport: TrustedGithub, now: datetime,
) -> VerifiedExecution:
    """Verify an operator-selected packet via fresh exact GitHub facts; no effects."""
    try:
        packet = ExecutionPacket.model_validate(_decode(packet_bytes))
        digest = hashlib.sha256(canonical_packet(packet)).hexdigest()
    except (ValidationError, UnicodeError):
        raise Denied("Malformed execution packet.") from None
    if (
        type(comment_id) is not int or comment_id <= 0
        or type(repository_id) is not int or repository_id != packet.repository_id
        or now.utcoffset() is None or now.timestamp() >= packet.expires_at
    ):
        raise Denied("Execution target missing, mismatched, or expired.")
    try:
        fact = transport.comment(comment_id)
    except (OSError, TimeoutError):
        raise Denied("Execution attestation unavailable.") from None
    if (
        fact is None or fact.comment_id != comment_id or fact.repository_id != repository_id
        or fact.issue != packet.issue or fact.author_id != packet.lead_actor
        or fact.app_id != packet.lead_app or fact.created_at != fact.updated_at
        or fact.created_at.utcoffset() is None or fact.created_at > now
    ):
        raise Denied("Execution attestation provenance not verified.")
    marker, sep, body = fact.body.partition("\n")
    if marker != MARKER or not sep:
        raise Denied("Execution attestation marker not verified.")
    try:
        attestation = Attestation.model_validate(_decode(body.encode("utf-8")))
    except (ValidationError, UnicodeError):
        raise Denied("Malformed execution attestation.") from None
    expected = packet.model_dump(include=set(Target.model_fields))
    observed = attestation.model_dump(include=set(Target.model_fields))
    if expected != observed or attestation.packet_sha256 != digest:
        raise Denied("Execution attestation does not match the private packet.")
    try:
        pr = transport.pull()
    except (OSError, TimeoutError):
        raise Denied("Execution pull request unavailable.") from None
    if pr != PullFact(repository_id, REPOSITORY, 14, "development", packet.head, packet.dot_actor, True):
        raise Denied("Execution pull request is not current.")
    return VerifiedExecution(packet, comment_id, digest)


def private_receipt_binding(receipt_root: Path) -> str:
    """Bind one separately configured private directory, not a CLI output path."""
    return _root_and_binding(receipt_root)[1]


def _root_and_binding(receipt_root: Path) -> tuple[Path, str]:
    try:
        root = receipt_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("not a directory")
        return root, hashlib.sha256(os.fsencode(os.path.normcase(str(root)))).hexdigest()
    except (OSError, ValueError):
        raise Denied("Private receipt directory unavailable.") from None


def claim(verified: VerifiedExecution, receipt_root: Path) -> Path:
    """Consume the sole launch allowance by durable, exclusive creation.

    After any write ambiguity, leave the canonical claim in place. A survivor
    only holds or reconciles its known run; claim presence never grants authority.
    """
    root, binding = _root_and_binding(receipt_root)
    if binding != verified.packet.receipt_binding:
        raise Denied("Private receipt directory does not match the approved binding.")
    path = root / f"t01-{verified.comment_id}.claim"
    try:
        with path.open("xb") as stream:
            material = f"{verified.packet_sha256}\n{verified.packet.dispatch_id}\n".encode("ascii")
            stream.write(material)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, UnicodeError):
        raise Denied("Execution already claimed or claim status unknown.") from None
    return path
