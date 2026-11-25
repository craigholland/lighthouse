"""One durable subscription and fixed retry budget for the event probe only."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import cast

from t02_event_types import (
    EVENT,
    MARKER,
    TOKEN,
    Binding,
    Callback,
    Hold,
    decode,
    encode,
    fixed_url,
    utc,
    verified_secret,
)

_SCHEMA = """
CREATE TABLE event_probe (
    slot INTEGER PRIMARY KEY CHECK(slot=1),
    binding TEXT NOT NULL,
    url TEXT,
    secret TEXT,
    expires INTEGER,
    stopped INTEGER NOT NULL DEFAULT 0 CHECK(stopped IN (0,1)),
    checks INTEGER NOT NULL DEFAULT 0 CHECK(checks IN (0,1,2)),
    sent INTEGER NOT NULL DEFAULT 0 CHECK(sent BETWEEN 0 AND 3),
    pending TEXT CHECK(pending IS NULL OR pending IN ('verify','send')),
    event_id TEXT,
    occurred INTEGER,
    last TEXT CHECK(last IS NULL OR last IN ('ack','retry')),
    duplicated INTEGER NOT NULL DEFAULT 0 CHECK(duplicated IN (0,1)),
    restarted INTEGER NOT NULL DEFAULT 0 CHECK(restarted IN (0,1))
) STRICT
"""


@dataclass(frozen=True)
class State:
    url: str | None
    secret: str | None
    expires: int | None
    stopped: int
    checks: int
    sent: int
    pending: str | None
    event_id: str | None
    occurred: int | None
    last: str | None
    duplicated: int
    restarted: int


class EventSource:
    """Owns persistent windows and one reserve-before-send protocol."""

    def __init__(
        self, state_path: Path, binding: Binding, callback: Callback,
        clock: Callable[[], int], random_id: Callable[[], str], principal_current: Callable[[], bool],
    ) -> None:
        self.path = state_path.resolve()
        self.binding = binding
        self.callback = callback
        self.clock = clock
        self.random_id = random_id
        self.principal_current = principal_current
        self.fingerprint = hashlib.sha256(encode((str(self.path), astuple(binding)))).hexdigest()

    def setup_disposable(self) -> None:
        """Explicit setup only; a run never creates or resets subscription state."""
        self.path.touch(exist_ok=False)
        with self._edit(check=False) as db:
            db.execute(_SCHEMA)
            db.execute("PRAGMA user_version=1")
            db.execute("INSERT INTO event_probe(slot,binding) VALUES (1,?)", (self.fingerprint,))

    @contextmanager
    def _edit(self, *, check: bool = True, timeout: float = 0.5) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=timeout)) as db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                if check:
                    self._read(db)
                yield db
                db.commit()
        except sqlite3.Error:
            raise Hold("subscription persistence unavailable or uncertain") from None

    def _read(self, db: sqlite3.Connection) -> State:
        ddl = db.execute("SELECT sql FROM sqlite_schema").fetchall()
        if (
            db.execute("PRAGMA user_version").fetchone() != (1,)
            or len(ddl) != 1 or not isinstance(ddl[0][0], str)
            or ddl[0][0].strip() != _SCHEMA.strip()
        ):
            raise Hold("unexpected probe schema")
        rows = db.execute(
            "SELECT binding,url,secret,expires,stopped,checks,sent,pending,event_id,occurred,last,duplicated,restarted FROM event_probe"
        ).fetchall()
        if len(rows) != 1 or rows[0][0] != self.fingerprint:
            raise Hold("probe state does not match private binding")
        state = State(*rows[0][1:])
        if (
            (state.url is None) != (state.secret is None)
            or (state.url is None) != (state.expires is None)
            or (state.event_id is None) != (state.occurred is None)
            or bool(state.sent) != bool(state.event_id)
            or (state.last is not None and not state.sent)
            or (state.duplicated and state.sent < 2)
            or (state.pending == "verify" and not state.checks)
            or (state.pending == "send" and not state.sent)
            or (state.sent and state.url is None)
            or (state.expires is not None
                and not self.binding.activation_ms < state.expires <= self.binding.deadline)
            or (state.event_id is not None and not TOKEN.fullmatch(state.event_id))
        ):
            raise Hold("inconsistent probe state")
        if state.url is not None:
            fixed_url(self.binding, state.url)
            verified_secret(state.secret)
        return state

    def _live(self, state: State) -> bool:
        now = self.clock()
        return (
            not state.stopped and self.binding.activation_ms <= now < self.binding.deadline
            and (state.expires is None or now < state.expires)
            and self.principal_current() is True
        )

    def observe_stop(self) -> bool:
        """Persist expiry or revoked configured authority when first observed."""
        with self._edit() as db:
            stopped = not self._live(self._read(db))
            if stopped:
                db.execute("UPDATE event_probe SET stopped=1 WHERE slot=1")
            return stopped

    def stop_for_cleanup(self, timeout: float) -> None:
        """Close the existing slot without changing its intent or allowances."""
        with self._edit(timeout=timeout) as db:
            db.execute("UPDATE event_probe SET stopped=1 WHERE slot=1 AND stopped=0")

    def durable_stop_confirmed(self, timeout: float) -> bool:
        """Check the stop flag in a separate connection, without inferring expiry."""
        with self._edit(check=False, timeout=timeout) as db:
            return self._read(db).stopped == 1

    def check_principal(self, caller: str | None, *, allow_stopped: bool = False) -> None:
        if caller != self.binding.principal or self.principal_current() is not True:
            raise Hold("probe principal not authorized")
        if self.observe_stop() and not allow_stopped:
            raise Hold("probe stopped")

    def check_filter(self, params: dict[str, object]) -> None:
        if params.get("name") != EVENT or params.get("arguments") != {"proof_id": self.binding.proof_id}:
            raise Hold("unknown proof filter")

    def _subscription_id(self) -> str:
        return "sub_" + hashlib.sha256(encode((
            self.binding.principal, self.binding.callback_host, self.binding.callback_path,
            EVENT, self.binding.proof_id,
        ))).hexdigest()

    def _new_id(self) -> str:
        token = self.random_id()
        if not TOKEN.fullmatch(token):
            raise Hold("random source unsuitable")
        return token

    def subscribe(self, caller: str | None, params: dict[str, object]) -> dict[str, object]:
        self.check_principal(caller)
        self.check_filter(params)
        if not params.keys() <= {"name", "arguments", "delivery", "cursor", "ttlMs"} or params.get("cursor") is not None:
            raise Hold("replay or unexpected subscription options")
        delivery = params.get("delivery")
        if not isinstance(delivery, dict) or set(delivery) != {"mode", "url", "secret"} or delivery["mode"] != "webhook":
            raise Hold("invalid webhook delivery")
        url = fixed_url(self.binding, delivery["url"])
        verified_secret(delivery["secret"])
        secret = cast(str, delivery["secret"])
        ttl = params.get("ttlMs", 900_000)
        if ttl is None:
            ttl = 900_000  # Indefinite request still gets a finite grant.
        if type(ttl) is not int or not 0 < ttl <= 86_400_000:
            raise Hold("invalid TTL")
        sid = self._subscription_id()
        with self._edit() as db:
            state = self._read(db)
            if not self._live(state) or state.pending is not None:
                raise Hold("subscription stopped or pending")
            expires = min(self.binding.deadline, self.clock() + ttl)
            if state.url == url and state.secret == secret:
                db.execute("UPDATE event_probe SET expires=? WHERE slot=1", (expires,))
                return {"id": sid, "refreshBefore": utc(expires), "cursor": None, "truncated": False}
            if state.checks >= 2:
                raise Hold("callback verification allowance consumed")
            challenge = self._new_id()
            msg = "verify_" + challenge[:100]
            db.execute("UPDATE event_probe SET checks=checks+1,pending='verify' WHERE slot=1")
        # The intent commits before the callback. Restart of a pending check
        # cannot retry it; stop and send use the same serialized authority.
        ok = False
        with self._edit() as db:
            state = self._read(db)
            if not self._live(state) or state.pending != "verify":
                raise Hold("verification no longer authorized")
            try:
                reply = self.callback.send(
                    self.binding, url, secret, sid, msg,
                    encode({"type": "verification", "challenge": challenge}), expires,
                )
                response = decode(reply.body, limit=1024)
                echoed = response.get("challenge")
                import hmac

                ok = (
                    200 <= reply.status < 300 and set(response) == {"challenge"}
                    and isinstance(echoed, str) and bool(TOKEN.fullmatch(echoed))
                    and hmac.compare_digest(challenge, echoed) and self._live(state)
                    and self.clock() < expires
                )
            except Hold:
                pass
            if ok:
                db.execute(
                    "UPDATE event_probe SET url=?,secret=?,expires=?,pending=NULL WHERE slot=1",
                    (url, secret, expires),
                )
            else:
                db.execute("UPDATE event_probe SET stopped=1,pending=NULL WHERE slot=1")
        if not ok:
            raise Hold("callback verification not established")
        return {"id": sid, "refreshBefore": utc(expires), "cursor": None, "truncated": False}

    def unsubscribe(self, caller: str | None, params: dict[str, object]) -> None:
        if caller != self.binding.principal or self.principal_current() is not True:
            raise Hold("probe principal not authorized")
        self.check_filter(params)
        delivery = params.get("delivery")
        if (
            set(params) != {"name", "arguments", "delivery"}
            or not isinstance(delivery, dict) or set(delivery) != {"mode", "url"}
            or delivery["mode"] != "webhook"
        ):
            raise Hold("invalid unsubscribe")
        fixed_url(self.binding, delivery["url"])
        with self._edit() as db:
            db.execute("UPDATE event_probe SET stopped=1 WHERE slot=1")

    def reserve_restart(self) -> None:
        """Consume the one planned source-restart allowance; never launch it."""
        with self._edit() as db:
            state = self._read(db)
            if not self._live(state) or state.pending is not None or state.restarted:
                raise Hold("source restart not authorized")
            db.execute("UPDATE event_probe SET restarted=1 WHERE slot=1")

    def deliver(self, *, duplicate: bool = False, retry: bool = False) -> str:
        """Synthetic operator phase only; transport acceptance is not Dot receipt."""
        if self.observe_stop() or self.clock() >= self.binding.send_until:
            raise Hold("delivery window closed")
        with self._edit() as db:
            state = self._read(db)
            if (
                not self._live(state) or state.pending is not None or state.url is None
                or state.sent >= 3 or self.clock() >= self.binding.send_until
            ):
                raise Hold("delivery not authorized")
            if duplicate and retry:
                raise Hold("ambiguous send intent")
            if duplicate:
                if state.duplicated or state.last != "ack":
                    raise Hold("one deliberate duplicate follows an acknowledged send")
            elif retry:
                if state.last != "retry":
                    raise Hold("retry requires an explicit transient response")
            elif state.sent != 0:
                raise Hold("fresh event already reserved")
            event_id = state.event_id or "event_" + self._new_id()[:100]
            occurred = state.occurred if state.occurred is not None else self.clock()
            db.execute(
                "UPDATE event_probe SET sent=sent+1,pending='send',event_id=?,occurred=?,"
                "duplicated=max(duplicated,?) WHERE slot=1",
                (event_id, occurred, int(duplicate)),
            )
        with self._edit() as db:
            state = self._read(db)
            if not self._live(state) or state.pending != "send":
                raise Hold("delivery no longer authorized")
            assert state.url is not None and state.secret is not None and state.expires is not None
            body = encode({
                "eventId": event_id, "name": EVENT, "timestamp": utc(occurred), "cursor": None,
                "data": {"proof_id": self.binding.proof_id, "marker": MARKER},
            })
            reply = self.callback.send(
                self.binding, state.url, state.secret, self._subscription_id(), event_id,
                body, min(self.binding.send_until, state.expires),
            )
            if 200 <= reply.status < 300:
                status = "ack"
            elif reply.status in (408, 425, 429, 500, 502, 503, 504):
                status = "retry"
            else:
                db.execute("UPDATE event_probe SET stopped=1,pending=NULL WHERE slot=1")
                return "stopped"
            db.execute("UPDATE event_probe SET pending=NULL,last=? WHERE slot=1", (status,))
            return status
