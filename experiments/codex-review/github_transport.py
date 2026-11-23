"""Deferred fixed-origin GitHub transport and one-shot Lead COMMENT publisher."""
import http.client
import json
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from authorization import (
    REPOSITORY,
    CommentFact,
    Denied,
    PullFact,
    VerifiedExecution,
    private_receipt_binding,
)

HOST = "api.github.com"
REPO = "/repos/" + REPOSITORY
LEAD_APP = 5869282
LEAD_ACTOR = 359712317


class Wire(Protocol):
    """Bounded authenticated HTTP boundary; tests provide a synthetic endpoint."""

    def __call__(
        self, method: str, path: str, token: str, body: dict[str, object] | None, timeout: float,
    ) -> object: ...


def https_json(
    method: str, path: str, token: str, body: dict[str, object] | None, timeout: float,
) -> object:
    """Use GitHub's fixed HTTPS origin, no redirects, retries, or unbounded reads."""
    if not path.startswith("/") or path.startswith("//") or method not in {"GET", "POST"}:
        raise Denied("GitHub request origin is fixed.")
    client = http.client.HTTPSConnection(HOST, timeout=timeout)
    try:
        client.request(method, path, json.dumps(body) if body is not None else None, {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "lighthouse-t01",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        response = client.getresponse()
        if response.status not in (200, 201):
            raise Denied("GitHub could not confirm the requested operation.")
        data = response.read(1_048_577)
        if len(data) > 1_048_576:
            raise Denied("GitHub response too large.")
        decoded: object = json.loads(data)
        return decoded
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        raise Denied("GitHub request outcome unconfirmed.") from None
    finally:
        client.close()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise Denied("Unexpected GitHub evidence.")
    return {key: item for key, item in value.items()}


def _positive(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise Denied("Unexpected GitHub numeric identity.")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise Denied("GitHub evidence is incomplete.")
    return value


def _date(value: object) -> datetime:
    try:
        stamp = datetime.fromisoformat(_text(value))
    except ValueError:
        raise Denied("GitHub evidence timestamp is invalid.") from None
    if stamp.utcoffset() is None:
        raise Denied("GitHub evidence timestamp is unqualified.")
    return stamp


class GithubTransport:
    """Use existing Lead App identity lazily; one repository and one scope per instance."""

    def __init__(
        self, *, jwt: Callable[[], str], repository_id: int, remaining: Callable[[], float],
        scope: Literal["verifier", "publisher"], wire: Wire = https_json,
    ) -> None:
        self._jwt = jwt
        self._repository_id = repository_id
        self._remaining = remaining
        self._scope = scope
        self._wire = wire
        self._token: str | None = None

    def _call(
        self, method: str, path: str, token: str, body: dict[str, object] | None = None,
    ) -> object:
        remaining = self._remaining()
        if not math.isfinite(remaining) or remaining <= 0:
            raise Denied("GitHub stage expired.")
        return self._wire(method, path, token, body, min(5.0, remaining))

    def verify_identity(self) -> None:
        """Mint and independently confirm the repository-only verifier/publisher scope."""
        if self._token is not None:
            return
        remaining = self._remaining()
        if not math.isfinite(remaining) or remaining <= 0:
            raise Denied("GitHub stage expired.")
        try:
            jwt = _text(self._jwt())
        except (OSError, ValueError):
            raise Denied("Lead identity unavailable.") from None
        app = _object(self._call("GET", "/app", jwt))
        if app.get("id") != LEAD_APP or app.get("slug") != "codex-lead-engineer":
            raise Denied("Unexpected GitHub App identity.")
        installation = _object(self._call("GET", REPO + "/installation", jwt))
        if installation.get("app_id") != LEAD_APP:
            raise Denied("Unexpected GitHub App installation.")
        install_id = _positive(installation.get("id"))
        if self._scope == "verifier":
            permissions = {"issues": "read", "pull_requests": "read", "metadata": "read"}
        else:
            permissions = {"pull_requests": "write", "metadata": "read"}
        response = _object(self._call(
            "POST", f"/app/installations/{install_id}/access_tokens", jwt,
            {"repository_ids": [self._repository_id], "permissions": permissions},
        ))
        token = _text(response.get("token"))
        if response.get("permissions") != permissions:
            raise Denied("Unexpected GitHub App permission scope.")
        repos = _object(self._call("GET", "/installation/repositories", token))
        listed = repos.get("repositories")
        if (repos.get("total_count") != 1 or not isinstance(listed, list) or len(listed) != 1
                or _object(listed[0]).get("id") != self._repository_id
                or _object(listed[0]).get("full_name") != REPOSITORY):
            raise Denied("Unexpected GitHub App repository scope.")
        self._token = token

    def _installation_request(
        self, method: str, path: str, body: dict[str, object] | None = None,
    ) -> object:
        self.verify_identity()
        assert self._token is not None
        return self._call(method, path, self._token, body)

    def comment(self, comment_id: int) -> CommentFact:
        """Fetch a fresh Issue #4 comment; never synthesize missing App attribution."""
        if self._scope != "verifier":
            raise Denied("Execution verification requires the read-only verifier.")
        comment_id = _positive(comment_id)
        data = _object(self._installation_request("GET", REPO + f"/issues/comments/{comment_id}"))
        if data.get("issue_url") != "https://" + HOST + REPO + "/issues/4":
            raise Denied("Execution attestation is not on Issue #4.")
        app = data.get("performed_via_github_app")
        return CommentFact(
            _positive(data.get("id")), self._repository_id, 4,
            _positive(_object(data.get("user")).get("id")),
            _positive(_object(app).get("id")) if app is not None else None,
            _text(data.get("body")), _date(data.get("created_at")), _date(data.get("updated_at")),
        )

    def pull(self) -> PullFact:
        """Fetch PR facts from GitHub and require the exact fixed target repository."""
        data = _object(self._installation_request("GET", REPO + "/pulls/14"))
        base = _object(data.get("base"))
        base_repo = _object(base.get("repo"))
        head = _object(data.get("head"))
        head_repo = _object(head.get("repo"))
        if head_repo.get("id") != self._repository_id or head_repo.get("full_name") != REPOSITORY:
            raise Denied("PR head is not in the approved repository.")
        return PullFact(
            _positive(base_repo.get("id")), _text(base_repo.get("full_name")),
            _positive(data.get("number")), _text(base.get("ref")), _text(head.get("sha")),
            _positive(_object(data.get("user")).get("id")), data.get("state") == "open",
        )

    def _create_comment_review(self, head: str, body: str) -> object:
        """Submit only the COMMENT event, explicitly pinned to the reviewed commit."""
        if self._scope != "publisher":
            raise Denied("Read-only verifier cannot publish.")
        if re.fullmatch(r"[0-9a-f]{40}", head) is None:
            raise Denied("COMMENT requires an exact commit SHA.")
        return self._installation_request("POST", REPO + "/pulls/14/reviews", {
            "event": "COMMENT", "commit_id": head, "body": body,
        })

    def review_page(self, page: int) -> list[object]:
        """Read one bounded page for lookup-only recovery."""
        if self._scope != "publisher" or type(page) is not int or not 1 <= page <= 5:
            raise Denied("Review lookup exceeded its approved scope.")
        data = self._installation_request("GET", REPO + f"/pulls/14/reviews?per_page=100&page={page}")
        if not isinstance(data, list):
            raise Denied("Unexpected GitHub review evidence.")
        return list(data)


@dataclass(frozen=True, repr=False)
class CompletedReview:
    """Output attributed by the review worker to the completed approved run."""

    packet_sha256: str
    head: str
    thread: str
    turn: str
    text: str


@dataclass(frozen=True)
class PublishedComment:
    """Confirmation of the one exact-head COMMENT; never implies current freshness."""

    review_id: int
    head: str
    reviewer: int


class CommentPublisher:
    """Consume one durable COMMENT attempt, then reconcile only its original facts."""

    def __init__(
        self, transport: GithubTransport, verified: VerifiedExecution, journal_root: Path,
    ) -> None:
        self._transport = transport
        self._verified = verified
        self._root = journal_root

    def _binding(self) -> tuple[Path, str, bytes]:
        packet = self._verified.packet
        if private_receipt_binding(self._root) != packet.receipt_binding:
            raise Denied("Publication receipt directory is not authorized.")
        root = self._root.resolve(strict=True)
        claim_path = root / f"t01-{self._verified.comment_id}.claim"
        intent = root / f"t01-{self._verified.comment_id}.comment-attempt"
        marker = f"<!-- lighthouse-t01-comment:{self._verified.comment_id}:{packet.dispatch_id} -->"
        expected_claim = f"{self._verified.packet_sha256}\n{packet.dispatch_id}\n".encode("ascii")
        try:
            with claim_path.open("rb") as f:
                if f.read(len(expected_claim) + 1) != expected_claim:
                    raise Denied("Publication has no matching run claim.")
        except OSError:
            raise Denied("Publication has no matching run claim.") from None
        bits = f"{packet.head}\n{self._verified.packet_sha256}\n{LEAD_ACTOR}\n{marker}\n"
        return intent, marker, bits.encode("ascii")

    def publish(
        self, review: CompletedReview, validate_current: Callable[[], VerifiedExecution],
    ) -> PublishedComment:
        """Post once only after independent fresh authority, target and output checks."""
        intent, marker, binding = self._binding()
        packet = self._verified.packet
        if (review.packet_sha256 != self._verified.packet_sha256 or review.head != packet.head
                or not review.thread or not review.turn or not review.text
                or len(review.text) > 32_000 or "lighthouse-t01-comment:" in review.text):
            raise Denied("Review output does not match the completed authorized run.")
        if intent.exists():
            raise Denied("COMMENT already attempted; lookup required.")
        self._transport.verify_identity()
        fresh = validate_current()
        if fresh != self._verified or self._transport.pull() != PullFact(
            packet.repository_id, packet.repository, packet.pr, packet.base, packet.head,
            packet.dot_actor, True,
        ):
            raise Denied("COMMENT target authorization is no longer current.")
        try:
            with intent.open("xb") as f:
                f.write(binding)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            raise Denied("COMMENT already attempted or intent persistence unknown.") from None
        result = self._receipt(self._transport._create_comment_review(
            packet.head, marker + "\n" + review.text,
        ), marker)
        if result is None:
            raise Denied("COMMENT acknowledgement is unconfirmed; lookup required.")
        return result

    def reconcile(self) -> PublishedComment | None:
        """Search for the original receipt without checking or writing to a new head."""
        intent, marker, binding = self._binding()
        try:
            with intent.open("rb") as f:
                matching = f.read(len(binding) + 1) == binding
        except OSError:
            raise Denied("No verifiable COMMENT intent.") from None
        if not matching:
            raise Denied("No verifiable COMMENT intent.")
        found: set[PublishedComment] = set()
        for page in range(1, 6):
            items = self._transport.review_page(page)
            for value in items:
                result = self._receipt(value, marker)
                if result is not None:
                    found.add(result)
            if len(items) < 100:
                if len(found) > 1:
                    raise Denied("Multiple matching review receipts; hold.")
                return next(iter(found), None)
        raise Denied("Review lookup could not establish a complete result.")

    def _receipt(self, value: object, marker: str) -> PublishedComment | None:
        row = _object(value)
        if (row.get("state") != "COMMENTED" or row.get("commit_id") != self._verified.packet.head
                or _object(row.get("user")).get("id") != LEAD_ACTOR):
            return None
        body = row.get("body")
        if not isinstance(body, str) or body.split("\n", 1)[0] != marker:
            return None
        return PublishedComment(_positive(row.get("id")), self._verified.packet.head, LEAD_ACTOR)
