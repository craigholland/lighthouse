"""Offline capture approval policy; no default transport or runtime."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from t02_event_evidence import API_ROOT, MAX_PROVIDER_BYTES, PublicGitHub
from t02_event_gate import LEAD, LEAD_APP, OWNER
from t02_event_types import Hold, decode

SCOPE = "lighthouse-t02-callback-capture-only"
PREFIX = "Lighthouse-T02 capture approval: "


@dataclass(frozen=True)
class CaptureApprovalTarget:
    """Exact digest projection; not a checked local operator packet."""

    head: str
    digest: str
    activation_ms: int
    cutoff_ms: int

    def __post_init__(self) -> None:
        if (not re.fullmatch(r"[0-9a-f]{40}", self.head)
            or not re.fullmatch(r"[0-9a-f]{64}", self.digest)
            or type(self.activation_ms) is not int or type(self.cutoff_ms) is not int
            or not 0 < self.cutoff_ms - self.activation_ms <= 900_000):
            raise Hold("invalid capture approval target")


class CaptureEvidence:
    """Check only provider-shaped reads; no operational factory or effects."""

    def __init__(self, http: PublicGitHub, clock: Callable[[], int]) -> None:
        self._http = http
        self._clock = clock

    def _read(self, path: str, deadline: int) -> dict[str, object]:
        if self._clock() >= deadline:
            raise Hold("capture evidence deadline")
        value = self._http.read(API_ROOT + path, deadline_ms=deadline, limit=MAX_PROVIDER_BYTES)
        if value.status != 200 or self._clock() >= deadline:
            raise Hold("capture evidence unavailable")
        return decode(value.body, MAX_PROVIDER_BYTES)

    def _comment(
        self, ref: int, actor: int, app: int | None, target: CaptureApprovalTarget, deadline: int,
    ) -> tuple[datetime, int, int]:
        record = self._read(f"/issues/comments/{ref}", deadline)
        user, origin, created, body = (record.get(k) for k in (
            "user", "performed_via_github_app", "created_at", "body",
        ))
        if (
            type(record.get("id")) is not int or record.get("id") != ref
            or record.get("issue_url") != "https://api.github.com" + API_ROOT + "/issues/5"
            or not isinstance(user, dict) or user.get("id") != actor
            or user.get("type") != ("User" if app is None else "Bot")
            or "performed_via_github_app" not in record
            or (origin is not None if app is None else not isinstance(origin, dict) or origin.get("id") != app)
            or not isinstance(created, str) or created != record.get("updated_at")
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", created)
            or not isinstance(body, str) or not body.startswith(PREFIX) or "\n" in body or "\r" in body
        ):
            raise Hold("invalid capture comment provenance")
        payload = decode(body[len(PREFIX):].encode())
        start, end = payload.get("not_before"), payload.get("expires")
        if (set(payload) != {"head", "digest", "scope", "not_before", "expires"}
            or payload.get("head") != target.head or payload.get("digest") != target.digest
            or payload.get("scope") != SCOPE or type(start) is not int or type(end) is not int
            or not start <= target.activation_ms < target.cutoff_ms <= end):
            raise Hold("invalid capture approval content")
        return datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC), start, end

    def allows(
        self, target: CaptureApprovalTarget, owner_ref: int, lead_ref: int, *, before_ms: int | None = None,
    ) -> bool:
        """Read the current issue, PR, and distinct chronological owner/Lead comments."""
        now = self._clock()
        if (type(owner_ref) is not int or type(lead_ref) is not int or not 0 < owner_ref < lead_ref
            or not target.activation_ms <= now < target.cutoff_ms):
            return False
        deadline = min(now + 4_000, target.cutoff_ms, before_ms if before_ms is not None else target.cutoff_ms)
        try:
            issue = self._read("/issues/5", deadline)
            pr = self._read("/pulls/15", deadline)
            labels, head, base = issue.get("labels"), pr.get("head"), pr.get("base")
            if (issue.get("number") != 5 or issue.get("state") != "open" or not isinstance(labels, list)
                or any(not isinstance(label, dict) or not isinstance(label.get("name"), str)
                       or label["name"] == "lighthouse:blocked" for label in labels)
                or pr.get("number") != 15 or pr.get("state") != "open" or pr.get("draft") is not True
                or pr.get("merged") is not False or not isinstance(head, dict) or head.get("sha") != target.head
                or not isinstance(base, dict) or base.get("ref") != "development"):
                return False
            owner = self._comment(owner_ref, OWNER, None, target, deadline)
            lead = self._comment(lead_ref, LEAD, LEAD_APP, target, deadline)
            now = self._clock()
            return (
                owner[0] <= lead[0] and lead[0].timestamp() * 1000 <= target.activation_ms
                and owner[1:] == lead[1:] and target.activation_ms <= now < deadline
            )
        except (Hold, OSError, ValueError, TypeError):
            return False
