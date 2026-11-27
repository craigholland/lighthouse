"""Exercise the concrete GitHub HTTP boundary with injected stdlib connections."""

import json
from collections import deque
from typing import Any

import pytest

from lighthouse.adapters.github import review_http
from lighthouse.adapters.github.review_publisher import (
    PublicationHeld,
    ReviewPublisher,
    ReviewTarget,
)

REPO, PR, HEAD, LEAD = "example/project", 8, "a" * 40, 12
BASE = f"/repos/{REPO}/pulls/{PR}"
URL = "https://api.github.com" + BASE
TARGET = ReviewTarget(REPO, PR, HEAD, LEAD, "b" * 64)


class Response:
    def __init__(self, status: int, payload: object, *, link: str = "") -> None:
        self.status = status
        self._data = bytearray(json.dumps(payload).encode())
        self.length = len(self._data)
        self.link = link

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def getheader(self, name: str):
        assert name == "Link"
        return self.link

    def read1(self, size: int) -> bytes:
        data = bytes(self._data[:size])
        del self._data[:size]
        self.length -= len(data)
        return data


class HTTPS:
    """Fakes only the standard-library TLS/HTTP connection, below the client."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.responses: deque[Any] = deque()
        self.requests: list[Any] = []
        self.reviews: list[dict[str, Any]] = []
        self.lose_post = False
        self.wrong_actor = False
        self.head = HEAD
        monkeypatch.setattr(review_http.http.client, "HTTPSConnection", self.connection)

    def connection(self, host: str, *, timeout: float):
        assert host == "api.github.com" and 0 < timeout <= 10
        fixture = self

        class Connection:
            def settimeout(self, step: float) -> None:
                assert 0 < step <= timeout

            def connect(self):
                self.sock = self

            def putrequest(self, method, target):
                self.requested = [method, target, None]
                self.headers = {}

            def putheader(self, name, value):
                self.headers[name] = value

            def endheaders(self):
                method, target, _ = self.requested
                headers = self.headers
                assert headers["Authorization"] == "Bearer fixture_only"
                assert headers["Accept"] == "application/vnd.github+json"
                assert headers["X-GitHub-Api-Version"]
                assert target.split("?", 1)[0] in {BASE, BASE + "/reviews"}
                if method == "POST":
                    assert "Content-Length" in headers
                fixture.requests.append(self.requested)

            def send(self, body):
                assert int(self.headers["Content-Length"]) == len(body)
                self.requested[2] = body

            def getresponse(self):
                method, target, body = self.requested
                if fixture.responses:
                    outcome = fixture.responses.popleft()
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome
                if method == "POST":
                    content = json.loads(body)
                    assert content["event"] == "COMMENT" and content["commit_id"] == HEAD
                    review = {"id": 51, "commit_id": HEAD, "user": {"id": 99 if fixture.wrong_actor else LEAD},
                              "state": "COMMENTED", "body": content["body"], "pull_request_url": URL}
                    fixture.reviews.append(review)
                    if fixture.lose_post:
                        raise TimeoutError("fixture timeout, no private diagnostics")
                    return Response(200, review)
                if target == BASE:
                    return Response(200, {"number": PR, "url": URL, "state": "open",
                                          "base": {"repo": {"full_name": REPO}}, "head": {"sha": fixture.head}})
                assert target == BASE + "/reviews?per_page=100&page=1"
                return Response(200, fixture.reviews)

            def close(self):
                pass

        return Connection()


@pytest.mark.parametrize("fault", ["valid", "stale", "wrong-actor", "wrong-authority", "lost-ack"])
def test_comment_and_lookup_use_actual_bound_http_client(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    http = HTTPS(monkeypatch)
    http.lose_post = fault == "lost-ack"
    http.wrong_actor = fault == "wrong-actor"
    if fault == "stale":
        http.head = "c" * 40
    client = review_http.HTTPSReviewClient(REPO, PR, "fixture_only",
                                         lambda *_: 99 if fault == "wrong-authority" else LEAD)
    publisher = ReviewPublisher(client, repository=REPO)
    if fault == "valid":
        assert publisher.publish(TARGET, "Synthetic review").review_id == 51
    else:
        with pytest.raises(PublicationHeld, match="COMMENT"):
            publisher.publish(TARGET, "Synthetic review")
    assert sum(method == "POST" for method, *_ in http.requests) == (fault in {"valid", "wrong-actor", "lost-ack"})
    if fault == "lost-ack":
        assert publisher.lookup(TARGET).review_id == 51
        assert sum(method == "POST" for method, *_ in http.requests) == 1
    with pytest.raises(PublicationHeld):
        client.read_pr(REPO, PR + 1)


@pytest.mark.parametrize("response", [
    Response(301, {}), Response(401, {}), Response(429, {}),
    Response(200, "x" * (review_http.MAX_BODY + 1)), TimeoutError("fixture_only"),
])
def test_http_faults_are_fixed_holds_without_retry(monkeypatch: pytest.MonkeyPatch, response: object) -> None:
    transport = HTTPS(monkeypatch)
    transport.responses.append(response)
    client = review_http.HTTPSReviewClient(REPO, PR, "fixture_only", lambda *_: LEAD)
    with pytest.raises(PublicationHeld, match="review response unavailable") as error:
        client.read_pr(REPO, PR)
    assert "fixture_only" not in str(error.value) and len(transport.requests) == 1
