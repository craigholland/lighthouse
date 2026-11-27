"""Exercise the selected concrete bindings with synthetic native and HTTP edges."""

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pytest
from test_coordinator import CYCLE, accept, assemble, with_pull
from test_github import BINDING, HEAD, PRE, PROJECT, REPO
from test_github_collection import Fake
from test_review_http import HTTPS
from test_t07_dispatch import commit_review
from test_t07_stdio import ACK, DONE, ENTER, EXIT, FakeSession

from lighthouse.adapters.codex import windows_session
from lighthouse.adapters.codex.stdio import ReviewRequest
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.coordinator import Bundle, Coordinator
from lighthouse.application.review_dispatch import Stage
from lighthouse.domain.workflow import (
    Candidate,
    Execution,
    Outcome,
    Ready,
    Verification,
    Workflow,
)
from lighthouse.operator_status import render_status
from lighthouse.runtime_bindings import PrivateRuntimeBinding, bind_review


@pytest.mark.parametrize("case", ["success", "workflow-hold", "incomplete-cleanup"])
def test_selected_bindings_run_through_actual_reconciliation_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    workspace, home = tmp_path / "workspace", tmp_path / "review-home"
    workspace.mkdir()
    home.mkdir()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"not an executable: exact fixture hash only")
    git = tmp_path / "git.exe"
    windows = windows_session.PrivateWindowsReview(
        REPO, workspace, executable, sha256(executable.read_bytes()).hexdigest(), git,
        home, (("SystemRoot", str(tmp_path)), ("TEMP", str(tmp_path))),
    )
    ledger = SQLiteLedger.initialize(tmp_path / "ledger")
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    http = HTTPS(monkeypatch)
    git_calls = []

    def fixture_git(args, **kwargs):
        assert args[0] == str(git) and kwargs["cwd"] == workspace and kwargs["timeout"] <= 2
        assert "CODEX_HOME" not in kwargs["env"] and "fixture_only" not in str(kwargs["env"])
        git_calls.append(args)
        if "--show-toplevel" in args:
            result = str(workspace)
        elif "remote.origin.url" in args:
            result = "https://github.com/" + REPO
        elif "HEAD^{commit}" in args:
            result = HEAD
        else:
            assert "--porcelain=v1" in args
            result = ""
        return subprocess.CompletedProcess(args, 0, result.encode(), b"")

    monkeypatch.setattr(windows_session.subprocess, "run", fixture_git)
    wire = FakeSession(
        ReviewRequest(REPO, 4, 8, HEAD, workspace, "fixture-model.1", request.context, request.instructions, "checks"),
        review_frames=(ACK, ENTER) if case == "incomplete-cleanup" else (ENTER, EXIT, DONE, ACK),
    )
    launches = []
    stops = []

    class Child:
        def start(self, path, args, cwd, env, deadline):
            assert path == executable and args == ("app-server", "--listen", "stdio://") and cwd == workspace
            assert set(env) == {"SystemRoot", "TEMP", "CODEX_HOME"} and "fixture_only" not in str(env)
            launches.append(deadline)

        def write(self, data, deadline):
            wire.write(data, 20.0)
            return len(data)

        def read(self, count, deadline):
            value = wire.read(1_048_576, 20.0)
            assert value is None or len(value) <= count
            return value

        def terminate(self):
            stops.append(True)

        def witnesses(self, deadline):
            return True, case != "incomplete-cleanup"

        def close(self, deadline):
            assert stops

    queue = []
    binding = PrivateRuntimeBinding(request.target, windows, "fixture-model.1", "fixture_only")
    service = bind_review(PROJECT, ledger, binding, current_authority=lambda _: True,
                          current_lead=lambda *_: PROJECT.lead, enqueue=queue.append, native_boundary=Child)
    assert not launches and not http.requests and not git_calls
    assert service.start(request).stage is Stage.EXECUTION_UNKNOWN
    assert not launches and not http.requests
    if case == "workflow-hold":
        fake = Fake()
        with_pull(fake)
        cycle = replace(CYCLE, version=3, revision="durable-test-hold", reviewing=Execution.UNKNOWN)
        assert assemble(tmp_path, fake, ledger).reconcile(cycle).phase is Outcome.HOLD
    queue[0]()
    saved = SQLiteLedger(tmp_path / "ledger").review_attempt(REPO, request.target.dispatch)
    assert saved is not None
    visible = json.loads(render_status(tmp_path / "ledger", REPO, request.target.dispatch))
    assert visible["head"] == HEAD and visible["work"] == request.target.order
    if case == "workflow-hold":
        assert saved.stage is Stage.CLAIMED and not launches and not http.requests
        assert visible["phase"] == "hold" and visible["next_actor"] == PROJECT.owner
    elif case == "incomplete-cleanup":
        assert saved.lifecycle.remote.value == "completion-unconfirmed"
        assert saved.lifecycle.cleanup.value == "owned-cleanup-unconfirmed"
        assert visible["causes"] == ["completion-unconfirmed", "owned-cleanup-unconfirmed"]
        assert not http.requests
    else:
        assert saved.stage is Stage.COMMENTED and saved.review_id == 51
        assert len(launches) == len(stops) == len(http.reviews) == 1 and len(git_calls) == 12


