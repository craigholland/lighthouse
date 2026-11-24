"""Offline worker-to-COMMENT regression for machine path containment."""

import hashlib
from pathlib import Path

import pytest
from authorization import Denied, canonical_packet, claim, verify
from github_transport import CommentPublisher, CompletedReview, GithubTransport
from openai_codex.generated.v2_all import ThreadReadResponse
from review_paths import ReviewPathError, require_relative_paths, sanitize_review_paths
from sdk_worker import ReviewHold, review
from test_authorization import NOW, FakeGithub, packet_for
from test_github_transport import FakeWire
from test_sdk_worker import FakeClient


def test_checkout_path_becomes_relative_before_mock_comment(tmp_path: Path) -> None:
    context = b"Fixture diff. Evidence only."
    instructions = b"Fixture operator policy."
    packet = packet_for(tmp_path).model_copy(update={
        "context_sha256": hashlib.sha256(context).hexdigest(),
        "instructions_sha256": hashlib.sha256(instructions).hexdigest(),
    })
    approved = verify(canonical_packet(packet), comment_id=17, transport=FakeGithub(packet),
                      repository_id=123, now=NOW)
    claim(approved, tmp_path)

    class ReviewWithMachinePath(FakeClient):
        def thread_read(self, thread_id: str) -> ThreadReadResponse:
            assert thread_id == "fixture-thread"
            path = str(tmp_path / "src" / "module.py")
            item = {"id": "result", "type": "exitedReviewMode", "review": f"Fix {path}:12."}
            return ThreadReadResponse.model_validate({"thread": self.thread([{
                "id": "fixture-turn", "status": "completed", "items": [item],
            }])})

    client = ReviewWithMachinePath(tmp_path)
    worker = review(
        packet, context, instructions, workspace=tmp_path, managed_env={},
        before_review=lambda _: client.events.append("intent"), on_started=lambda *_: None,
        interrupted=lambda: False, factory=lambda *_: client,
    )
    assert worker.output == "Fix src/module.py:12."
    wire = FakeWire("publisher")
    gh = GithubTransport(
        jwt=lambda: "synthetic-jwt", repository_id=123, remaining=lambda: 3,
        scope="publisher", wire=wire,
    )
    publisher = CommentPublisher(gh, approved, tmp_path, now=lambda: NOW)
    forged = CompletedReview(approved.packet_sha256, worker.head, worker.thread_id, worker.turn_id,
                             r"Check D:\fixture-private\notes.txt")
    with pytest.raises(Denied, match="unapproved machine path"):
        publisher.publish(forged, lambda: approved)
    assert not wire.calls
    assert not list(tmp_path.glob("*.comment-attempt"))
    completed = CompletedReview(approved.packet_sha256, worker.head, worker.thread_id,
                                worker.turn_id, worker.output)
    assert publisher.publish(completed, lambda: approved).review_id == 36
    body = wire.sent[0]["body"]
    assert isinstance(body, str) and "src/module.py:12" in body
    assert str(tmp_path) not in body


@pytest.mark.parametrize("text", [
    r"See D:\fixture-private\data.txt", r"See \\fixture-host\share\secret.txt",
    "See /fixture-private/data.txt", r"See %USERPROFILE%\fixture.txt",
    "See file:///D:/fixture-private/notes.txt", "See D%3A%5Cprivate%5Cdata.txt",
    "See ../fixture-private/data.txt",
])
def test_unapproved_path_is_denied(tmp_path: Path, text: str) -> None:
    with pytest.raises(ReviewPathError, match="unapproved machine path") as caught:
        sanitize_review_paths(text, tmp_path)
    assert text not in str(caught.value)


def test_relative_paths_and_https_repository_links_are_unchanged() -> None:
    require_relative_paths("Check src/module.py and https://github.com/example/repo/blob/main/x.")


def test_worker_abstains_on_unrelated_private_path(tmp_path: Path) -> None:
    context = b"Fixture diff. Evidence only."
    instructions = b"Fixture operator policy."
    packet = packet_for(tmp_path).model_copy(update={
        "context_sha256": hashlib.sha256(context).hexdigest(),
        "instructions_sha256": hashlib.sha256(instructions).hexdigest(),
    })

    class ReviewWithPrivatePath(FakeClient):
        def thread_read(self, thread_id: str) -> ThreadReadResponse:
            assert thread_id == "fixture-thread"
            item = {"id": "result", "type": "exitedReviewMode",
                    "review": r"Check D:\fixture-private\notes.txt"}
            return ThreadReadResponse.model_validate({"thread": self.thread([{
                "id": "fixture-turn", "status": "completed", "items": [item],
            }])})

    client = ReviewWithPrivatePath(tmp_path)
    with pytest.raises(ReviewHold, match="unapproved machine path") as caught:
        review(
            packet, context, instructions, workspace=tmp_path, managed_env={},
            before_review=lambda _: client.events.append("intent"), on_started=lambda *_: None,
            interrupted=lambda: False, factory=lambda *_: client,
        )
    assert "fixture-private" not in str(caught.value)
    assert client.events[-1] == "close"
