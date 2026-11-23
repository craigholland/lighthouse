"""Single-writer, fake-only recovery experiment; never a production dispatcher."""

import hashlib
import os
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.dataclasses import dataclass

_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


@dataclass(config=_CONFIG)
class Target:
    """Synthetic repository binding and exact PR revision."""

    repository: Literal["example/lighthouse"]
    base: Literal["development"]
    pr: Literal[1]
    author: Literal[101]
    reviewer: Literal[202]
    head: Literal["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]
    context: Literal["approved-fixture-a", "approved-fixture-b"]

    @property
    def fingerprint(self) -> str:
        """Hash only approved synthetic fields, never free-form Issue content."""
        fields = (self.repository, self.base, self.pr, self.author, self.reviewer,
                  self.head, self.context)
        return hashlib.sha256("|".join(map(str, fields)).encode()).hexdigest()


def target_a() -> Target:
    """Return the fixed dry-run target."""
    return Target("example/lighthouse", "development", 1, 101, 202, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "approved-fixture-a")


class Run(BaseModel):
    """Synthetic provider acceptance handle, distinct from a receiver acknowledgement."""

    model_config = _CONFIG
    thread: Literal["fake-thread"]
    turn: Literal["fake-turn"]


class Receipt(BaseModel):
    """Validated, attributed fake COMMENT receipt."""

    model_config = _CONFIG
    id: Literal[1]
    repository: Literal["example/lighthouse"]
    base: Literal["development"]
    pr: Literal[1]
    author: Literal[101]
    reviewer: Literal[202]
    head: Literal["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]
    marker: Literal["lighthouse:fake-dispatch-1"]
    kind: Literal["COMMENT"]


class Record(BaseModel):
    """Minimal private proof state with one permanent dispatch identity."""

    model_config = _CONFIG
    dispatch: Literal["fake-dispatch-1"] = "fake-dispatch-1"
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal["none", "accepted", "complete", "reviewed"] = "none"
    phase: Literal["launch-intent", "accepted", "complete", "review-intent", "reviewed", "hold"]
    run: Run | None = None
    receipt: Receipt | None = None
    reason: Literal["launch-unknown", "permission", "unavailable", "rejected", "interrupted",
                    "cancel-unknown", "stale-target", "review-unknown"] | None = None
    next_actor: Literal["lead", "owner", "none"] = "lead"


class Journal:
    """Load and atomically replace a single scratch receipt; not multi-process safe."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Record | None:
        """Read a receipt without rendering sensitive parser details on failure."""
        try:
            return Record.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError):
            raise RuntimeError("Cannot read proof journal; stop for Lead.") from None

    def save(self, record: Record) -> Record:
        """Flush and atomically replace the record before returning."""
        pending = self._path.with_suffix(".pending")
        try:
            with pending.open("w", encoding="utf-8") as stream:
                stream.write(record.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            pending.replace(self._path)
        except OSError:
            raise RuntimeError("Cannot persist proof journal; stop for Lead.") from None
        return record


Outcome = Literal["running", "complete", "interrupted", "cancel-unknown",
                  "permission", "unavailable", "rejected", "unknown"]


class Worker(Protocol):
    """The experiment's injected, exclusively synthetic worker boundary."""

    def start(self, target: Target) -> Run: ...
    def observe(self, run: Run) -> Outcome: ...
    def cancel(self, run: Run) -> Outcome: ...


class Reviews(Protocol):
    """The experiment's injected, exclusively synthetic review boundary."""

    def target_matches(self, target: Target) -> bool: ...
    def comment(self, target: Target, marker: Literal["lighthouse:fake-dispatch-1"]) -> Receipt: ...
    def find(self, target: Target, marker: Literal["lighthouse:fake-dispatch-1"]) -> Receipt | None: ...


class Proof:
    """Bind one synthetic dispatch to a revision and never replay uncertain calls."""

    _marker: Literal["lighthouse:fake-dispatch-1"] = "lighthouse:fake-dispatch-1"

    def __init__(self, journal: Journal, worker: Worker, reviews: Reviews) -> None:
        self.journal = journal
        self.worker = worker
        self.reviews = reviews

    def dispatch(self, target: Target) -> Record:
        """Persist intent first; identical replay reads state and never launches again."""
        record = self._bound(target)
        if record is not None:
            if record.phase == "launch-intent":
                return self._hold(record, "launch-unknown")
            return record
        record = self.journal.save(Record(fingerprint=target.fingerprint, phase="launch-intent"))
        try:
            run = self.worker.start(target)
        except (TimeoutError, ConnectionError):
            return self._hold(record, "launch-unknown")
        return self._confirm(record, phase="accepted", run=run)

    def observe(self, target: Target) -> Record:
        """Reconcile a confirmed run only; ignore nonmonotonic evidence."""
        record = self._required(target)
        if record.run is None or record.phase != "accepted":
            return record
        try:
            outcome = self.worker.observe(record.run)
        except (TimeoutError, ConnectionError):
            return self._hold(record, "launch-unknown")
        return self._apply(record, outcome)

    def reconcile_run(self, target: Target) -> Record:
        """Refresh a known run after a transport hold, without starting a new one."""
        record = self._required(target)
        if record.run is None or record.reason != "launch-unknown":
            return record
        try:
            outcome = self.worker.observe(record.run)
        except (TimeoutError, ConnectionError):
            return record
        if outcome == "running":
            return self._confirm(record, phase="accepted")
        return self._apply(record, outcome)

    def cancel(self, target: Target) -> Record:
        """Request fake interruption once; acknowledgement alone cannot confirm it."""
        record = self._required(target)
        if record.phase != "accepted" or record.run is None:
            return record
        intent = self._hold(record, "cancel-unknown")
        try:
            outcome = self.worker.cancel(record.run)
        except (TimeoutError, ConnectionError):
            return intent
        return self._apply(intent, outcome) if outcome in ("interrupted", "permission", "unavailable", "rejected") else intent

    def publication(self, target: Target) -> Record:
        """Simulate exactly one COMMENT attempt and recover only by attributed lookup."""
        r = self._required(target)
        if r.phase == "reviewed":
            return r
        pending = r.phase == "review-intent" or r.reason == "review-unknown"
        if r.phase != "complete" and not pending:
            return r
        try:
            if not self.reviews.target_matches(target):
                return self._hold(r, "stale-target")
        except (TimeoutError, ConnectionError):
            return self._hold(r, "review-unknown")
        if not pending:
            r = self._confirm(r, phase="review-intent")
        try:
            receipt = self.reviews.find(target, self._marker) if pending else self.reviews.comment(
                target, self._marker
            )
        except (TimeoutError, ConnectionError):
            return self._hold(r, "review-unknown")
        if (receipt is None or
                (receipt.repository, receipt.base, receipt.pr, receipt.author,
                 receipt.reviewer, receipt.head, receipt.marker, receipt.kind) !=
                (target.repository, target.base, target.pr, target.author,
                 target.reviewer, target.head, self._marker, "COMMENT")):
            return self._hold(r, "review-unknown")
        return self._confirm(r, phase="reviewed", receipt=receipt, next_actor="none")

    def _bound(self, target: Target) -> Record | None:
        record = self.journal.load()
        if record is not None and record.fingerprint != target.fingerprint:
            raise ValueError("Dispatch scope changed; no action taken.")
        return record

    def _required(self, target: Target) -> Record:
        record = self._bound(target)
        if record is None:
            raise ValueError("No accepted dispatch scope.")
        return record

    def _confirm(
        self, record: Record, *,
        phase: Literal["accepted", "complete", "review-intent", "reviewed"],
        run: Run | None = None, receipt: Receipt | None = None,
        next_actor: Literal["lead", "none"] = "lead",
    ) -> Record:
        return self.journal.save(Record(fingerprint=record.fingerprint, phase=phase,
                                        confirmed="complete" if phase == "review-intent" else phase,
                                        run=run or record.run, receipt=receipt,
                                        next_actor=next_actor))

    def _hold(
        self, record: Record,
        reason: Literal["launch-unknown", "permission", "unavailable", "rejected",
                        "interrupted", "cancel-unknown", "stale-target", "review-unknown"],
    ) -> Record:
        return self.journal.save(Record(fingerprint=record.fingerprint, phase="hold",
                                        confirmed=record.confirmed,
                                        run=record.run, receipt=record.receipt,
                                        reason=reason,
                                        next_actor="owner" if reason == "permission" else "lead"))

    def _apply(self, record: Record, outcome: Outcome) -> Record:
        if outcome == "running":
            return record
        if outcome == "complete":
            return self._confirm(record, phase="complete")
        if outcome == "unknown":
            return self._hold(record, "launch-unknown")
        return self._hold(record, outcome)


class Fake:
    """Scripted worker and review store; records simulated effects for assertions."""

    def __init__(self) -> None:
        self.starts = 0
        self.posts = 0
        self.cancels = 0
        self.outcome: Outcome = "complete"
        self.current_head = "a"*40
        self.lost_start = False
        self.lost_post = False
        self.lost_observation = False
        self.receipt: Receipt | None = None

    def start(self, target: Target) -> Run:
        """Create a synthetic acceptance, optionally lose the acknowledgement."""
        self.starts += 1
        if self.lost_start:
            raise TimeoutError
        return Run(thread="fake-thread", turn="fake-turn")

    def observe(self, run: Run) -> Outcome:
        """Return the scripted status of the known synthetic run."""
        if self.lost_observation:
            raise ConnectionError
        return self.outcome

    def cancel(self, run: Run) -> Outcome:
        """Return a separately scripted interruption outcome."""
        self.cancels += 1
        return self.outcome

    def target_matches(self, target: Target) -> bool:
        """Represent an attributed fake lookup of repository, PR, actor and head."""
        return target == target_a() and self.current_head == target.head

    def comment(self, target: Target, marker: Literal["lighthouse:fake-dispatch-1"]) -> Receipt:
        """Record one fake COMMENT and optionally lose its POST acknowledgement."""
        self.posts += 1
        self.receipt = Receipt(id=1, repository=target.repository, base=target.base,
                               pr=target.pr, author=target.author, reviewer=target.reviewer,
                               head=target.head, marker=marker, kind="COMMENT")
        if self.lost_post:
            raise TimeoutError
        return self.receipt

    def find(self, target: Target, marker: Literal["lighthouse:fake-dispatch-1"]) -> Receipt | None:
        """Return a synthetic observation for attribution checks in the harness."""
        return self.receipt
