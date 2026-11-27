"""Offline exact COMMENT and read-only reconciliation at a fake transport."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from lighthouse.adapters.github.review_publisher import (
    CommentReceipt,
    PublicationHeld,
    ReviewPublisher,
    ReviewTarget,
)

TARGET = ReviewTarget("owner/example", 19, "a" * 40, 205, "c" * 64)
DIGEST = sha256(json.dumps("One synthetic comment.", sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Client:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.next_head = TARGET.head
        self.actor = TARGET.lead_id
        self.late = False
        self.failure = False
        self.result_drift: dict[str, object] = {}
        self.rows: list[object] = []

    def read_pr(self, repository: str, number: int) -> object:
        assert (repository, number) == (TARGET.repository, TARGET.pull_request)
        self.calls.append("read")
        return {
            "number": number, "url": TARGET.pull_url, "state": "open",
            "base": {"repo": {"full_name": repository}}, "head": {"sha": self.next_head},
        }

    def authorized_lead(self, repository: str, number: int, head: str) -> int:
        assert (repository, number, head) == (TARGET.repository, TARGET.pull_request, TARGET.head)
        self.calls.append("authorize")
        if self.late:
            self.next_head = "b" * 40
        return self.actor

    def create_review(
        self, repository: str, number: int, *, head: str, event: str, body: str,
    ) -> object:
        assert (repository, number, head, event) == (TARGET.repository, TARGET.pull_request, TARGET.head, "COMMENT")
        assert body == TARGET.marker + "\n\nOne synthetic comment."
        self.calls.append("post")
        record = {
            "id": 99, "state": "COMMENTED", "pull_request_url": TARGET.pull_url,
            "commit_id": head, "user": {"id": TARGET.lead_id}, "body": body,
        } | self.result_drift
        self.rows.append(deepcopy(record))
        if self.failure:
            raise OSError("synthetic internal reply lost")
        return record

    def list_reviews(self, repository: str, number: int, *, limit: int) -> object:
        assert (repository, number, limit) == (TARGET.repository, TARGET.pull_request, 100)
        self.calls.append("lookup")
        return deepcopy(self.rows)


def test_publish_and_lookup_the_exact_comment() -> None:
    client = Client()
    publisher = ReviewPublisher(client, repository=TARGET.repository)
    receipt = publisher.publish(TARGET, "One synthetic comment.")
    assert receipt == CommentReceipt(TARGET, 99, DIGEST)
    assert client.calls == ["read", "authorize", "read", "post"]
    assert publisher.lookup(TARGET) == receipt
    assert client.calls[-1] == "lookup"


@pytest.mark.parametrize("field", ["head", "authority", "late-head", "repository", "spoofed-body"])
def test_holds_before_post_when_current_exact_gate_changes(field: str) -> None:
    client = Client()
    publisher = ReviewPublisher(client, repository="owner/not-allowed" if field == "repository" else TARGET.repository)
    if field == "head":
        client.next_head = "b" * 40
    elif field == "authority":
        client.actor += 1
    elif field == "late-head":
        client.late = True
    with pytest.raises(PublicationHeld):
        publisher.publish(TARGET, TARGET.marker if field == "spoofed-body" else "One synthetic comment.")
    assert "post" not in client.calls and "lookup" not in client.calls


@pytest.mark.parametrize("changes", [
    {"id": True}, {"state": "APPROVED"}, {"commit_id": "b" * 40},
    {"pull_request_url": "https://api.github.com/repos/foreign/repo/pulls/19"},
    {"user": {"id": 404}}, {"body": "uncorrelated response"},
])
def test_inexact_post_response_is_unknown_without_retry(changes: dict[str, object]) -> None:
    client = Client()
    client.result_drift = changes
    publisher = ReviewPublisher(client, repository=TARGET.repository)
    with pytest.raises(PublicationHeld, match="outcome unknown"):
        publisher.publish(TARGET, "One synthetic comment.")
    assert client.calls == ["read", "authorize", "read", "post"]


def test_ambiguous_post_never_replays_even_when_head_has_advanced() -> None:
    client = Client()
    client.failure = True
    publisher = ReviewPublisher(client, repository=TARGET.repository)
    with pytest.raises(PublicationHeld, match="outcome unknown") as cause:
        publisher.publish(TARGET, "One synthetic comment.")
    assert "internal" not in str(cause.value)
    assert client.calls == ["read", "authorize", "read", "post"]
    client.next_head = "b" * 40
    assert publisher.lookup(TARGET) == CommentReceipt(TARGET, 99, DIGEST)
    client.rows += client.rows
    with pytest.raises(PublicationHeld, match="lookup held"):
        publisher.lookup(TARGET)
    assert client.calls.count("post") == 1


def test_lookup_does_not_choose_another_attempt_or_accept_truncated_list() -> None:
    client = Client()
    publisher = ReviewPublisher(client, repository=TARGET.repository)
    client.rows = [{"body": "<!-- lighthouse:codex-dispatch-v1:" + "d" * 64 + " -->\n\nDifferent attempt."}]
    assert publisher.lookup(TARGET) is None
    client.rows *= 100
    with pytest.raises(PublicationHeld):
        publisher.lookup(TARGET)
    assert client.calls == ["lookup", "lookup"]
