"""SQLite transaction boundary for the offline Lighthouse ledger."""

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

from lighthouse.adapters.sqlite._codec import (
    change_from,
    encode_change,
    encode_intent,
    encode_state,
    intent_from,
    state_from,
)
from lighthouse.application.ledger import (
    Change,
    Intent,
    IntentStatus,
    LedgerError,
    WriteResult,
)
from lighthouse.application.review_dispatch import (
    Attempt,
    Cleanup,
    Lifecycle,
    Remote,
    Stage,
    StartupDiagnostic,
    StartupProgress,
    Target,
)
from lighthouse.domain.workflow import Binding, Decision, Outcome, State

_VERSION = 2
_DISPATCHING = (Outcome.IMPLEMENT, Outcome.REVIEW, Outcome.REVISE)
_SCHEMA = (
    "CREATE TABLE projects (repo TEXT PRIMARY KEY NOT NULL, state TEXT NOT NULL) STRICT",
    "CREATE TABLE audit (repo TEXT NOT NULL REFERENCES projects(repo), "
    "observation TEXT NOT NULL, version INTEGER NOT NULL, change TEXT NOT NULL, "
    "PRIMARY KEY (repo, observation), UNIQUE (repo, version)) STRICT",
    "CREATE TABLE intents (id TEXT PRIMARY KEY NOT NULL, "
    "repo TEXT NOT NULL REFERENCES projects(repo), data TEXT NOT NULL) STRICT",
    "CREATE TABLE review_attempts (dispatch TEXT PRIMARY KEY NOT NULL REFERENCES intents(id), "
    "repo TEXT NOT NULL REFERENCES projects(repo), data TEXT NOT NULL) STRICT",
)
_REJECTED = "Ledger unavailable or invalid; stop and inspect the selected file without resetting it."
_INVALID = "Invalid ledger change; inspect normalized evidence before recording."
_T = TypeVar("_T")


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load(data: str, parse: Callable[[dict[str, Any]], _T]) -> _T:
    try:
        raw = json.loads(data)
        if not isinstance(raw, dict) or _dump(raw) != data:
            raise ValueError
        return parse(raw)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise LedgerError(_REJECTED) from None



_HOLDS = {
    Stage.EXECUTION_UNKNOWN, Stage.APPROVAL_REQUIRED, Stage.CLEANUP_UNCONFIRMED,
    Stage.UNKNOWN_AND_CLEANUP, Stage.UNAVAILABLE,
}


def _review_from(data: dict[str, Any]) -> Attempt:
    raw = data["target"]
    startup = data.get("startup")
    result = Attempt(
        Target(raw["repository"], raw["order"], raw["dispatch"], raw["issue"], raw["pr"],
               raw["head"], Binding(**raw["binding"])),
        data["fingerprint"], Stage(data["stage"]), data["thread"], data["turn"], data["output"],
        data["marker"], data["review_id"],
        Lifecycle(Remote(data["lifecycle"]["remote"]), Cleanup(data["lifecycle"]["cleanup"]),
                  data["lifecycle"]["approval"]),
        data.get("event", "COMMENT"),
        StartupDiagnostic(startup["reason"], StartupProgress(startup["progress"])) if startup is not None else None,
    )
    if not result.valid() or _dump({"event": "COMMENT", "startup": None, **data}) != _dump(asdict(result)):
        raise ValueError
    return result


@dataclass(frozen=True)
class OperatorSnapshot:
    """Current durable decision and independently attributed selected dispatch."""

    state: State
    decision: Decision | None
    intent: Intent | None
    attempt: Attempt | None
    issue: int | None
    assignee: int | None = None


