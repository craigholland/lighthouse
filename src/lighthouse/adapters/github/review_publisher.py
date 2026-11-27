"""Exact single-attempt GitHub COMMENT boundary; no live client is selected here."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

_ORIGIN = "https://api.github.com"
_MAX_TEXT_BYTES = 16_384
_LIMIT = 100
_PREFIX = "<!-- lighthouse:codex-dispatch-v1:"


class PublicationHeld(RuntimeError):
    """The fixed effect or its exact receipt could not be verified."""


def _repository(value: str) -> bool:
    return bool(
        re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", value)
        and all(piece not in {".", ".."} for piece in value.split("/"))
    )


def _positive(value: object) -> bool:
    return type(value) is int and 0 < value < 2**63


@dataclass(frozen=True)
class ReviewTarget:
    """Immutable dispatch attempt bound to one exact PR commit and Lead ID."""

    repository: str
    pull_request: int
    head: str
    lead_id: int
    attempt_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str) or not _repository(self.repository)
            or not _positive(self.pull_request) or not _positive(self.lead_id)
            or not isinstance(self.head, str) or not re.fullmatch(r"[0-9a-f]{40}", self.head)
            or not isinstance(self.attempt_id, str) or not re.fullmatch(r"[0-9a-f]{64}", self.attempt_id)
        ):
            raise PublicationHeld("invalid review target")

    @property
    def marker(self) -> str:
        """Stable internal line kept out of public diagnostics."""
        return _PREFIX + self.attempt_id + " -->"

    @property
    def pull_url(self) -> str:
        return f"{_ORIGIN}/repos/{self.repository}/pulls/{self.pull_request}"


@dataclass(frozen=True)
class CommentReceipt:
    """Verified review identity and the exact target, never its content."""

    target: ReviewTarget
    review_id: int
    output_digest: str


class ReviewClient(Protocol):
    """Injected fixed GitHub effect boundary. No fallback origin or identity."""

    def read_pr(self, repository: str, number: int) -> object: ...
    def authorized_lead(self, repository: str, number: int, head: str) -> int | None: ...
    def create_review(
        self, repository: str, number: int, *, head: str, event: str, body: str,
    ) -> object: ...
    def list_reviews(self, repository: str, number: int, *, limit: int) -> object: ...


def _body(target: ReviewTarget, text: str) -> str:
    if not isinstance(text, str) or not text.strip() or _PREFIX in text or "\x00" in text:
        raise PublicationHeld("invalid COMMENT content")
    try:
        if len(text) > _MAX_TEXT_BYTES or len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
            raise PublicationHeld("invalid COMMENT content")
    except UnicodeError:
        raise PublicationHeld("invalid COMMENT content") from None
    # The first line is the only defined marker position.
    return f"{target.marker}\n\n{text}"


def _receipt(target: ReviewTarget, resource: object, *, body: str | None = None) -> CommentReceipt:
    if not isinstance(resource, dict):
        raise PublicationHeld("exact COMMENT receipt unavailable")
    review_id, actor, content = resource.get("id"), resource.get("user"), resource.get("body")
    if (
        not _positive(review_id) or resource.get("state") != "COMMENTED"
        or resource.get("commit_id") != target.head or resource.get("pull_request_url") != target.pull_url
        or not isinstance(actor, dict) or not _positive(actor.get("id")) or actor["id"] != target.lead_id
        or not isinstance(content, str) or len(content) > _MAX_TEXT_BYTES + 256
        or not content.startswith(target.marker + "\n\n") or (body is not None and content != body)
    ):
        raise PublicationHeld("exact COMMENT receipt unavailable")
    assert isinstance(review_id, int)
    text = content[len(target.marker) + 2:]
    if content != _body(target, text):
        raise PublicationHeld("exact COMMENT receipt unavailable")
    output_digest = sha256(json.dumps(text, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CommentReceipt(target, review_id, output_digest)


class ReviewPublisher:
    """Hold unless one configured repository and the exact positive evidence agree."""

    def __init__(self, client: ReviewClient, *, repository: str) -> None:
        if not isinstance(repository, str) or not _repository(repository):
            raise PublicationHeld("invalid publisher repository")
        self._client = client
        self._repository = repository

    def _validate_scope(self, target: ReviewTarget) -> None:
        if target.repository != self._repository:
            raise PublicationHeld("review repository not allowed")

    def _head(self, target: ReviewTarget) -> None:
        found = self._client.read_pr(target.repository, target.pull_request)
        if not isinstance(found, dict):
            raise PublicationHeld("current pull request unavailable")
        head, base = found.get("head"), found.get("base")
        repo = base.get("repo") if isinstance(base, dict) else None
        if (
            not _positive(found.get("number")) or found["number"] != target.pull_request
            or found.get("url") != target.pull_url or found.get("state") != "open"
            or not isinstance(repo, dict) or repo.get("full_name") != target.repository
            or not isinstance(head, dict) or head.get("sha") != target.head
        ):
            raise PublicationHeld("current pull request does not match")

    def publish(self, target: ReviewTarget, text: str) -> CommentReceipt:
        """One fixed COMMENT POST after the outer durable one-use claim."""
        self._validate_scope(target)
        body = _body(target, text)
        try:
            self._head(target)
            actor = self._client.authorized_lead(target.repository, target.pull_request, target.head)
            if not _positive(actor) or actor != target.lead_id:
                raise PublicationHeld("current Lead authority held")
            self._head(target)
        except (OSError, RuntimeError, ValueError):
            raise PublicationHeld("COMMENT not attempted") from None
        try:
            response = self._client.create_review(
                target.repository, target.pull_request, head=target.head, event="COMMENT", body=body,
            )
            return _receipt(target, response, body=body)
        except (OSError, RuntimeError, ValueError):
            # No retry, fallback, or implicit lookup after an ambiguous POST.
            raise PublicationHeld("COMMENT outcome unknown") from None

    def lookup(self, target: ReviewTarget) -> CommentReceipt | None:
        """Inspect only the original attempt; bound the read and never POST."""
        self._validate_scope(target)
        try:
            page = self._client.list_reviews(target.repository, target.pull_request, limit=_LIMIT)
            if not isinstance(page, (list, tuple)) or len(page) >= _LIMIT:
                raise PublicationHeld("bounded COMMENT lookup incomplete")
            matches: list[CommentReceipt] = []
            for resource in page:
                if not isinstance(resource, dict):
                    raise PublicationHeld("bounded COMMENT lookup malformed")
                content = resource.get("body")
                if not isinstance(content, str):
                    raise PublicationHeld("bounded COMMENT lookup malformed")
                if len(content) > _MAX_TEXT_BYTES + 256:
                    raise PublicationHeld("bounded COMMENT lookup incomplete")
                if content.startswith(target.marker + "\n"):
                    matches.append(_receipt(target, resource))
            if len(matches) > 1:
                raise PublicationHeld("exact COMMENT lookup ambiguous")
            return matches[0] if matches else None
        except (OSError, RuntimeError, ValueError):
            raise PublicationHeld("COMMENT lookup held") from None
