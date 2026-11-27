"""Private, inert T02 proof of one handoff and one managed marker effect."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Work:
    """Captured synthetic authorization and exact target, independent of event IDs."""

    project: str
    repository: str
    issue: int
    dispatch: str
    scope: str
    revision: str
    role: str
    worker: str
    host: str
    checkout: str
    authority: str
    expires: int
    state_path: str


@dataclass(frozen=True)
class Observation:
    """Trusted fixture's current work and observed worker availability."""

    work: Work
    connected: bool


@dataclass(frozen=True)
class Acceptance:
    """Known-task acceptance, not delivery acknowledgement or work completion."""

    dispatch: str
    worker: str
    revision: str
    turn: str


@dataclass(frozen=True)
class Delivery:
    """Independent transport receipt and optional attributable native evidence."""

    acknowledged: bool
    acceptance: Acceptance | None = None


class KnownWorker(Protocol):
    """No creation, fallback, or replacement operation exists on this port."""

    def continue_known(self, work: Work) -> Delivery: ...

    def inspect_known(self, work: Work) -> Acceptance | None: ...


@dataclass(frozen=True)
class Status:
    """Canonical evidence; a marker is incomplete proof without native attribution."""

    attempted: bool = False
    acknowledged: bool = False
    turn: str | None = None
    started: bool = False
    marker: bool = False
    hold: str | None = None

    @property
    def attributed_completion(self) -> bool:
        return self.marker and self.turn is not None and self.hold is None


class StateError(Exception):
    """Missing, invalid, mismatched or unavailable experimental state."""


_SCHEMA = """
CREATE TABLE proof (
    slot INTEGER PRIMARY KEY CHECK(slot = 1),
    binding TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt IN (0, 1)),
    ack INTEGER NOT NULL DEFAULT 0 CHECK(ack IN (0, 1) AND ack <= attempt),
    turn TEXT CHECK(turn IS NULL OR (attempt = 1 AND length(turn) BETWEEN 1 AND 128)),
    started INTEGER NOT NULL DEFAULT 0 CHECK(started IN (0, 1) AND started <= attempt),
    marker INTEGER NOT NULL DEFAULT 0 CHECK(marker IN (0, 1) AND marker <= started),
    conflict INTEGER NOT NULL DEFAULT 0 CHECK(conflict IN (0, 1) AND (conflict = 0 OR turn IS NOT NULL))
) STRICT
"""
_VERSION = 3
_CONFLICT_HOLD = "attention: conflicting acceptance for the bound worker"
_ALLOWED_EFFECT = "fixed synthetic marker v1"


