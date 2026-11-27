"""One bounded read-only GitHub collection cycle with conditional caching."""

import http.client
import json
import math
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from lighthouse.adapters.github.cache import Cache, Page
from lighthouse.adapters.github.facts import (
    API_VERSION,
    Context,
    GitHubFacts,
    Observation,
    Resources,
    _id,
    _object,
    _objects,
)
from lighthouse.adapters.github.transport import (
    MAX_BODY,
    ORIGIN,
    GetTransport,
    Held,
    Response,
)
from lighthouse.configuration import Labels
from lighthouse.domain.workflow import Project


@dataclass(frozen=True)
class Scan:
    """A failed cycle exposes no authoritative observations."""

    revision: str
    requests: int
    observations: tuple[Observation, ...] = ()
    hold: str | None = None
    retry_at: datetime | None = None


class _Limited(Held):
    def __init__(self, retry_at: datetime | None) -> None:
        super().__init__("rate-limited")
        self.retry_at = retry_at


class GitHubCollector:
    """Compose a repository-scoped transport, durable cache and existing mapper."""

    def __init__(
        self, transport: GetTransport, cache: Cache, project: Project,
        labels: Labels, verification: str,
    ) -> None:
        self._transport, self._cache = transport, cache
        self._default = Context(project, labels, verification, False)

    def collect(
        self, contexts: Mapping[int, Context], *, revision: str, now: datetime,
        budget: int = 20, timeout: float = 5.0,
    ) -> Scan:
        """Discover ready work and reconcile explicit accepted work in one serial call."""
        cycle = _Cycle(self._transport, self._cache, now, budget, timeout)
        try:
            if (not revision or now.utcoffset() is None or type(budget) is not int
                    or not 0 < budget <= 200 or not math.isfinite(timeout) or not 0 < timeout <= 30
                    or self._transport.scope.read_identity != self._default.project.lead
                    or self._transport.scope.ready_label != self._default.labels.ready
                    or self._transport.scope.repository != self._default.project.repository):
                raise Held("invalid-cycle")
            for number, context in contexts.items():
                _id(number)
                if (context.project, context.labels, context.verification) != (
                    self._default.project, self._default.labels, self._default.verification
                ) or (context.work is not None and context.work.issue != number):
                    raise Held("wrong-context")
            ready = cycle.pages("issues", state="open", labels=self._default.labels.ready)
            numbers = {_id(x.get("number")) for x in ready if "pull_request" not in x}
            numbers.update(n for n, ctx in contexts.items() if ctx.work is not None)
            observed = []
            refresh: dict[str, Any] = {}
            for number in sorted(numbers):
                ctx = contexts.get(number, self._default)
                issue_path = f"issues/{number}"
                issue = cycle.detail(issue_path)
                refresh[issue_path] = issue
                events = cycle.pages(f"{issue_path}/events")
                pull, reviews = self._pull(cycle, ctx, refresh)
                observed.append(GitHubFacts(ctx).normalize(Resources(
                    cycle.repository, number, revision, API_VERSION, True,
                    issue, events, pull, reviews,
                )))
            for path, original in refresh.items():
                if cycle.detail(path, fresh=True) != original:
                    raise Held("resource-drift")
            return Scan(revision, cycle.count, tuple(observed))
        except _Limited as limited:
            return Scan(revision, cycle.count, hold="rate-limited", retry_at=limited.retry_at)
        except Held as problem:
            return Scan(revision, cycle.count, hold=str(problem))
        except (ValueError, OSError, OverflowError, sqlite3.Error, http.client.HTTPException):
            return Scan(revision, cycle.count, hold="invalid-or-unavailable-evidence")

    @staticmethod
    def _pull(
        cycle: _Cycle, context: Context, refresh: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
        work = context.work
        if work is None:
            return None, None
        number = work.pr
        if number is None:
            mapper = GitHubFacts(context)
            candidates = []
            for row in cycle.pages("pulls", state="all"):
                if _object(row.get("user")).get("id") != context.project.implementer:
                    continue
                body = row.get("body")
                if isinstance(body, str) and mapper.matches_work(body):
                    candidates.append(_id(row.get("number")))
            if len(candidates) > 1:
                raise Held("ambiguous-pull")
            if not candidates:
                return None, None
            number = candidates[0]
        path = f"pulls/{number}"
        pull = cycle.detail(path)
        if _id(pull.get("number")) != number:
            raise Held("wrong-pull-resource")
        refresh[path] = pull
        return pull, cycle.pages(f"{path}/reviews")


class _Cycle:
    """Cycle-local budget and provider pagination state."""

    def __init__(
        self, transport: GetTransport, cache: Cache, now: datetime, budget: int, timeout: float,
    ) -> None:
        self.transport, self.cache, self.now = transport, cache, now
        self.budget, self.timeout, self.count = budget, timeout, 0
        self.repository = transport.scope.repository
        self.root = f"{ORIGIN}/repos/{self.repository}"
        self.repo_id: int | None = None

    def detail(self, path: str, *, fresh: bool = False) -> dict[str, Any]:
        data, _ = self._read(f"{self.root}/{path}", collection=False, fresh=fresh)
        return _object(data)

    def pages(self, path: str, **query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            params = {**query, "per_page": "100", "page": str(page)}
            url = f"{self.root}/{path}?{urlencode(params)}"
            data, link = self._read(url, collection=True)
            rows.extend(_objects(data))
            candidate = self._next(link)
            if candidate is None:
                return _objects(rows)
            page += 1
            self._validate_next(candidate, path, {**params, "page": str(page)})

    @staticmethod
    def _next(link: str | None) -> str | None:
        if link is None:
            return None
        fields = list(re.finditer(r'<([^>]+)>\s*;\s*rel="([a-z]+)"(?:\s*,\s*|\s*$)', link))
        if not fields or "".join(m[0] for m in fields) != link:
            raise Held("invalid-pagination")
        next_urls = [item[1] for item in fields if item[2] == "next"]
        if len(next_urls) > 1:
            raise Held("invalid-pagination")
        return next_urls[0] if next_urls else None

    def _validate_next(self, url: str, path: str, expected: dict[str, str]) -> None:
        try:
            parsed = urlsplit(url)
            supplied = parse_qs(parsed.query, strict_parsing=True, max_num_fields=4)
        except ValueError:
            raise Held("invalid-pagination") from None
        query = {key: [value] for key, value in expected.items()}
        if (not url.startswith(ORIGIN + "/") or parsed.netloc != "api.github.com" or "#" in url
                or any(ord(c) <= 32 for c in url)
                or supplied != query):
            raise Held("invalid-pagination")
        if parsed.path == f"/repos/{self.repository}/{path}":
            return
        match = re.fullmatch(r"/repositories/([1-9][0-9]*)/" + re.escape(path), parsed.path)
        if not match:
            raise Held("invalid-pagination")
        if self.repo_id is None:
            data, _ = self._read(self.root, collection=False, fresh=True)
            repo = _object(data)
            if repo.get("full_name") != self.repository:
                raise Held("repository-alias-unconfirmed")
            self.repo_id = _id(repo.get("id"))
        if str(self.repo_id) != match[1]:
            raise Held("repository-alias-unconfirmed")
        # Subsequent GETs use the equivalent certified canonical named route.

    def _read(self, url: str, *, collection: bool, fresh: bool = False) -> tuple[object, str | None]:
        scope = self.transport.scope
        scope.target(url)
        if self.count >= self.budget:
            raise Held("request-budget")
        saved = self.cache.read(scope, url)
        if saved is not None:
            self._decode(saved, collection)
        validator = saved.etag if saved is not None and not fresh else None
        self.count += 1
        response = self.transport.get(url, etag=validator, timeout=self.timeout)
        headers = {key.lower(): value for key, value in response.headers.items()}
        if self._is_rate_limit(response, headers):
            raise _Limited(self._retry(headers))
        if response.status in (401, 403, 404):
            raise Held("permission-or-resource-unavailable")
        if response.status == 304:
            if saved is None or validator is None or (
                headers.get("etag", validator) != validator
                or headers.get("link", saved.link) != saved.link
            ):
                raise Held("unbound-conditional-response")
            return self._decode(saved, collection), saved.link
        if response.status != 200:
            raise Held("unsuccessful-response")
        page = Page(response.body, headers.get("etag"), headers.get("link"))
        data = self._decode(page, collection)
        self.cache.write(scope, url, page)
        return data, page.link

    @staticmethod
    def _decode(page: Page, collection: bool) -> object:
        if (not page.body or len(page.body) > MAX_BODY
                or (page.etag is not None and not re.fullmatch(r'(?:W/)?"[^"\r\n]+"', page.etag))):
            raise Held("invalid-response")
        decoded = json.loads(page.body)
        return _objects(decoded) if collection else _object(decoded)

    @staticmethod
    def _is_rate_limit(response: Response, headers: dict[str, str]) -> bool:
        return response.status == 429 or (response.status == 403 and (
            headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers
        ))

    def _retry(self, headers: dict[str, str]) -> datetime | None:
        delays = []
        for key in ("retry-after", "x-ratelimit-reset"):
            raw = headers.get(key)
            if raw:
                try:
                    if raw.isascii() and raw.isdecimal():
                        value = int(raw) + (self.now.timestamp() if key == "retry-after" else 0)
                        delays.append(datetime.fromtimestamp(value, self.now.tzinfo))
                    elif key == "retry-after":
                        date = parsedate_to_datetime(raw)
                        if date.utcoffset() is not None:
                            delays.append(date)
                except (ValueError, TypeError, OverflowError, OSError):
                    continue
        return max([self.now, *delays]) if delays else None
