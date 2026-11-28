"""Test the foreground command through SQLite, collector, worker and publisher."""

import json
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from test_coordinator import CYCLE, ready, with_pull
from test_github import CONTEXT, HEAD, PRE, PROJECT, REPO, pull, resources, review
from test_github_collection import Fake
from test_review_http import Response
from test_t07_stdio import ACK, DONE, ENTER, FakeSession, notify

from lighthouse.adapters.codex import windows_session
from lighthouse.adapters.codex.stdio import ReviewRequest
from lighthouse.adapters.github import review_http
from lighthouse.adapters.github.facts import ReadinessBinding
from lighthouse.adapters.github.observation_source import GitHubObservationSource
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.coordinator import Coordinator
from lighthouse.cli import main
from lighthouse.configuration import load_configuration, profile_fingerprint
from lighthouse.domain.workflow import Outcome, Workflow


def test_installed_review_help_and_missing_settings_are_inert(tmp_path: Path) -> None:
    def run(*args: str):
        return subprocess.run(
            [sys.executable, "-I", "-m", "lighthouse", *args],
            cwd=tmp_path, capture_output=True, text=True, timeout=8, check=False,
        )

    assert run("--help").returncode == run("--version").returncode == 0
    help_review = run("review", "--help")
    assert help_review.returncode == 0 and "--dispatch" in help_review.stdout
    for selector in ("invalid", "a" * 64):
        missing = tmp_path / "missing"
        result = run("review", "--settings", str(missing), "--dispatch", selector)
        assert result.returncode == 2 and not result.stdout and str(missing) not in result.stderr
        assert not missing.exists()


