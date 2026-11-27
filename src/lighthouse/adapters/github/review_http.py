"""Exact, dormant GitHub review HTTP client; no credential acquisition."""

import http.client
import json
import math
import re
from collections.abc import Callable
from queue import Empty, Queue
from threading import Lock, Thread
from time import monotonic

from lighthouse.adapters.github.facts import API_VERSION
from lighthouse.adapters.github.review_publisher import PublicationHeld
from lighthouse.adapters.github.transport import MAX_BODY, MEDIA

_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_HEAD = re.compile(r"[0-9a-f]{40}")


class HTTPSReviewClient:
    """Own one fixed repository/PR and at most one bounded request worker."""

    def __init__(
        self, repository: str, number: int, bearer: str,
        authority: Callable[[str, int, str], int | None], *, timeout: float = 10,
    ) -> None:
        if (not _REPO.fullmatch(repository) or any(x in {".", ".."} for x in repository.split("/"))
                or type(number) is not int or not 0 < number < 2**63
                or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,512}", bearer)
                or not math.isfinite(timeout) or not 0 < timeout <= 30):
            raise PublicationHeld("invalid private GitHub binding")
        self._repository, self._number, self._bearer = repository, number, bearer
        self._authority, self._timeout, self._inflight = authority, timeout, Lock()

    def _target(self, repository: str, number: int) -> str:
        if type(number) is not int or (repository, number) != (self._repository, self._number):
            raise PublicationHeld("review destination not allowed")
        return f"/repos/{self._repository}/pulls/{self._number}"

    def read_pr(self, repository: str, number: int) -> object:
        return self._request("GET", self._target(repository, number))

    def authorized_lead(self, repository: str, number: int, head: str) -> int | None:
        self._target(repository, number)
        return self._authority(repository, number, head) if _HEAD.fullmatch(head) else None

    def create_review(self, repository: str, number: int, *, head: str, event: str, body: str) -> object:
        target = self._target(repository, number)
        if (event != "COMMENT" or not _HEAD.fullmatch(head) or not body.strip()
                or len(body) > 16640 or len(body.encode(errors="replace")) > 16640):
            raise PublicationHeld("review action not allowed")
        payload = json.dumps({"commit_id": head, "event": "COMMENT", "body": body}).encode()
        return self._request("POST", target + "/reviews", payload)

    def list_reviews(self, repository: str, number: int, *, limit: int) -> object:
        target = self._target(repository, number)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise PublicationHeld("review lookup not bounded")
        return self._request("GET", f"{target}/reviews?per_page={limit}&page=1")

    def _request(self, method: str, target: str, body: bytes | None = None) -> object:
        if not self._inflight.acquire(blocking=False):
            raise PublicationHeld("previous review request unresolved")
        deadline = monotonic() + self._timeout
        done: Queue[tuple[bool, object]] = Queue(1)

        def perform() -> None:
            try:
                value = (True, self._exchange(method, target, body, deadline))
            except Exception:
                value = (False, None)
            finally:
                self._inflight.release()
            done.put_nowait(value)

        try:
            Thread(target=perform, daemon=True).start()
        except Exception:
            self._inflight.release()
            raise PublicationHeld("review request unavailable") from None
        try:
            ok, value = done.get(timeout=max(0, deadline - monotonic()))
        except Empty:
            raise PublicationHeld("review request deadline elapsed") from None
        if not ok or monotonic() >= deadline:
            raise PublicationHeld("review response unavailable")
        return value

    def _exchange(self, method: str, target: str, body: bytes | None, deadline: float) -> object:
        def remaining() -> float:
            left = deadline - monotonic()
            if left <= 0:
                raise TimeoutError
            return left

        headers = {"Accept": MEDIA, "X-GitHub-Api-Version": API_VERSION,
                   "User-Agent": "Lighthouse-review", "Authorization": f"Bearer {self._bearer}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPSConnection("api.github.com", timeout=remaining())
        try:
            # Resolve and establish TLS before checking the last send budget.
            conn.connect()
            sock = conn.sock
            if sock is None:
                raise OSError
            conn.putrequest(method, target)
            for name, value in headers.items():
                conn.putheader(name, value)
            sock.settimeout(remaining())
            conn.endheaders()
            if body is not None:
                # Header transmission can consume the remaining budget.
                sock.settimeout(remaining())
                conn.send(body)
            sock.settimeout(remaining())
            with conn.getresponse() as response:
                if response.status not in ({200, 201} if method == "POST" else {200}):
                    raise PublicationHeld("review response unavailable")
                if "/reviews?" in target and response.getheader("Link"):
                    raise PublicationHeld("review pagination not proven complete")
                data = bytearray()
                while len(data) <= MAX_BODY:
                    sock.settimeout(remaining())
                    chunk = response.read1(min(65536, MAX_BODY + 1 - len(data)))
                    if not chunk:
                        break
                    data += chunk
                if len(data) > MAX_BODY or response.length not in (0, None):
                    raise PublicationHeld("review response incomplete")
                remaining()
                return json.loads(data)
        finally:
            conn.close()
