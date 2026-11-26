"""Fake HTTP at the GET boundary; actual temporary SQLite persistence."""

import json
import sqlite3
import subprocess
import sys
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from test_github import (
    BINDING,
    CONTEXT,
    LABELS,
    PROJECT,
    REPO,
    TIME,
    pull,
    resources,
    review,
)

from lighthouse.adapters.github.cache import Cache
from lighthouse.adapters.github.collection import GitHubCollector
from lighthouse.adapters.github.transport import ORIGIN, Held, HTTPSGet, Response, Scope
from lighthouse.domain.workflow import Work

ROOT = f"{ORIGIN}/repos/{REPO}"
SCOPE = Scope(REPO, PROJECT.lead, LABELS.ready)
READY = "issues?" + urlencode({"state": "open", "labels": LABELS.ready, "per_page": "100", "page": "1"})
EVENTS = "issues/4/events?per_page=100&page=1"
PULLS = "pulls?state=all&per_page=100&page=1"
REVIEWS = "pulls/8/reviews?per_page=100&page=1"


def response(body: object, **headers: str) -> Response:
    return Response(200, {"etag": '"sample"', **headers}, json.dumps(body).encode())


class Fake:
    scope = SCOPE

    def __init__(self) -> None:
        self.routes: dict[str, deque[Response]] = defaultdict(deque)
        self.sent: list[tuple[str, str | None]] = []

    def get(self, url: str, *, etag: str | None, timeout: float) -> Response:
        assert 0 < timeout <= 30 and url.startswith(ROOT)
        path = url.removeprefix(ROOT + "/") if url != ROOT else ""
        self.sent.append((path, etag))
        return self.routes[path].popleft()


def make_scan(path: Path, fake: Fake) -> GitHubCollector:
    return GitHubCollector(fake, Cache(path), PROJECT, LABELS, "checks")


def _page_two(alias: bool = False) -> str:
    origin = ORIGIN + "/repositories/123" if alias else ROOT
    return f'<{origin}/{READY[:-1]}2>; rel="next"'


def script(fake: Fake, *, conditional: bool = False, alias: bool = False) -> None:
    data = resources()
    choices = {
        READY: response([data.issue], link=_page_two(alias)),
        READY[:-1] + "2": response([]),
        "issues/4": response(data.issue),
        EVENTS: response(data.events),
    }
    for path, value in choices.items():
        fake.routes[path].append(Response(304, {}) if conditional else value)
    fake.routes["issues/4"].append(choices["issues/4"])
    if alias:
        fake.routes[""].append(response({"id": 123, "full_name": REPO}))


def test_complete_pages_durable_conditional_reuse_in_fresh_process(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    fake = Fake()
    script(fake)
    initial = make_scan(path, fake).collect({4: CONTEXT}, revision="first", now=TIME)
    assert initial.hold is None and initial.requests == 5
    assert initial.observations[0].candidate is not None
    assert initial.observations[0].candidate.ready is not None
    own = Path(__file__).resolve()
    child = subprocess.run(
        [sys.executable, "-c", """
import runpy, sys
from pathlib import Path
m = runpy.run_path(sys.argv[1])
fake = m["Fake"]()
m["script"](fake, conditional=True)
scan = m["make_scan"](Path(sys.argv[2]), fake).collect({}, revision="reopen", now=m["TIME"])
assert scan.hold is None and scan.requests == 5
assert scan.observations[0].hold == "readiness-unresolved"
assert sum(etag == '"sample"' for _, etag in fake.sent) == 4
assert fake.sent[-1][1] is None
print("reused both pages, refreshed Issue, rechecked authority")
""", str(own), str(path)],
        cwd=own.parent, timeout=8, capture_output=True, text=True,
    )
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "reused both pages, refreshed Issue, rechecked authority"


def test_numeric_repository_alias_requires_same_repository(tmp_path: Path) -> None:
    fake = Fake()
    script(fake, alias=True)
    scan = make_scan(tmp_path / "cache", fake).collect({4: CONTEXT}, revision="alias", now=TIME)
    assert scan.hold is None and scan.requests == 6
    assert all("repositories/" not in path for path, _ in fake.sent)
    fake = Fake()
    script(fake, alias=True)
    fake.routes[""] = deque([response({"id": 124, "full_name": REPO})])
    scan = make_scan(tmp_path / "cache", fake).collect({4: CONTEXT}, revision="wrong", now=TIME)
    assert scan.hold == "repository-alias-unconfirmed" and scan.requests == 2


@pytest.mark.parametrize(("status", "headers", "expected"), [
    (429, {"Retry-After": "10"}, "rate-limited"),
    (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(TIME.timestamp()) + 30)},
     "rate-limited"),
    (403, {}, "permission-or-resource-unavailable"),
    (302, {"location": ORIGIN + "/elsewhere"}, "unsuccessful-response"),
    (500, {}, "unsuccessful-response"),
])
def test_partial_failure_then_restart_not_false_empty(
    tmp_path: Path, status: int, headers: dict[str, str], expected: str,
) -> None:
    path = tmp_path / "cache"
    fake = Fake()
    script(fake)
    fake.routes[READY[:-1] + "2"] = deque([Response(status, headers)])
    result = make_scan(path, fake).collect({4: CONTEXT}, revision="overlap", now=TIME)
    assert result.hold == expected and result.requests == 2 and result.observations == ()
    if expected == "rate-limited":
        assert result.retry_at is not None and result.retry_at > TIME
    other = Fake()
    script(other)
    other.routes[READY] = deque([Response(304, {})])
    complete = make_scan(path, other).collect({4: CONTEXT}, revision="overlap", now=TIME)
    assert complete.hold is None and complete.observations[0].candidate is not None
    assert other.sent[0][1] == '"sample"' and other.sent[1][1] is None


