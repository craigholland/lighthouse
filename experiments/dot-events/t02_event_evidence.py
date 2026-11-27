"""Strict private packet parsing and read-only public GitHub evidence adapter.

The adapter consumes bytes from a bounded transport, not pasted approvals.
No caller-supplied approval or native/real service is wired into the CLI.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import astuple, dataclass
from typing import Protocol

from t02_event_gate import (
    LEAD,
    LEAD_APP,
    OWNER,
    REPOSITORY,
    SCOPE,
    Authority,
    Evidence,
    Packet,
)
from t02_event_types import Binding, Hold, decode, encode

API_ROOT = "/repos/craigholland/lighthouse"
PREFIX = "Lighthouse-T02 exact approval: "
MAX_PROVIDER_BYTES = 32768


@dataclass(frozen=True)
class PrivatePacket:
    packet: Packet
    binding: Binding

    @classmethod
    def parse(cls, body: bytes) -> PrivatePacket:
        """Parse bounded canonical data, not credentials or provider authority."""
        outer = decode(body)
        if set(outer) != {"packet", "binding"}:
            raise Hold("unexpected private packet fields")
        p, b = outer["packet"], outer["binding"]
        packet_keys = {
            "head", "workspace", "dot", "platform", "tunnel", "private_binding_digest",
            "runtime_binary_digest", "host", "activation_ms",
        }
        binding_keys = {"proof_id", "principal", "callback_host", "callback_path", "activation_ms"}
        if not isinstance(p, dict) or p.keys() != packet_keys or not isinstance(b, dict) or b.keys() != binding_keys:
            raise Hold("unexpected private packet fields")
        if any(type(p[key]) is not str for key in packet_keys - {"activation_ms"}):
            raise Hold("invalid identity fields")
        if any(type(b[key]) is not str for key in binding_keys - {"activation_ms"}):
            raise Hold("invalid private binding fields")
        if type(p["activation_ms"]) is not int or type(b["activation_ms"]) is not int:
            raise Hold("invalid activation")
        packet = Packet(**p)
        binding = Binding(**b)
        if not re.fullmatch(r"[0-9a-f]{40}", packet.head) or not re.fullmatch(
            r"[0-9a-f]{64}", packet.runtime_binary_digest,
        ):
            raise Hold("missing exact commit or executable identity")
        if packet.activation_ms != binding.activation_ms or packet.private_binding_digest != hashlib.sha256(
            encode(astuple(binding)),
        ).hexdigest():
            raise Hold("private binding digest mismatch")
        return cls(packet, binding)


@dataclass(frozen=True)
class ProviderReply:
    status: int
    body: bytes


class PublicGitHub(Protocol):
    """GET only against api.github.com, no redirect, proxy, auth or alternate origin."""

    def read(self, path: str, *, deadline_ms: int, limit: int) -> ProviderReply: ...


class GitHubEvidence:
    """Verify two named public comments and current GitHub PR/Issue state."""

    def __init__(
        self, http: PublicGitHub, private: PrivatePacket, clock: Callable[[], int],
        owner_comment: int, lead_comment: int,
    ) -> None:
        if (
            type(owner_comment) is not int or type(lead_comment) is not int
            or not 0 < owner_comment < lead_comment
        ):
            raise Hold("invalid public evidence references")
        self._http = http
        self._private = private
        self._clock = clock
        self._ids = (owner_comment, lead_comment)

    def _get(self, path: str, deadline_ms: int) -> dict[str, object]:
        if self._clock() >= deadline_ms:
            raise Hold("provider deadline")
        response = self._http.read(API_ROOT + path, deadline_ms=deadline_ms, limit=MAX_PROVIDER_BYTES)
        if response.status != 200 or self._clock() >= deadline_ms:
            raise Hold("provider state unavailable")
        return decode(response.body, MAX_PROVIDER_BYTES)

    def current(self) -> Authority | None:
        """No synthesized authority on timeout, edit, mismatch or failed reads."""
        limit = min(self._clock() + 4_000, self._private.binding.send_until)
        try:
            issue = self._get("/issues/5", limit)
            pr = self._get("/pulls/15", limit)
            revisions = pr.get("head")
            target = pr.get("base")
            labels = issue.get("labels")
            if (
                issue.get("number") != 5 or issue.get("state") != "open" or pr.get("number") != 15
                or pr.get("state") != "open" or pr.get("draft") is not True
                or pr.get("merged") is not False or not isinstance(revisions, dict)
                or not isinstance(target, dict) or target.get("ref") != "development"
                or not isinstance(labels, list)
                or any(not isinstance(label, dict) for label in labels)
                or "lighthouse:blocked" in {label.get("name") for label in labels}
            ):
                raise Hold("scope not current")
            head = revisions.get("sha")
            if not isinstance(head, str) or head != self._private.packet.head:
                raise Hold("exact head not current")
            owner = self._read_comment(self._ids[0], OWNER, None, limit)
            lead = self._read_comment(self._ids[1], LEAD, LEAD_APP, limit)
            return Authority(head, owner, lead)
        except (Hold, OSError, ValueError, TypeError):
            return None

    def _read_comment(self, ref: int, actor: int, app: int | None, limit: int) -> Evidence:
        record = self._get(f"/issues/comments/{ref}", limit)
        user = record.get("user")
        origin = record.get("performed_via_github_app")
        body = record.get("body")
        if (
            record.get("id") != ref or record.get("issue_url") != "https://api.github.com" + API_ROOT + "/issues/5"
            or not isinstance(user, dict) or user.get("id") != actor
            or user.get("type") != ("User" if app is None else "Bot")
            or (origin is not None if app is None else not isinstance(origin, dict) or origin.get("id") != app)
            or not isinstance(record.get("created_at"), str) or record.get("created_at") != record.get("updated_at")
            or not isinstance(body, str) or not body.startswith(PREFIX) or "\n" in body
        ):
            raise Hold("approval provenance unavailable")
        payload = decode(body[len(PREFIX):].encode())
        if set(payload) != {"head", "digest", "scope", "not_before", "expires"} or (
            payload["head"] != self._private.packet.head or payload["digest"] != self._private.packet.digest
            or payload["scope"] != SCOPE or type(payload["not_before"]) is not int
            or type(payload["expires"]) is not int
        ):
            raise Hold("approval content unavailable")
        return Evidence(
            REPOSITORY, 5, 15, actor, app, SCOPE, self._private.packet.head,
            self._private.packet.digest, payload["not_before"], payload["expires"],
        )
