"""Inert address capture; intentionally has no callback or sender capability."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import astuple, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from t02_event_assembly import LoopbackHttp
from t02_event_rpc import ProbeRpc
from t02_event_types import EVENT, HOST, TOKEN, Hold, encode, verified_secret

_SCHEMA = """CREATE TABLE capture (
    slot INTEGER PRIMARY KEY CHECK(slot=1),
    binding TEXT NOT NULL,
    provenance BLOB NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('new','reserved','captured','held')),
    candidate TEXT,
    captured_ms INTEGER
) STRICT"""


@dataclass(frozen=True)
class CaptureBinding:
    """Exact stage-specific source revision and private proof envelope."""

    source_head: str
    proof_id: str
    principal: str
    not_before_ms: int
    deadline_ms: int

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-f0-9]{40}", self.source_head)
            or not TOKEN.fullmatch(self.proof_id) or not TOKEN.fullmatch(self.principal)
            or type(self.not_before_ms) is not int or type(self.deadline_ms) is not int
            or not 0 < self.deadline_ms - self.not_before_ms <= 900_000
        ):
            raise Hold("invalid capture binding")


def _candidate(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048 or not value.isascii() or not value.startswith("https://"):
        raise Hold("candidate URL held")
    if any(character.isspace() or ord(character) < 33 or ord(character) >= 127 for character in value):
        raise Hold("candidate URL held")
    try:
        parts = urlsplit(value)
        if (
            not HOST.fullmatch(parts.netloc) or not re.fullmatch(r"/[A-Za-z0-9/_~-]{1,1024}", parts.path)
            or "//" in parts.path or value != "https://" + parts.netloc + parts.path
        ):
            raise Hold("candidate URL held")
    except ValueError:
        raise Hold("candidate URL held") from None
    return value


class CaptureStore:
    """Durable one-slot store; reservation is committed before capture data."""

    def __init__(self, path: Path, binding: CaptureBinding) -> None:
        self.path = path.resolve()
        self.binding = binding
        self._provenance = encode((astuple(binding), EVENT, {"proof_id": binding.proof_id}))
        self._fingerprint = hashlib.sha256(encode((str(self.path), astuple(binding), EVENT))).hexdigest()

    @contextmanager
    def _edit(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.5)) as db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
        except sqlite3.Error:
            raise Hold("capture persistence unavailable or uncertain") from None

    def setup_fixture(self) -> None:
        """Explicit disposable setup, never invoked by RPC or a live entry."""
        self.path.touch(exist_ok=False)
        with self._edit() as db:
            db.execute(_SCHEMA)
            db.execute("INSERT INTO capture VALUES (1,?,?,'new',NULL,NULL)", (self._fingerprint, self._provenance))

    def _read(self, db: sqlite3.Connection) -> tuple[str, str | None, int | None]:
        schema = db.execute("SELECT sql FROM sqlite_schema").fetchall()
        rows = db.execute("SELECT binding, provenance, disposition, candidate, captured_ms FROM capture").fetchall()
        if schema != [(_SCHEMA,)] or len(rows) != 1 or rows[0][:2] != (self._fingerprint, self._provenance):
            raise Hold("unexpected capture binding or schema")
        _, _, stage, candidate, captured = rows[0]
        if ((candidate is None) != (captured is None)
            or (stage in {"new", "reserved"} and candidate is not None)
            or (stage == "captured" and candidate is None)):
            raise Hold("inconsistent capture")
        if candidate is not None:
            _candidate(candidate)
            if type(captured) is not int or not self.binding.not_before_ms <= captured < self.binding.deadline_ms:
                raise Hold("capture time outside binding")
        assert isinstance(stage, str)
        return stage, candidate, captured

    def capture(self, value: str, clock: Callable[[], int]) -> None:
        _candidate(value)
        with self._edit() as db:
            stage, saved, _ = self._read(db)
            if stage != "new":
                if stage == "reserved" or (stage == "captured" and saved != value):
                    db.execute("UPDATE capture SET disposition='held' WHERE slot=1")
                return
            db.execute("UPDATE capture SET disposition='reserved' WHERE slot=1")
        with self._edit() as db:
            stage, _, _ = self._read(db)
            now = clock()
            if stage == "reserved":
                if self.binding.not_before_ms <= now < self.binding.deadline_ms:
                    db.execute("UPDATE capture SET disposition='captured',candidate=?,captured_ms=? WHERE slot=1",
                               (value, now))
                else:
                    db.execute("UPDATE capture SET disposition='held' WHERE slot=1")


class CaptureSource:
    """Accepted framing and authentication, but every subscribe yields a hold."""

    def __init__(self, binding: CaptureBinding, store: CaptureStore, clock: Callable[[], int]) -> None:
        if store.binding != binding:
            raise Hold("capture store binding mismatch")
        self.binding = binding
        self._store = store
        self._clock = clock

    def check_principal(self, caller: str | None, *, allow_stopped: bool = False) -> None:
        if caller != self.binding.principal or not self.binding.not_before_ms <= self._clock() < self.binding.deadline_ms:
            raise Hold("capture authority unavailable")

    def subscribe(self, caller: str | None, params: dict[str, object]) -> dict[str, object]:
        self.check_principal(caller)
        if (
            not params.keys() <= {"name", "arguments", "delivery", "cursor", "ttlMs"}
            or params.get("name") != EVENT or params.get("arguments") != {"proof_id": self.binding.proof_id}
            or params.get("cursor") is not None
        ):
            raise Hold("capture scope mismatch")
        ttl = params.get("ttlMs")
        if ttl is not None and (type(ttl) is not int or not 0 < ttl <= 86_400_000):
            raise Hold("invalid capture TTL")
        delivery = params.get("delivery")
        if not isinstance(delivery, dict) or set(delivery) != {"mode", "url", "secret"} or delivery["mode"] != "webhook":
            raise Hold("capture delivery held")
        candidate = _candidate(delivery["url"])
        verified_secret(delivery["secret"])  # Validate then discard; no sender exists.
        self._store.capture(candidate, self._clock)
        raise Hold("capture only, subscription not admitted")

    def unsubscribe(self, caller: str | None, params: dict[str, object]) -> None:
        raise Hold("capture does not admit subscriptions")


def capture_receiver(binding: CaptureBinding, store: CaptureStore, bearer: str, clock: Callable[[], int]) -> LoopbackHttp:
    """Compose only the existing pure request adapter; no real listener or activation entry."""
    return LoopbackHttp(ProbeRpc(CaptureSource(binding, store, clock)), binding, bearer)