@pytest.mark.parametrize(("event", "phase", "drift"), [
    ("COMMENT", "review", ""), ("REQUEST_CHANGES", "revise", ""), ("APPROVE", "hold", ""),
    ("APPROVE", "", "owner"), ("APPROVE", "", "verification"), ("APPROVE", "", "workspace"),
])
def test_explicit_foreground_composition(tmp_path: Path, monkeypatch, capsys, event: str, phase: str, drift: str) -> None:
    ledger_path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(ledger_path)
    workspace, home = tmp_path / "review", tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    (workspace / "AGENTS.md").write_text("Synthetic repository guidance.", encoding="utf-8")
    executable, git = tmp_path / "codex.exe", tmp_path / "git.exe"
    executable.write_bytes(b"synthetic bytes, never executed")
    profile, service, settings = (tmp_path / n for n in ("profile.toml", "service.toml", "settings.toml"))
    service.write_text("version = 1\n", encoding="utf-8")

    def write(path, fields, tables=()):
        def text(rows):
            return "".join(f"{name} = {json.dumps(value)}\n" for name, value in rows.items())
        path.write_text(text(fields) + "".join(f"[{name}]\n{text(rows)}" for name, rows in tables), encoding="utf-8")

    write(profile, dict(version=1, project=PROJECT.profile, repository=REPO, adapter="github",
                        credential_ref="ref:synthetic"), (
        ("actors", dict(owner=PROJECT.owner, lead=PROJECT.lead, implementer=PROJECT.implementer)),
        ("workspaces", dict(implementation=str(tmp_path / "writer"), review=str(workspace))),
        ("verification", dict(directory=".", commands=["python -m pytest"])),
    ))
    configured = load_configuration(service, [profile])
    fingerprint = profile_fingerprint(configured.service, configured.projects[0])
    admitted_project = replace(PROJECT, profile=fingerprint)
    assert CONTEXT.readiness is not None
    admitted_binding = replace(CONTEXT.readiness.binding, profile=fingerprint)
    admitted_context = replace(CONTEXT, project=admitted_project,
                               readiness=ReadinessBinding(4, 100, admitted_binding))
    fake = Fake()


    # Use the configured profile fingerprint at the independent admission boundary.
    from lighthouse.adapters.github.cache import Cache
    from lighthouse.adapters.github.collection import GitHubCollector

    collector = GitHubCollector(fake, Cache(tmp_path / "profile-cache"), admitted_project, CONTEXT.labels, "checks")
    coordinator = Coordinator(Workflow(admitted_project), ledger, GitHubObservationSource(
        collector, lambda state: {4: replace(admitted_context, work=state.work)},
    ))
    ready(fake)
    assert coordinator.reconcile(CYCLE).phase is Outcome.IMPLEMENT
    with_pull(fake, discover=True)
    selected = coordinator.reconcile(replace(CYCLE, revision="captured-review", version=2))
    assert selected.phase is Outcome.REVIEW
    req, = [i for i in selected.intents if i.operation == "review"]
    origin = f"https://api.github.com/repos/{REPO}"
    pr = pull(url=f"{origin}/pulls/8")
    available = resources()
    issue = available.issue
    assert isinstance(issue, dict)
    evidence = json.dumps({"issue": issue["body"], "title": issue["title"], "pull": pr["body"]},
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    write(settings, dict(version=1, service=str(service), profile=str(profile), profile_id=PROJECT.profile,
                         ledger=str(ledger_path), cache=str(tmp_path / "run-cache"), repository=REPO,
                         order=req.order, issue=4, pr=req.pr, head=req.head, readiness_event=100,
                         verification="checks", runtime=str(executable),
                         runtime_sha256=sha256(executable.read_bytes()).hexdigest(), git=str(git),
                         codex_home=str(home), model="fixture-model.1", intake_ref="FIXTURE_READ", expected_event=event,
                         publisher_ref="FIXTURE_PUBLISH", dependencies=[],
                         evidence_sha256=sha256(evidence.encode()).hexdigest()),
          (("environment", dict(SystemRoot=str(tmp_path), TEMP=str(tmp_path))),))
    if drift:
        content = profile.read_text(encoding="utf-8")
        changes = {
            "owner": (f"owner = {PROJECT.owner}", "owner = 99"),
            "verification": ('commands = ["python -m pytest"]', 'commands = ["python -m unittest"]'),
            "workspace": (json.dumps(str(workspace)), json.dumps(str(tmp_path / "other-review"))),
        }
        old, new = changes[drift]
        assert old in content
        profile.write_text(content.replace(old, new), encoding="utf-8")

        def forbidden(*_args, **_kwargs):
            pytest.fail("profile drift reached credentials, Git, HTTP or child work")

        monkeypatch.setattr(windows_session.subprocess, "run", forbidden)
        monkeypatch.setattr(review_http.http.client, "HTTPSConnection", forbidden)
        monkeypatch.setattr(windows_session.WindowsReviewOwner, "__init__", forbidden)
        # Resolve would raise KeyError unless the exact input gate worked first.
        from lighthouse.review_runner import run_review

        before = ledger_path.read_bytes()
        with pytest.raises(ValueError, match="selection is not a committed review"):
            run_review(settings, req.dispatch_id, resolve=forbidden)
        with pytest.raises(SystemExit) as held:
            main(["review", "--settings", str(settings), "--dispatch", req.dispatch_id])
        assert held.value.code == 2
        assert ledger_path.read_bytes() == before and not (tmp_path / "run-cache").exists()
        return
    monkeypatch.setenv("FIXTURE_READ", "synthetic-read")
    monkeypatch.setenv("FIXTURE_PUBLISH", "synthetic-write")

    def git_boundary(args, **kwargs):
        assert args[0] == str(git) and kwargs["cwd"] == workspace
        found = next((value for key, value in {
            "--show-toplevel": str(workspace), "remote.origin.url": f"https://github.com/{REPO}",
            "HEAD^{commit}": HEAD, "--porcelain=v1": "",
        }.items() if key in args), None)
        assert found is not None
        return subprocess.CompletedProcess(args, 0, found.encode(), b"")

    monkeypatch.setattr(windows_session.subprocess, "run", git_boundary)
    frames = (
        ENTER, notify("item/completed", {"item": {"type": "exitedReviewMode",
                                               "review": json.dumps({"event": event, "body": "Synthetic review."})}}),
        DONE, ACK,
    )
    wire = FakeSession(ReviewRequest(REPO, 4, 8, HEAD, workspace, "fixture-model.1", "ctx", "rules", "checks"),
                       review_frames=frames)
    launched, posts = [], []

    class Child:
        def start(self, path, args, cwd, env, deadline):
            assert path == executable and cwd == workspace and "synthetic-write" not in str(env)
            launched.append(True)

        def write(self, data, deadline):
            wire.write(data, 20.0)
            return len(data)

        def read(self, count, deadline):
            return wire.read(1_048_576, 20.0)

        def terminate(self):
            pass

        def witnesses(self, deadline):
            return True, True

        def close(self, deadline):
            pass

    original = windows_session.WindowsReviewOwner.__init__

    def owned(self, selected, **_kwargs):
        original(self, selected, child=Child)

    monkeypatch.setattr(windows_session.WindowsReviewOwner, "__init__", owned)

    class FakeResponse(Response):
        def getheaders(self):
            return []

        def read(self, size):
            return self.read1(size)

    class Link:
        def __init__(self, host, *, timeout):
            assert host == "api.github.com" and timeout > 0
            self.headers = {}

        def request(self, method, route, *, headers):
            self.method, self.route, self.headers = method, route, headers

        def connect(self):
            self.sock = self

        def putrequest(self, method, route):
            self.method, self.route = method, route

        def putheader(self, name, value):
            self.headers[name] = value

        def endheaders(self):
            pass

        def settimeout(self, timeout):
            assert timeout > 0

        def send(self, data):
            self.payload = json.loads(data)

        def close(self):
            pass

        def getresponse(self):
            route = self.route.split("?", 1)[0]
            prefix = f"/repos/{REPO}"
            if self.method == "POST":
                assert self.headers["Authorization"] == "Bearer synthetic-write"
                assert route == prefix + "/pulls/8/reviews" and self.payload["event"] == event
                assert self.payload["commit_id"] == HEAD
                state = {"APPROVE": "APPROVED", "COMMENT": "COMMENTED", "REQUEST_CHANGES": "CHANGES_REQUESTED"}[event]
                posts.append(review(state=state, body=self.payload["body"], submitted_at=PRE))
                return FakeResponse(201, posts[0])
            choices = {"/issues/4": issue, "/issues/4/events": available.events,
                       "/pulls/8": pr, "/pulls/8/reviews": posts}
            assert self.method == "GET" and route.startswith(prefix)
            return FakeResponse(200, choices[route.removeprefix(prefix)])

    monkeypatch.setattr(review_http.http.client, "HTTPSConnection", Link)
    assert main(["review", "--settings", str(settings), "--dispatch", req.dispatch_id]) == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["review_event"] == event and reported["phase"] == phase, (reported, launched, len(posts), wire.sent)
    assert reported["review"] == 90 and len(launched) == len(posts) == 1
    assert main(["review", "--settings", str(settings), "--dispatch", req.dispatch_id]) == 0
    assert len(launched) == len(posts) == 1
