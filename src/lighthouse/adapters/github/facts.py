"""Normalize supplied GitHub REST resources. No transport or effects."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from lighthouse.configuration import Labels
from lighthouse.domain.workflow import (
    Binding,
    Candidate,
    Merge,
    Priority,
    Project,
    Pull,
    Ready,
    Review,
    Verdict,
    Work,
)

API_VERSION = "2022-11-28"
_HEADINGS = (
    "Objective", "Sources", "In scope", "Out of scope", "Expected surfaces",
    "Acceptance criteria", "Dependencies", "Verification", "Stop conditions", "Handoff",
)


@dataclass(frozen=True)
class ReadinessBinding:
    """Independently captured current content bound to the exact readiness event."""

    issue: int
    event: int
    binding: Binding


@dataclass(frozen=True)
class Context:
    """Validated project context; dependency resolution is supplied separately."""

    project: Project
    labels: Labels
    verification: str
    dependencies_complete: bool
    work: Work | None = None
    readiness: ReadinessBinding | None = None


@dataclass(frozen=True)
class Resources:
    """One explicitly scoped group of complete supplied REST responses."""

    repository: str
    issue_number: int
    revision: str
    version: str
    complete: bool
    issue: object
    events: object
    pull: object = None
    reviews: object = None
    failed: bool = False


@dataclass(frozen=True)
class Observation:
    """Source revision, normalized facts and explicit unresolved evidence."""

    revision: str
    hold: str | None = None
    candidate: Candidate | None = None
    pull: Pull | None = None
    review: Review | None = None
    merge: Merge | None = None
    issue_id: int | None = None
    pull_id: int | None = None


class _Invalid(ValueError):
    """A fixed reason for evidence that cannot be normalized."""


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _Invalid("invalid-resource")
    return value


def _objects(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _Invalid("invalid-collection")
    items = [_object(item) for item in value]
    ids = [_id(item.get("id")) for item in items]
    if len(ids) != len(set(ids)):
        raise _Invalid("duplicate-resource")
    return items


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Invalid("invalid-text")
    return value


def _id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise _Invalid("invalid-id")
    return value


def _flag(value: object) -> bool:
    if type(value) is not bool:
        raise _Invalid("invalid-flag")
    return value


def _time(value: object) -> datetime:
    raw = _text(value)
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", raw):
        raise _Invalid("invalid-time")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise _Invalid("invalid-time") from None


def _sha(value: object) -> str:
    sha = _text(value)
    if not re.fullmatch("[0-9a-f]{40}", sha) or sha == "0" * 40:
        raise _Invalid("invalid-sha")
    return sha


def _actor(resource: dict[str, Any], field: str) -> int:
    return _id(_object(resource.get(field)).get("id"))


def _open(resource: dict[str, Any]) -> bool:
    state: object = resource.get("state")
    if state not in ("open", "closed"):
        raise _Invalid("invalid-state")
    return state == "open"


def _fields(body: str) -> None:
    headings = tuple(re.finditer(r"^##\s+([^\n\r]+)$", body, re.MULTILINE))
    for required in _HEADINGS:
        matches = [i for i, h in enumerate(headings) if h[1].strip() == required]
        if len(matches) != 1:
            raise _Invalid("invalid-task-fields")
        i = matches[0]
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        if not body[headings[i].end():end].strip():
            raise _Invalid("invalid-task-fields")


def scope_fingerprint(title: str, body: str, priority_labels: tuple[str, ...]) -> str:
    """Conservatively fingerprint the full intake text and sorted mapped priority labels."""
    return sha256(json.dumps((title, body.replace("\r\n", "\n"), sorted(priority_labels)),
                             separators=(",", ":")).encode()).hexdigest()


class GitHubFacts:
    """Map exact repository evidence; neither infer authority nor call GitHub."""

    def __init__(self, context: Context) -> None:
        self.context = context

    def normalize(self, source: Resources) -> Observation:
        """Return typed facts or a fixed evidence hold, never an empty success."""
        try:
            if not _flag(source.complete) or _flag(source.failed):
                raise _Invalid("incomplete-collection")
            if source.version != API_VERSION or source.repository != self.context.project.repository:
                raise _Invalid("wrong-source")
            _text(source.revision)
            candidate, unresolved = self._candidate(source)
            pull, review, merge = self._pull(source, candidate)
            issue_id = _id(_object(source.issue).get("id"))
            pull_id = _id(_object(source.pull).get("id")) if pull else None
            return Observation(source.revision, unresolved, candidate, pull, review, merge,
                               issue_id, pull_id)
        except _Invalid as failure:
            return Observation(source.revision, str(failure))

    def _candidate(self, source: Resources) -> tuple[Candidate, str | None]:
        ctx = self.context
        issue = _object(source.issue)
        if (issue.get("repository_url") != "https://api.github.com/repos/" + ctx.project.repository
                or _id(issue.get("number")) != _id(source.issue_number) or "pull_request" in issue):
            raise _Invalid("wrong-issue")
        names = [_text(item.get("name")) for item in _objects(issue.get("labels"))]
        if len(names) != len(set(names)):
            raise _Invalid("ambiguous-labels")
        label = ctx.labels
        mapping = {label.high: Priority.HIGH, label.normal: Priority.NORMAL, label.low: Priority.LOW}
        matched = tuple(sorted(set(names) & mapping.keys()))
        if len(matched) > 1:
            raise _Invalid("conflicting-priority")
        priorities = tuple(mapping[name] for name in matched)
        body = _text(issue.get("body")).replace("\r\n", "\n")
        _fields(body)
        binding = Binding(scope_fingerprint(_text(issue.get("title")), body, matched),
                          _text(ctx.project.profile), _text(ctx.verification))
        created = _time(issue.get("created_at"))
        updated = _time(issue.get("updated_at"))
        if updated < created:
            raise _Invalid("invalid-issue-revision")
        ready, unresolved = self._ready(
            source, label.ready in names, priorities, binding, created, updated,
        )
        return Candidate(source.repository, source.issue_number, created, binding, _open(issue),
                         label.blocked in names, _flag(ctx.dependencies_complete), priorities,
                         ready), unresolved

    def _ready(
        self, source: Resources, present: bool, priorities: tuple[Priority, ...],
        binding: Binding, created: datetime, updated: datetime,
    ) -> tuple[Ready | None, str | None]:
        events = _objects(source.events)
        if not present:
            return None, None
        ctx = self.context
        matches = []
        for item in events:
            if item.get("event") in ("labeled", "unlabeled") and (
                _object(item.get("label")).get("name") == ctx.labels.ready
            ):
                time = _time(item.get("created_at"))
                if not created <= time <= updated:
                    raise _Invalid("invalid-event-revision")
                matches.append((time, _id(item.get("id")), item))
        if not matches:
            return None, "readiness-unresolved"
        latest = max(matches, key=lambda event: event[:2])
        current = latest[2]
        actor = _actor(current, "actor")
        if (current["event"] != "labeled" or actor not in (ctx.project.owner, ctx.project.lead)
                or ctx.readiness != ReadinessBinding(source.issue_number, latest[1], binding)):
            return None, "readiness-unresolved"
        return Ready(actor, f"github:issue-event:{latest[1]}", binding, priorities), None

    def _pull(
        self, source: Resources, issue: Candidate,
    ) -> tuple[Pull | None, Review | None, Merge | None]:
        ctx = self.context
        work = ctx.work
        if work is not None and (work.issue != issue.number or work.binding != issue.binding):
            raise _Invalid("accepted-binding-changed")
        if source.pull is None:
            if source.reviews is not None or (work and work.pr is not None):
                raise _Invalid("missing-pull")
            return None, None, None
        obj = _object(source.pull)
        base = _object(obj.get("base"))
        author = _actor(obj, "user")
        number = _id(obj.get("number"))
        if (
            work is None or author != ctx.project.implementer
            or _object(base.get("repo")).get("full_name") != ctx.project.repository
            or base.get("ref") != ctx.project.base or (work.pr is not None and work.pr != number)
        ):
            raise _Invalid("unbound-pull")
        text = _text(obj.get("body")).replace("\r\n", "\n")
        self._link(text, "Lighthouse-Issue", f"{ctx.project.repository}#{issue.number}")
        self._link(text, "Lighthouse-Work-Order", work.order)
        pull = Pull(ctx.project.repository, ctx.project.base, author, issue.number, work.order,
                    number, _sha(_object(obj.get("head")).get("sha")), _open(obj),
                    _flag(obj.get("draft")))
        review = self._review(source.reviews, pull)
        merge = self._merge(obj, pull)
        if merge is not None and (review is None or review.verdict is not Verdict.APPROVED
                                  or review.submitted >= merge.occurred):
            raise _Invalid("no-pre-merge-approval")
        return pull, review, merge

    @staticmethod
    def _link(body: str, label: str, expected: str) -> None:
        # Work markers inside code fences do not bind a PR.
        visible = re.sub(r"(?ms)^\s{0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^\s{0,3}\1 *$|\Z)", "", body)
        values = re.findall(rf"^{label}:[ \t]*(.*?)\s*$", visible, re.MULTILINE)
        if values != [expected]:
            raise _Invalid("unbound-pull")

    def _review(self, data: object, pull: Pull) -> Review | None:
        effective = []
        for obj in _objects(data):
            if _actor(obj, "user") != self.context.project.lead:
                continue
            state = obj.get("state")
            if state in ("COMMENTED", "PENDING"):
                continue
            if state not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                raise _Invalid("invalid-review-state")
            if _sha(obj.get("commit_id")) == pull.head:
                effective.append((_time(obj.get("submitted_at")), _id(obj.get("id")), state))
        if not effective:
            return None
        timestamp, key, state = max(effective)
        if any(at == timestamp and value != state for at, _, value in effective):
            raise _Invalid("ambiguous-review")
        if state == "DISMISSED":
            return None
        verdict = Verdict.APPROVED if state == "APPROVED" else Verdict.CHANGES
        return Review(self.context.project.lead, pull.number, pull.head, f"github:review:{key}",
                      verdict, timestamp)

    def _merge(self, obj: dict[str, Any], pull: Pull) -> Merge | None:
        if not _flag(obj.get("merged")):
            if obj.get("merged_at") is not None:
                raise _Invalid("contradictory-merge")
            return None
        actor = _actor(obj, "merged_by")
        if pull.is_open or pull.draft or actor != self.context.project.owner:
            raise _Invalid("unconfirmed-owner-merge")
        return Merge(actor, pull.number, pull.head, _sha(obj.get("merge_commit_sha")),
                     _time(obj.get("merged_at")), f"github:pull:{_id(obj.get('id'))}:merge")
