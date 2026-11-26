"""Repository-scoped GitHub GET boundary; no redirects or credential loaders."""

import http.client
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit

from lighthouse.adapters.github.facts import API_VERSION

ORIGIN = "https://api.github.com"
MEDIA = "application/vnd.github+json"
MAX_BODY = 2_000_000


class Held(ValueError):
    """Fixed diagnostic for incomplete collection."""


@dataclass(frozen=True)
class Scope:
    repository: str
    read_identity: int
    ready_label: str

    def target(self, url: str) -> str:
        """Validate destination and endpoint-specific query before any send."""
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository)
                or any(piece in (".", "..") for piece in self.repository.split("/"))
                or not url.startswith(ORIGIN + "/") or any(ord(c) <= 32 for c in url)):
            raise Held("destination")
        parsed = urlsplit(url)
        root = f"/repos/{self.repository}"
        suffix = parsed.path.removeprefix(root)
        if (parsed.netloc != "api.github.com" or "#" in url
                or not parsed.path.startswith(root)
                or not re.fullmatch(
                    r"(?:|/issues(?:/[1-9][0-9]*(?:/events)?)?"
                    r"|/pulls(?:/[1-9][0-9]*(?:/reviews)?)?)", suffix,
                )):
            raise Held("destination")
        try:
            pairs = parse_qsl(parsed.query, strict_parsing=True, max_num_fields=4)
        except ValueError:
            raise Held("destination-query") from None
        query = dict(pairs)
        if len(query) != len(pairs):
            raise Held("destination-query")
        listing = suffix in ("/issues", "/pulls") or suffix.endswith(("/events", "/reviews"))
        expected = {"page", "per_page"} if listing else set()
        if suffix == "/issues":
            expected |= {"labels", "state"}
            label = query.get("labels", "")
            if query.get("state") != "open" or not label or label != self.ready_label:
                raise Held("destination-query")
        if suffix == "/pulls":
            expected.add("state")
            if query.get("state") != "all":
                raise Held("destination-query")
        if set(query) != expected or (
            listing and (query["per_page"] != "100" or not re.fullmatch(r"[1-9][0-9]{0,6}", query["page"]))
        ):
            raise Held("destination-query")
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes = b""


class GetTransport(Protocol):
    scope: Scope

    def get(self, url: str, *, etag: str | None, timeout: float) -> Response: ...


class HTTPSGet:
    """Dormant stdlib GET transport with an explicitly injected bearer."""

    def __init__(self, scope: Scope, bearer: str) -> None:
        self.scope = scope
        self._bearer = bearer

    def get(self, url: str, *, etag: str | None, timeout: float) -> Response:
        if not 0 < timeout <= 30:
            raise Held("invalid-timeout")
        target = self.scope.target(url)
        headers = {
            "Accept": MEDIA, "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "Lighthouse-readonly", "Authorization": f"Bearer {self._bearer}",
        }
        if etag:
            headers["If-None-Match"] = etag
        conn = http.client.HTTPSConnection("api.github.com", timeout=timeout)
        try:
            conn.request("GET", target, headers=headers)
            with conn.getresponse() as response:
                body = response.read(MAX_BODY + 1) if response.status == 200 else b""
                return Response(response.status, {k.lower(): v for k, v in response.getheaders()}, body)
        finally:
            conn.close()