class SQLiteLedger:
    """Explicit file adapter; each operation uses its own bounded connection."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self._uri = path.resolve().as_uri() + ("?mode=ro" if read_only else "?mode=rw")
        with self._connection() as conn:
            if (conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]
                    or conn.execute("PRAGMA foreign_key_check").fetchone() is not None):
                raise LedgerError(_REJECTED)
            for (repo,) in conn.execute("SELECT repo FROM projects"):
                self._state(conn, repo)
            for key, payload in conn.execute("SELECT id, data FROM intents"):
                self._stored_intent(key, payload)
            for dispatch, repo in conn.execute("SELECT dispatch, repo FROM review_attempts"):
                self._attempt(conn, repo, dispatch)

    @classmethod
    def initialize(cls, path: Path) -> SQLiteLedger:
        """Create a deliberately new file; never initialize an existing file."""
        try:
            with path.open("xb"):
                pass
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as conn:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    for query in _SCHEMA:
                        conn.execute(query)
                    conn.execute(f"PRAGMA user_version = {_VERSION}")
        except (OSError, sqlite3.Error):
            raise LedgerError(_REJECTED) from None
        return cls(path)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self._uri, uri=True, timeout=2.0)) as conn, conn:
                conn.execute("PRAGMA foreign_keys = ON")
                if not write:
                    conn.execute("PRAGMA query_only = ON")
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                schemas = conn.execute(
                    "SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL"
                ).fetchall()
                if (conn.execute("PRAGMA user_version").fetchone() != (_VERSION,)
                        or sorted(row[0] for row in schemas) != sorted(_SCHEMA)):
                    raise LedgerError(_REJECTED)
                yield conn
        except sqlite3.Error:
            raise LedgerError(_REJECTED) from None

    @staticmethod
    def _state(conn: sqlite3.Connection, repo: str) -> State:
        row = conn.execute("SELECT state FROM projects WHERE repo=?", (repo,)).fetchone()
        if row is None:
            return State(repo)
        state = _load(row[0], state_from)
        if state.repository != repo:
            raise LedgerError(_REJECTED)
        return state

    def state(self, repository: str) -> State:
        with self._connection() as conn:
            return self._state(conn, repository)

    def audit(self, repository: str) -> tuple[Change, ...]:
        with self._connection() as conn:
            self._state(conn, repository)
            rows = conn.execute(
                "SELECT observation, version, change FROM audit WHERE repo=? ORDER BY version",
                (repository,),
            )
            results = []
            for observation, version, payload in rows:
                change = _load(payload, change_from)
                if (change.decision.state.repository, change.decision.state.version,
                        change.observation) != (repository, version, observation):
                    raise LedgerError(_REJECTED)
                results.append(change)
            return tuple(results)

    def intents(self, repository: str) -> tuple[Intent, ...]:
        with self._connection() as conn:
            self._state(conn, repository)
            results = []
            for key, payload in conn.execute(
                "SELECT id, data FROM intents WHERE repo=? ORDER BY id", (repository,)
            ):
                results.append(self._stored_intent(key, payload))
            return tuple(results)

    @staticmethod
    def _stored_intent(key: str, payload: str) -> Intent:
        intent = _load(payload, intent_from)
        if intent.dispatch_id != key:
            raise LedgerError(_REJECTED)
        return intent

    def record(self, change: Change) -> WriteResult:
        """Atomically persist the successor and associated evidence or do nothing."""
        try:
            data = _dump(encode_change(change))
            _load(data, change_from)
        except (LedgerError, ValueError, TypeError, RecursionError):
            raise LedgerError(_INVALID) from None
        successor = change.decision.state
        repo = successor.repository
        with self._connection(write=True) as conn:
            prior = self._state(conn, repo)
            row = conn.execute(
                "SELECT change FROM audit WHERE repo=? AND observation=?", (repo, change.observation)
            ).fetchone()
            if row is not None:
                _load(row[0], change_from)
                return WriteResult.DUPLICATE if row[0] == data else WriteResult.CONFLICT
            if prior.version != change.expected or successor.version <= prior.version:
                return WriteResult.STALE
            if not self._preserves_claim(prior, change):
                return WriteResult.CONFLICT
            intent = change.intent
            if change.decision.outcome in _DISPATCHING and intent is None:
                return WriteResult.CONFLICT
            if intent is not None:
                current = conn.execute(
                    "SELECT repo, data FROM intents WHERE id=?", (intent.dispatch_id,)
                ).fetchone()
                if not self._matches_intent(prior, change, intent, current):
                    return WriteResult.CONFLICT
            conn.execute(
                "INSERT INTO projects VALUES (?, ?) ON CONFLICT(repo) DO UPDATE SET state=excluded.state",
                (repo, _dump(encode_state(successor))),
            )
            conn.execute("INSERT INTO audit VALUES (?, ?, ?, ?)",
                         (repo, change.observation, successor.version, data))
            if intent is not None:
                conn.execute(
                    "INSERT INTO intents VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (intent.dispatch_id, repo, _dump(encode_intent(intent))),
                )
            return WriteResult.COMMITTED

    @staticmethod
    def _preserves_claim(prior: State, change: Change) -> bool:
        after, before = change.decision.state.work, prior.work
        if before is None:
            return after is None or change.decision.outcome is Outcome.IMPLEMENT
        if after is None:
            return change.decision.outcome is Outcome.COMPLETE
        return (
            (before.issue, before.order, before.binding) == (after.issue, after.order, after.binding)
            and (before.pr is None or before.pr == after.pr)
        )

    @classmethod
    def _matches_intent(
        cls, prior: State, change: Change, intent: Intent, current: tuple[str, str] | None,
    ) -> bool:
        decision = change.decision
        work = decision.state.work
        if not work or work.order != intent.order or (intent.pr is not None and work.pr != intent.pr):
            return False
        if current:
            repo, payload = current
            saved = cls._stored_intent(intent.dispatch_id, payload)
            return (
                decision.outcome not in _DISPATCHING and repo == decision.state.repository
                and intent == replace(saved, status=intent.status)
                and (saved.status is intent.status or intent.status is IntentStatus.UNCERTAIN)
            )
        return (
            intent.status is IntentStatus.PENDING and intent.operation == decision.outcome.value
            and work.pr == intent.pr
            and (decision.outcome is Outcome.IMPLEMENT
                 or (decision.outcome in (Outcome.REVIEW, Outcome.REVISE) and any(
                     (op, head, pr) == (decision.outcome, intent.head, intent.pr)
                     for op, head, pr, _ in decision.state.action_keys - prior.action_keys
                 )))
        )

    @staticmethod
    def _attempt(conn: sqlite3.Connection, repository: str, dispatch: str) -> Attempt | None:
        row = conn.execute(
            "SELECT data FROM review_attempts WHERE repo=? AND dispatch=?", (repository, dispatch),
        ).fetchone()
        if row is None:
            return None
        result = _load(row[0], _review_from)
        if (result.target.repository, result.target.dispatch) != (repository, dispatch):
            raise LedgerError(_REJECTED)
        return result

    def operator_snapshot(self, repository: str, dispatch: str | None) -> OperatorSnapshot:
        """Select current guidance and original dispatch admission atomically."""
        with self._connection() as conn:
            state = self._state(conn, repository)
            latest = conn.execute("SELECT change FROM audit WHERE repo=? AND version=?",
                                  (repository, state.version)).fetchone()
            decision = _load(latest[0], change_from).decision if latest else None
            if (state.version >= 0 and decision is None) or (decision and decision.state != state):
                raise LedgerError(_REJECTED)
            original = assignee = None
            for (payload,) in conn.execute("SELECT change FROM audit WHERE repo=? ORDER BY version DESC",
                                           (repository,)):
                event = _load(payload, change_from)
                recorded, work = event.intent, event.decision.state.work
                if recorded is None or work is None or recorded.order != work.order:
                    continue
                if dispatch is None and state.work and (work.issue, work.order) == (
                    state.work.issue, state.work.order,
                ):
                    dispatch = recorded.dispatch_id
                if (recorded.dispatch_id == dispatch and recorded.status is IntentStatus.PENDING
                        and recorded.operation == event.decision.outcome.value):
                    original, assignee = work.issue, event.decision.actor
                    break
            if dispatch is None:
                return OperatorSnapshot(state, decision, None, None, state.work.issue if state.work else None)
            row = conn.execute("SELECT data FROM intents WHERE repo=? AND id=?",
                               (repository, dispatch)).fetchone()
            intent = self._stored_intent(dispatch, row[0]) if row else None
            attempt = self._attempt(conn, repository, dispatch)
            if (intent is not None and original is None) or (attempt is not None and attempt.target.issue != original):
                raise LedgerError(_REJECTED)
            return OperatorSnapshot(state, decision, intent, attempt, original, assignee)

    def review_attempt(self, repository: str, dispatch: str) -> Attempt | None:
        """Read durable dispatch status without advancing it."""
        with self._connection() as conn:
            return self._attempt(conn, repository, dispatch)

    def _review_current(self, conn: sqlite3.Connection, t: Target) -> bool:
        """Read the existing T04 disposition and exact intent inside the writer boundary."""
        state = self._state(conn, t.repository)
        work = state.work
        if state.outcome is not Outcome.REVIEW or work is None or (
            work.issue, work.order, work.pr, work.binding,
        ) != (t.issue, t.order, t.pr, t.binding):
            return False
        row = conn.execute("SELECT change FROM audit WHERE repo=? AND version=?",
                           (t.repository, state.version)).fetchone()
        if row is None:
            raise LedgerError(_REJECTED)
        latest = _load(row[0], change_from).decision
        if (latest.state != state or latest.outcome not in {Outcome.REVIEW, Outcome.UNCHANGED}
                or latest.evidence[:1] != (t.head,)):
            return False
        intent = conn.execute("SELECT data FROM intents WHERE repo=? AND id=?",
                              (t.repository, t.dispatch)).fetchone()
        return intent is not None and self._stored_intent(t.dispatch, intent[0]) == Intent(
            t.dispatch, t.order, Outcome.REVIEW.value, t.pr, t.head,
        )

    def claim_review(self, attempt: Attempt) -> bool:
        """Reserve only a committed review intent; any unresolved review blocks another."""
        if attempt.stage is not Stage.CLAIMED or not attempt.valid():
            return False
        t = attempt.target
        with self._connection(write=True) as conn:
            if not self._review_current(conn, t):
                return False
            for (saved_id,) in conn.execute("SELECT dispatch FROM review_attempts WHERE repo=?", (t.repository,)):
                old = self._attempt(conn, t.repository, saved_id)
                if old is None or old.target.dispatch == t.dispatch or old.stage not in {Stage.COMMENTED, Stage.STALE}:
                    return False
            conn.execute("INSERT INTO review_attempts VALUES (?, ?, ?)",
                         (t.dispatch, t.repository, _dump(asdict(attempt))))
            return True

    def advance_review(self, expected: Attempt, updated: Attempt) -> bool:
        """Compare-and-set a single stage; never mutate the accepted identity."""
        t = expected.target
        allowed = {
            Stage.CLAIMED: {Stage.STARTING, *_HOLDS},
            Stage.STARTING: {Stage.ACCEPTED, *_HOLDS},
            Stage.ACCEPTED: {Stage.COMPLETED, *_HOLDS},
            Stage.CLEANUP_UNCONFIRMED: {Stage.COMPLETED},
            Stage.COMPLETED: {Stage.PUBLISHING, Stage.STALE},
            Stage.PUBLISHING: {Stage.COMMENTED},
        }
        if (not updated.valid() or updated.target != t or updated.fingerprint != expected.fingerprint
                or updated.stage not in allowed.get(expected.stage, set())
                or (updated.stage is not Stage.ACCEPTED
                    and (updated.thread, updated.turn) != (expected.thread, expected.turn))
                or (expected.output and (updated.output, updated.event) != (expected.output, expected.event))
                or (expected.marker and updated.marker != expected.marker)):
            return False
        with self._connection(write=True) as conn:
            if self._attempt(conn, t.repository, t.dispatch) != expected:
                return False
            if updated.stage in {Stage.STARTING, Stage.PUBLISHING} and not self._review_current(conn, t):
                return False
            conn.execute("UPDATE review_attempts SET data=? WHERE repo=? AND dispatch=?",
                         (_dump(asdict(updated)), t.repository, t.dispatch))
            return True
