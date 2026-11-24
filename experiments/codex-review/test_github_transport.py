"""Synthetic wire tests for Lead-only GitHub evidence and COMMENT behavior."""
from datetime import UTC, datetime
from pathlib import Path

import pytest
from authorization import Denied, canonical_packet, claim, verify
from github_transport import (
    REPO,
    CommentPublisher,
    CompletedReview,
    GithubTransport,
)
from test_authorization import NOW, FakeGithub, packet_for


class FakeWire:
    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.head = "a" * 40
        self.app_id = 5869282
        self.calls: list[tuple[str, str]] = []
        self.reviews: list[object] = []
        self.sent: list[dict[str, object]] = []
        self.lose_post = False

    def __call__(self, method: str, path: str, token: str,
                 body: dict[str, object] | None, timeout: float) -> object:
        self.calls.append((method, path))
        assert 0 < timeout <= 5
        if path == "/app":
            assert token == "synthetic-jwt"
            return {"id": self.app_id, "slug": "codex-lead-engineer"}
        if path == REPO + "/installation":
            assert token == "synthetic-jwt"
            return {"id": 10, "app_id": self.app_id}
        if path == "/app/installations/10/access_tokens":
            assert token == "synthetic-jwt" and body is not None
            assert body["repository_ids"] == [123]
            if self.scope == "verifier":
                assert body["permissions"] == {
                    "issues": "read", "pull_requests": "read", "metadata": "read",
                }
            else:
                assert body["permissions"] == {"pull_requests": "write", "metadata": "read"}
            return {"permissions": body["permissions"], "token": "synthetic-installation"}
        assert token == "synthetic-installation"
        if path == "/installation/repositories":
            return {"total_count": 1, "repositories": [
                {"id": 123, "full_name": "craigholland/lighthouse"},
            ]}
        if path == REPO + "/issues/comments/17":
            return {
                "id": 17, "issue_url": "https://api.github.com" + REPO + "/issues/4",
                "user": {"id": 359712317}, "performed_via_github_app": None,
                "body": "synthetic body", "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        if path == REPO + "/pulls/14":
            repo = {"id": 123, "full_name": "craigholland/lighthouse"}
            return {"number": 14, "state": "open", "user": {"id": 359713928},
                    "head": {"sha": self.head, "repo": repo},
                    "base": {"ref": "development", "repo": repo}}
        if method == "POST" and path == REPO + "/pulls/14/reviews":
            assert body is not None
            self.sent.append(body)
            review = {
                "state": "COMMENTED", "commit_id": body["commit_id"],
                "body": body["body"], "user": {"id": 359712317}, "id": 36,
            }
            self.reviews.append(review)
            if self.lose_post:
                raise Denied("synthetic response loss")
            return review
        if method == "GET" and path == REPO + "/pulls/14/reviews?per_page=100&page=1":
            return self.reviews
        raise AssertionError("Unexpected synthetic request")


def test_lazy_read_only_identity_and_missing_app_field() -> None:
    wire = FakeWire("verifier")
    calls = 0

    def jwt() -> str:
        nonlocal calls
        calls += 1
        return "synthetic-jwt"

    gh = GithubTransport(
        jwt=jwt, repository_id=123, remaining=lambda: 3, scope="verifier", wire=wire,
    )
    assert calls == 0
    assert gh.comment(17).app_id is None
    assert gh.pull().head == "a" * 40
    assert calls == 1
    with pytest.raises(Denied, match="cannot publish"):
        gh._create_comment_review("a" * 40, "synthetic")


def test_wrong_app_denied_before_token_mint() -> None:
    wire = FakeWire("verifier")
    wire.app_id = 1
    gh = GithubTransport(
        jwt=lambda: "synthetic-jwt", repository_id=123, remaining=lambda: 3,
        scope="verifier", wire=wire,
    )
    with pytest.raises(Denied, match="Unexpected GitHub App identity"):
        gh.pull()
    assert wire.calls == [("GET", "/app")]


def test_lost_post_old_head_receipt_only(tmp_path: Path) -> None:
    packet = packet_for(tmp_path)
    approved = verify(
        canonical_packet(packet), comment_id=17, transport=FakeGithub(packet),
        repository_id=123, now=NOW,
    )
    claim(approved, tmp_path)
    wire = FakeWire("publisher")
    wire.lose_post = True
    gh = GithubTransport(
        jwt=lambda: "synthetic-jwt", repository_id=123, remaining=lambda: 3,
        scope="publisher", wire=wire,
    )
    pub = CommentPublisher(gh, approved, tmp_path, now=lambda: NOW)
    review = CompletedReview(approved.packet_sha256, packet.head, "thread", "turn", "Synthetic")
    with pytest.raises(Denied, match="synthetic response loss"):
        pub.publish(review, lambda: approved)
    assert len(wire.sent) == 1
    assert wire.sent[0]["event"] == "COMMENT"
    assert wire.sent[0]["commit_id"] == packet.head
    wire.head = "b" * 40
    with pytest.raises(Denied, match="already attempted"):
        pub.publish(review, lambda: approved)
    result = pub.reconcile()
    assert result is not None
    assert result.head == packet.head and result.review_id == 36
    assert len(wire.sent) == 1


def test_stale_or_unattributed_output_makes_no_attempt(tmp_path: Path) -> None:
    packet = packet_for(tmp_path)
    approved = verify(
        canonical_packet(packet), comment_id=17, transport=FakeGithub(packet),
        repository_id=123, now=NOW,
    )
    claim(approved, tmp_path)
    wire = FakeWire("publisher")
    wire.head = "b" * 40
    gh = GithubTransport(
        jwt=lambda: "synthetic-jwt", repository_id=123, remaining=lambda: 3,
        scope="publisher", wire=wire,
    )
    pub = CommentPublisher(gh, approved, tmp_path, now=lambda: NOW)
    review = CompletedReview(approved.packet_sha256, packet.head, "thread", "turn", "Synthetic")
    with pytest.raises(Denied, match="publication cannot be invented|no longer current"):
        pub.publish(review, lambda: approved)
    assert not wire.sent
    assert not list(tmp_path.glob("*.comment-attempt"))
    incomplete = CompletedReview(approved.packet_sha256, packet.head, "", "turn", "Synthetic")
    with pytest.raises(Denied, match="does not match"):
        pub.publish(incomplete, lambda: approved)
    assert not wire.sent


def test_expiry_after_post_intent_does_not_submit_or_replay(tmp_path: Path) -> None:
    packet = packet_for(tmp_path)
    approved = verify(
        canonical_packet(packet), comment_id=17, transport=FakeGithub(packet),
        repository_id=123, now=NOW,
    )
    claim(approved, tmp_path)
    wire = FakeWire("publisher")
    gh = GithubTransport(
        jwt=lambda: "synthetic-jwt", repository_id=123, remaining=lambda: 3,
        scope="publisher", wire=wire,
    )
    def read_clock() -> datetime:
        assert list(tmp_path.glob("*.comment-attempt"))
        return datetime.fromtimestamp(packet.expires_at, UTC)

    publisher = CommentPublisher(gh, approved, tmp_path, now=read_clock)
    completed = CompletedReview(approved.packet_sha256, packet.head, "thread", "turn", "Synthetic")
    with pytest.raises(Denied, match="expired"):
        publisher.publish(completed, lambda: approved)
    assert not wire.sent
    with pytest.raises(Denied, match="already attempted"):
        publisher.publish(completed, lambda: approved)