class Proof:
    """Single owner of the SQLite intents and the fixed local effect.

    The existing database and its parent directory are operator-owned, private,
    non-replaceable for the proof's lifetime, and on a local filesystem.
    """

    def __init__(
        self,
        path: Path,
        work: Work,
        worker: KnownWorker,
        observe: Callable[[], Observation],
        clock: Callable[[], int],
    ) -> None:
        self._path = path.resolve()
        self._work = work
        self._worker = worker
        self._observe = observe
        self._clock = clock
        self._binding = hashlib.sha256(
            json.dumps((str(self._path), _ALLOWED_EFFECT, astuple(work))).encode()
        ).hexdigest()

    def seed_fixture(self) -> None:
        """Explicit one-time synthetic setup; runtime methods never create state."""
        if not self._fresh():
            raise StateError("invalid fixture binding")
        if self._path.with_suffix(".marker").exists():
            raise StateError("fixture marker already exists")
        self._path.touch(exist_ok=False)
        with self._transaction(validate=False) as db:
            db.execute(_SCHEMA)
            db.execute(f"PRAGMA user_version = {_VERSION}")
            db.execute("INSERT INTO proof(slot,binding) VALUES (1,?)", (self._binding,))

    @contextmanager
    def _transaction(self, *, validate: bool = True) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path.as_uri() + "?mode=rw", uri=True, timeout=1)) as db:
            db.execute("PRAGMA synchronous = FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                if validate:
                    self._read(db)
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _read(self, db: sqlite3.Connection) -> Status:
        if db.execute("PRAGMA user_version").fetchone() != (_VERSION,):
            raise StateError("unexpected schema version")
        definitions = db.execute("SELECT sql FROM sqlite_schema").fetchall()
        if (
            len(definitions) != 1 or not isinstance(definitions[0][0], str)
            or definitions[0][0].strip() != _SCHEMA.strip()
        ):
            raise StateError("unexpected schema")
        rows = db.execute("SELECT binding,attempt,ack,turn,started,marker,conflict FROM proof").fetchall()
        if len(rows) != 1:
            raise StateError("missing or conflicting reservation")
        binding, attempt, ack, turn, started, marker, conflict = rows[0]
        if (
            binding != self._binding
            or any(type(value) is not int or value not in (0, 1)
                   for value in (attempt, ack, started, marker, conflict))
            or ack > attempt or started > attempt or marker > started
            or (conflict and turn is None)
            or (turn is not None and (not self._valid_turn(turn) or not attempt))
        ):
            raise StateError("unexpected binding or corrupt record")
        hold = None
        if conflict:
            hold = _CONFLICT_HOLD
        elif (attempt and turn is None) or (started and not marker):
            hold = "attention: unresolved acceptance or effect"
        return Status(bool(attempt), bool(ack), turn, bool(started), bool(marker), hold)

    @staticmethod
    def _valid_turn(turn: object) -> bool:
        return isinstance(turn, str) and 1 <= len(turn) <= 128 and turn.isascii() and turn.isprintable() and not turn.isspace()

    def _fresh(self) -> bool:
        work = self._work
        current = self._observe()
        return (
            current.connected is True
            and current.work == work
            and work.state_path == str(self._path)
            and work.issue > 0
            and work.role == "dot-implementation"
            and all(isinstance(value, str) and bool(value.strip())
                    for value in astuple(work) if not isinstance(value, int))
            and self._clock() < work.expires
        )

    def status(self) -> Status:
        """Read persisted local evidence without granting either effect."""
        try:
            with self._transaction() as db:
                return self._read(db)
        except (sqlite3.Error, StateError, OSError):
            return Status(hold="attention: state unavailable or invalid")

    def _record(self, observed: Acceptance | None, *, acknowledged: bool = False) -> Status:
        try:
            with self._transaction() as db:
                current = self._read(db)
                if not current.attempted:
                    return current
                if acknowledged is True:
                    db.execute("UPDATE proof SET ack=1 WHERE slot=1")
                if observed is not None:
                    if (
                        not isinstance(observed, Acceptance)
                        or not self._valid_turn(observed.turn)
                        or (observed.dispatch, observed.worker, observed.revision)
                        != (self._work.dispatch, self._work.worker, self._work.revision)
                    ):
                        return Status(current.attempted, current.acknowledged or acknowledged,
                                      current.turn, current.started, current.marker,
                                      "attention: rejected acceptance evidence")
                    if current.turn is not None and current.turn != observed.turn:
                        db.execute("UPDATE proof SET conflict=1 WHERE slot=1")
                    else:
                        db.execute("UPDATE proof SET turn=? WHERE slot=1", (observed.turn,))
                return self._read(db)
        except (sqlite3.Error, StateError, OSError):
            return Status(hold="attention: receipt persistence uncertain")

    def on_event(self, event_id: str) -> Status:
        """Accept a hint, never using its identity as authority or dispatch identity."""
        if not event_id:
            return Status(hold="attention: missing event hint")
        try:
            with self._transaction() as db:
                current = self._read(db)
                if current.attempted:
                    return current
                if not self._fresh():
                    return Status(hold="attention: current context does not match")
                db.execute("UPDATE proof SET attempt=1 WHERE slot=1")
        except (sqlite3.Error, StateError, OSError):
            return Status(hold="attention: continuation intent uncertain")
        try:
            delivery = self._worker.continue_known(self._work)
        except Exception:
            return self.status()
        if not isinstance(delivery, Delivery) or type(delivery.acknowledged) is not bool:
            return self.status()
        return self._record(delivery.acceptance, acknowledged=delivery.acknowledged)

    def reconcile(self) -> Status:
        """Use only exact known-worker status, never perform another handoff."""
        current = self.status()
        if not current.attempted:
            return current
        try:
            observed = self._worker.inspect_known(self._work)
        except Exception:
            return current
        return self._record(observed)

    def receive(self) -> Status:
        """Validate then commit a start intent before invoking our fixed marker."""
        try:
            with self._transaction() as db:
                current = self._read(db)
                if current.started or current.hold == _CONFLICT_HOLD:
                    return current
                if not current.attempted or not self._fresh():
                    return Status(current.attempted, current.acknowledged, current.turn,
                                  hold="attention: receiver context not admitted")
                db.execute("UPDATE proof SET started=1 WHERE slot=1")
        except (sqlite3.Error, StateError, OSError):
            return Status(hold="attention: start intent uncertain")
        try:
            self._write_marker()
            with self._transaction() as db:
                db.execute("UPDATE proof SET marker=1 WHERE slot=1")
        except (sqlite3.Error, StateError, OSError):
            return self.status()
        return self.status()

    def _write_marker(self) -> None:
        """One fixed, harmless file effect; never execute commands or edit source."""
        with self._path.with_suffix(".marker").open("a", encoding="ascii") as stream:
            stream.write(self._binding + "\n")