def test_installed_readonly_status_and_incompatible_ledger(tmp_path: Path) -> None:
    path = tmp_path / "selected-ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    parent = Path.cwd()

    def inspect(selected: Path, *extra: str):
        return subprocess.run(
            [sys.executable, "-I", "-m", "lighthouse", "status", "--ledger", str(selected),
             "--project", REPO, *extra],
            cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False,
        )

    before = path.read_bytes()
    current = inspect(path)
    assert not current.stderr and current.returncode == 0
    result = json.loads(current.stdout)
    assert (result["phase"], result["issue"], result["pr"], result["head"], result["status"]) == (
        "review", 4, 8, HEAD, "pending",
    )
    assert result["dispatch"] == request.target.dispatch and result["next_actor"] == PROJECT.lead
    known = inspect(path, "--dispatch", request.target.dispatch)
    assert json.loads(known.stdout) == result
    assert path.read_bytes() == before and str(tmp_path) not in known.stdout and str(parent) not in known.stdout
    missing = tmp_path / "missing-ledger"
    assert inspect(missing).returncode == 2 and not missing.exists()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=1")
    bad = inspect(path)
    assert bad.returncode == 2 and not bad.stdout and str(path) not in bad.stderr

def _installed_status(tmp_path: Path, path: Path, dispatch: str | None = None):
    command = [sys.executable, "-I", "-m", "lighthouse", "status", "--ledger", str(path), "--project", REPO]
    if dispatch is not None:
        command += ["--dispatch", dispatch]
    response = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=10, check=True)
    assert not response.stderr and str(path) not in response.stdout
    return json.loads(response.stdout)


def test_installed_status_reports_latest_owner_hold_with_pending_review(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    fake = Fake()
    with_pull(fake)
    cycle = replace(CYCLE, version=3, revision="unknown-after-review", reviewing=Execution.UNKNOWN)
    assert assemble(tmp_path, fake, ledger).reconcile(cycle).phase is Outcome.HOLD
    before = path.read_bytes()
    for dispatch in (None, request.target.dispatch):
        data = _installed_status(tmp_path, path, dispatch)
        assert (data["phase"], data["status"], data["decision_reason"]) == ("hold", "pending", "unknown-acceptance")
        assert data["decision_actor"] == data["next_actor"] == PROJECT.owner
        assert data["issue"] == 4 and data["dispatch"] == request.target.dispatch
    assert path.read_bytes() == before


def test_installed_historical_dispatch_uses_its_originating_issue(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    original = accept(tmp_path, ledger)
    commit_review(tmp_path, ledger)
    fake = Fake()
    with_pull(fake, merged=True, approval="APPROVED")
    check = Verification(8, HEAD, "checks", "fixture-verification", datetime.fromisoformat(PRE))
    done = replace(CYCLE, version=3, revision="first-work-merged", verification=check)
    assert assemble(tmp_path, fake, ledger).reconcile(done).phase is Outcome.COMPLETE

    class Source:
        def observe(self, _state, cycle):
            ready = Ready(PROJECT.lead, "fixture-ready", BINDING, ())
            return Bundle((Candidate(REPO, 5, cycle.now, BINDING, True, False, True, ready=ready),))

    another = replace(CYCLE, version=4, revision="next-work", new_order="order-2")
    current = Coordinator(Workflow(PROJECT), ledger, Source()).reconcile(another)
    assert current.phase is Outcome.IMPLEMENT and current.order == "order-2"
    before = path.read_bytes()
    old = _installed_status(tmp_path, path, original)
    fresh = _installed_status(tmp_path, path)
    assert (old["issue"], old["work"], old["dispatch"]) == (4, "order", original)
    assert (fresh["issue"], fresh["work"]) == (5, "order-2")
    assert old["phase"] == fresh["phase"] == "implement"
    assert old["decision_actor"] == fresh["decision_actor"] == PROJECT.implementer
    assert path.read_bytes() == before

def test_installed_status_retains_original_review_assignee_on_unchanged_and_recovery(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    ledger = SQLiteLedger.initialize(path)
    accept(tmp_path, ledger)
    request = commit_review(tmp_path, ledger)
    original = ledger.intents(REPO)
    for version, execution, expected_actor, decision_actor in (
        (3, Execution.QUIESCENT, PROJECT.lead, None),
        (4, Execution.UNKNOWN, PROJECT.owner, PROJECT.owner),
        (5, Execution.QUIESCENT, PROJECT.lead, None),
    ):
        fake = Fake()
        with_pull(fake)
        cycle = replace(CYCLE, version=version, revision=f"later-observation-{version}", reviewing=execution)
        status = assemble(tmp_path, fake, ledger).reconcile(cycle)
        assert status.phase is (Outcome.HOLD if execution is Execution.UNKNOWN else Outcome.REVIEW)
        before = path.read_bytes()
        for selector in (None, request.target.dispatch):
            view = _installed_status(tmp_path, path, selector)
            assert view["status"] == "pending" and view["dispatch"] == request.target.dispatch
            assert view["issue"] == request.target.issue and view["work"] == request.target.order
            assert view["dispatch_next_actor"] == PROJECT.lead and view["next_actor"] == expected_actor
            assert view["decision_actor"] == decision_actor
            assert view["decision_reason"] == (
                "unknown-acceptance" if execution is Execution.UNKNOWN else "already-recommended"
            )
        assert path.read_bytes() == before
        assert SQLiteLedger(path).intents(REPO) == original