def test_missing_mismatched_and_corrupt_cache_do_not_authorize(tmp_path: Path) -> None:
    path = tmp_path / "cache"
    fake = Fake()
    fake.routes[READY].append(Response(304, {}))
    assert make_scan(path, fake).collect({}, revision="missing", now=TIME).hold == (
        "unbound-conditional-response"
    )
    fake = Fake()
    script(fake)
    assert make_scan(path, fake).collect({}, revision="seed", now=TIME).hold is None
    fake = Fake()
    fake.routes[READY].append(Response(304, {"etag": '"other"'}))
    assert make_scan(path, fake).collect({}, revision="mismatched", now=TIME).hold == (
        "unbound-conditional-response"
    )
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE response SET body=?", (b"[]",))
    fake = Fake()
    assert make_scan(path, fake).collect({}, revision="bad", now=TIME).hold == "cache-invalid"
    assert not fake.sent


@pytest.mark.parametrize("link", [
    '<https://example.invalid/next>; rel="next"',
    f'<{ORIGIN}/repos/other/project/{READY[:-1]}2>; rel="next"',
    f'<{ROOT}/{READY}>; rel="next"',
    f'<{ROOT}/{READY[:-1]}2&other=1>; rel="next"',
])
def test_pagination_rejects_foreign_loop_and_changed_query(tmp_path: Path, link: str) -> None:
    fake = Fake()
    fake.routes[READY].append(response([], link=link))
    scan = make_scan(tmp_path / "cache", fake).collect({}, revision="bad", now=TIME)
    assert scan.hold == "invalid-pagination" and scan.requests == 1
    assert len(fake.sent) == 1


def test_budget_and_read_identity_checked_before_network(tmp_path: Path) -> None:
    fake = Fake()
    script(fake)
    collector = make_scan(tmp_path / "cache", fake)
    scan = collector.collect({}, revision="budget", now=TIME, budget=1)
    assert scan.hold == "request-budget" and scan.requests == 1
    fake.scope = replace(SCOPE, read_identity=PROJECT.implementer)
    assert collector.collect({}, revision="actor", now=TIME).hold == "invalid-cycle"
    assert len(fake.sent) == 1


@pytest.mark.parametrize("variant", ["bound", "discover", "ambiguous", "drift"])
def test_active_work_is_checked_even_when_not_in_ready_list(tmp_path: Path, variant: str) -> None:
    fake = Fake()
    fake.routes[READY].append(response([]))
    issue = resources().issue
    assert isinstance(issue, dict)
    closed = {**issue, "state": "closed"}
    fake.routes["issues/4"].extend((response(closed), response(closed)))
    fake.routes[EVENTS].append(response(resources().events))
    if variant in ("discover", "ambiguous"):
        listing = [pull()]
        if variant == "ambiguous":
            listing.append(pull(id=81, number=9))
        fake.routes[PULLS].append(response(listing))
    actual = pull(merged=True)
    revised = actual if variant != "drift" else {**actual, "head": {"sha": "c" * 40}}
    fake.routes["pulls/8"].extend((response(actual), response(revised)))
    fake.routes[REVIEWS].append(response([review()]))
    bound = None if variant in ("discover", "ambiguous") else 8
    context = replace(CONTEXT, work=Work(4, "order", BINDING, bound))
    scan = make_scan(tmp_path / "cache", fake).collect({4: context}, revision="active", now=TIME)
    if variant in ("bound", "discover"):
        assert scan.hold is None and scan.observations[0].merge is not None
    else:
        expected = "ambiguous-pull" if variant == "ambiguous" else "resource-drift"
        assert scan.hold == expected and scan.observations == ()


def test_dormant_stdlib_transport_sends_only_scoped_get_to_injected_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    class Connection:
        def __init__(self, host: str, *, timeout: float) -> None:
            assert host == "api.github.com" and timeout == 1.0

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            calls.append((method, path, headers))

        def getresponse(self) -> Any:
            class Redirect:
                status = 302

                def getheaders(self) -> list[tuple[str, str]]:
                    return [("Location", "https://example.invalid")]

                def __enter__(self) -> Any:
                    return self

                def __exit__(self, *exc: object) -> None:
                    pass

            return Redirect()

        def close(self) -> None:
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    transport = HTTPSGet(SCOPE, "synthetic-only")
    with pytest.raises(Held):
        transport.get("https://example.invalid/repos/example/project/issues/4", etag=None, timeout=1)
    with pytest.raises(Held):
        transport.get(f"{ROOT}/issues/4?other=yes", etag=None, timeout=1)
    assert calls == []
    assert transport.get(f"{ROOT}/issues/4", etag='"sample"', timeout=1).status == 302
    assert len(calls) == 1 and calls[0][:2] == ("GET", f"/repos/{REPO}/issues/4")
    assert calls[0][2]["X-GitHub-Api-Version"] == "2022-11-28"
