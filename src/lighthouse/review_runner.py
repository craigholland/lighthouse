"""Foreground selection of one previously committed exact-head review intent."""

import json
import os
import re
import tomllib
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

from lighthouse.adapters.codex.stdio import ReviewRequest
from lighthouse.adapters.codex.windows_session import (
    MAX_RUNTIME_ARTIFACT_BYTES,
    PrivateWindowsReview,
    WindowsReviewOwner,
)
from lighthouse.adapters.github.cache import Cache
from lighthouse.adapters.github.collection import GitHubCollector
from lighthouse.adapters.github.dependency_evidence import Resolution
from lighthouse.adapters.github.facts import Context, Observation, ReadinessBinding
from lighthouse.adapters.github.transport import HTTPSGet, Scope
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.coordinator import Bundle, Coordinator, Cycle
from lighthouse.application.ledger import Intent
from lighthouse.application.review_dispatch import ReviewInput, Stage, Target
from lighthouse.configuration import load_configuration, profile_fingerprint
from lighthouse.domain.workflow import Execution, Outcome, Project, State, Workflow
from lighthouse.operator_status import render_status
from lighthouse.runtime_bindings import PrivateRuntimeBinding, bind_review

_ID = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_INSTRUCTIONS = "Perform ordinary, read-only application code review for the exact authorized change."


def _read(path: Path, maximum: int) -> str:
    if not path.is_absolute() or not path.is_file():
        raise ValueError("missing private input")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("input limit")
    return raw.decode("utf-8")


def _number(value: object) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("invalid number")
    return value


def _path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("private path required")
    return path


def _credential(name: str) -> str:
    return os.environ[name]


def run_review(settings: Path, dispatch: str, *, resolve: Callable[[str], str] = _credential) -> str:
    """Validate selected files and ledger before touching external boundaries."""
    if not _ID.fullmatch(dispatch):
        raise ValueError("invalid dispatch")
    raw = tomllib.loads(_read(settings, 32768))
    if raw.keys() != {
        "version", "service", "profile", "profile_id", "ledger", "cache", "repository",
        "order", "issue", "pr", "head", "readiness_event", "verification",
        "runtime", "runtime_sha256", "git", "codex_home", "model",
        "environment", "intake_ref", "publisher_ref", "dependencies", "evidence_sha256", "expected_event",
    } or type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("invalid settings")
    issue, pr, ready_id = (_number(raw[k]) for k in ("issue", "pr", "readiness_event"))
    configuration = load_configuration(_path(raw["service"]), [_path(raw["profile"])])
    profile, = configuration.projects
    if profile.repository != raw["repository"] or profile.project != raw["profile_id"]:
        raise ValueError("profile mismatch")
    project = Project(profile.repository, profile.integration, profile_fingerprint(configuration.service, profile),
                      profile.actors.owner,
                      profile.actors.lead, profile.actors.implementer)
    ledger_path, cache_path = _path(raw["ledger"]), _path(raw["cache"])
    if ledger_path.resolve() in {cache_path.resolve(), settings.resolve()}:
        raise ValueError("storage overlap")
    ledger = SQLiteLedger(ledger_path)
    view = ledger.operator_snapshot(project.repository, dispatch)
    work = view.state.work
    if (work is None or view.issue != issue or view.assignee != project.lead
            or (work.issue, work.pr, work.order, work.binding.profile, work.binding.verification)
            != (issue, pr, raw["order"], project.profile, raw["verification"])
            or view.intent != Intent(dispatch, work.order, Outcome.REVIEW.value, pr, raw["head"])):
        raise ValueError("selection is not a committed review")
    admissions = [change for change in ledger.audit(project.repository)
                  if change.decision.outcome is Outcome.IMPLEMENT
                  and (admitted := change.decision.state.work) is not None
                  and (admitted.order, admitted.binding, admitted.issue) == (work.order, work.binding, issue)]
    if (len(admissions) != 1 or admissions[0].decision.evidence[:1] != (f"github:issue-event:{ready_id}",)):
        raise ValueError("readiness attribution unavailable")
    target = Target(project.repository, work.order, dispatch, issue, pr, raw["head"], work.binding)
    ref1, ref2 = raw["intake_ref"], raw["publisher_ref"]
    model, event = raw["model"], raw["expected_event"]
    if (event not in ("COMMENT", "APPROVE", "REQUEST_CHANGES") or not isinstance(raw["evidence_sha256"], str) or not _ID.fullmatch(raw["evidence_sha256"]) or not target.valid() or not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", model)
            or not isinstance(ref1, str) or not isinstance(ref2, str)
            or not _REF.fullmatch(ref1) or not _REF.fullmatch(ref2) or ref1 == ref2
            or not isinstance(raw["environment"], dict) or not isinstance(raw["dependencies"], list)):
        raise ValueError("invalid settings")
    dependencies = tuple(Resolution(**entry) for entry in raw["dependencies"])
    if len(dependencies) > 10 or any(
        entry.provenance != "unmanaged" or not _number(entry.comment) or not _number(entry.actor)
        or entry.actor not in {project.owner, project.lead}
        or not isinstance(entry.dependency, str)
        or not isinstance(entry.revision, str) or not isinstance(entry.body_sha256, str)
        for entry in dependencies
    ):
        raise ValueError("dependency evidence unavailable")
    windows = PrivateWindowsReview(
        project.repository, _path(str(profile.review_workspace)), _path(raw["runtime"]),
        raw["runtime_sha256"], _path(raw["git"]), _path(raw["codex_home"]), tuple(raw["environment"].items()),
    )
    windows.inputs()
    digest = sha256()
    maximum = MAX_RUNTIME_ARTIFACT_BYTES
    if windows.executable.resolve(strict=True) != windows.executable or not windows.codex_home.is_dir():
        raise ValueError("runtime binding unavailable")
    with windows.executable.open("rb") as image:
        while block := image.read(1024 * 1024):
            maximum -= len(block)
            if maximum < 0:
                raise ValueError("runtime binding limit")
            digest.update(block)
    if digest.hexdigest() != windows.executable_sha256:
        raise ValueError("runtime binding changed")
    if windows.codex_home.resolve(strict=True).is_relative_to(Path(str(profile.implementation_workspace)).resolve()):
        raise ValueError("managed home overlaps writer")
    if view.attempt is not None and view.attempt.stage not in {Stage.PUBLISHING, Stage.COMMENTED}:
        return render_status(ledger_path, project.repository, dispatch)
    if view.attempt is None and (
        view.state.outcome is not Outcome.REVIEW or view.decision is None
        or view.decision.outcome not in {Outcome.REVIEW, Outcome.UNCHANGED}
        or view.decision.evidence[:1] != (target.head,)
    ):
        return render_status(ledger_path, project.repository, dispatch)
    owner = WindowsReviewOwner(windows)
    instructions = windows.workspace / "AGENTS.md"
    if not instructions.resolve(strict=True).is_relative_to(windows.workspace.resolve(strict=True)):
        raise ValueError("wrong instruction location")
    context = _read(instructions, 65536)
    # Content, runtime, model and independently captured evidence bind the attempt.
    # Exact raw review evidence is supplied below for a new dispatch only.
    proof = raw["evidence_sha256"]
    context_identity = json.dumps(
                {"runtime": windows.executable_sha256, "model": model, "evidence": proof, "instructions": context,
         "event": event, "dependencies": [asdict(item) for item in dependencies], "profile": asdict(project)},
        ensure_ascii=False, sort_keys=True,
    )

    if not owner.checkout_matches(
        ReviewRequest(project.repository, issue, pr, target.head, windows.workspace, model,
                      context, _INSTRUCTIONS, work.binding.verification, True), monotonic() + 8,
    ):
        raise ValueError("checkout unavailable")
    if view.attempt is not None and view.attempt.fingerprint != ReviewInput(
        target, _INSTRUCTIONS, context_identity,
    ).fingerprint():
        raise ValueError("captured input changed")
    if view.attempt is not None and view.attempt.stage is Stage.COMMENTED and (
        view.state.outcome is not Outcome.REVIEW or view.attempt.event == "COMMENT"
    ):
        return render_status(ledger_path, project.repository, dispatch)
    intake, publisher = resolve(ref1), resolve(ref2)
    if (intake == publisher or not intake or not publisher
            or any(not re.fullmatch(r"[!-~]{1,512}", value) for value in (intake, publisher))):
        raise ValueError("capabilities unavailable")
    scope = Scope(project.repository, project.lead, profile.labels.ready, frozenset(e.comment for e in dependencies))
    collector = GitHubCollector(HTTPSGet(scope, intake), Cache(cache_path), project, profile.labels, raw["verification"])
    ready = ReadinessBinding(issue, ready_id, work.binding)
    selected = Context(project, profile.labels, work.binding.verification, False, work, ready)

    def observe() -> tuple[Observation, str]:
        return collector.selected_review(selected, now=datetime.now(UTC), revision=uuid4().hex,
                                         dependencies=dependencies)

    def current(exact: Target) -> bool:
        snapshot = ledger.operator_snapshot(project.repository, dispatch)
        if (exact != target or snapshot.state.outcome is not Outcome.REVIEW
                or snapshot.state.work != work or snapshot.intent != view.intent
                or snapshot.decision is None or snapshot.decision.outcome not in {Outcome.REVIEW, Outcome.UNCHANGED}
                or snapshot.decision.evidence[:1] != (target.head,)):
            return False
        facts, evidence = observe()
        candidate, pull = facts.candidate, facts.pull
        return (
            sha256(evidence.encode()).hexdigest() == proof and facts.hold is None
            and candidate is not None and candidate.is_open and not candidate.blocked
            and candidate.dependencies_complete and candidate.ready is not None
            and candidate.binding == target.binding and pull is not None and pull.is_open and not pull.draft
            and (pull.repository, pull.issue, pull.order, pull.number, pull.head, pull.author, pull.base)
            == (project.repository, issue, work.order, pr, target.head, project.implementer, project.base)
            and facts.review is None and facts.merge is None
        )

    def lead(repository: str, number: int, head: str) -> int | None:
        return project.lead if (repository, number, head) == (target.repository, pr, target.head) and current(target) else None

    execution_input = ""
    if view.attempt is None:
        if not current(target):
            raise ValueError("current authority unavailable")
        _, execution_input = observe()
        if sha256(execution_input.encode()).hexdigest() != proof:
            raise ValueError("review evidence changed")

    dispatch_service = bind_review(
        project, ledger, PrivateRuntimeBinding(target, windows, model, publisher),
        current_authority=current, current_lead=lead, enqueue=lambda action: action(), structured=True,
        worker_context=(_INSTRUCTIONS, json.dumps({"checkout_guidance": context, "review": execution_input})), expected_event=event,
    )
    if view.attempt is not None and view.attempt.stage is Stage.PUBLISHING:
        dispatch_service.publish(dispatch)  # Lookup only for the original PUBLISHING record.
    elif view.attempt is None:
        dispatch_service.start(ReviewInput(target, _INSTRUCTIONS, context_identity))
    reconciliation_held = False
    result = dispatch_service.status(dispatch).attempt
    if result is not None and result.stage is Stage.COMMENTED:
        receipt_event, receipt_id = result.event, result.review_id
        # The existing paired lifecycle witnesses and prior REVIEW selection
        # delimit observation. Reconcile only the matched real receipt.
        class ReceiptObservation:
            def observe(self, accepted: State, cycle: Cycle) -> Bundle:
                try:
                    facts, refreshed = observe()
                except (OSError, RuntimeError, ValueError):
                    return Bundle(held=True)
                review = facts.review
                matches = ((review is None and receipt_event == "COMMENT") or (
                    review is not None and review.evidence == f"github:review:{receipt_id}"
                    and review.verdict.value == {"APPROVE": "approved", "REQUEST_CHANGES": "changes-requested"}
                    .get(receipt_event)
                ))
                return Bundle(
                    (facts.candidate,) if facts.candidate is not None else (),
                    facts.pull, review, facts.merge, accepted.work != work or
                    facts.hold is not None or sha256(refreshed.encode()).hexdigest() != proof or not matches,
                )
        latest = ledger.operator_snapshot(project.repository, dispatch)
        if (latest.state.work == work and latest.state.outcome is Outcome.REVIEW
                and latest.decision is not None and latest.decision.evidence[:1] == (target.head,)):
            reconciled = Coordinator(Workflow(project), ledger, ReceiptObservation()).reconcile(Cycle(
                f"review-receipt:{dispatch}:{receipt_id}", latest.state.version + 1, datetime.now(UTC),
                implementation=Execution.QUIESCENT, reviewing=Execution.QUIESCENT,
            ))
            reconciliation_held = reconciled.reason == "observation-held"
    status = render_status(ledger_path, project.repository, dispatch)
    if reconciliation_held:
        data = json.loads(status)
        data.update(reconciliation="observation-held", next_actor=project.owner)
        return json.dumps(data, sort_keys=True)
    return status
