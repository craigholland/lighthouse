"""Inward contract for atomic offline workflow evidence."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from lighthouse.domain.workflow import Decision, State


class LedgerError(RuntimeError):
    """Fixed, operator-actionable storage failure."""


class WriteResult(Enum):
    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    STALE = "stale"
    CONFLICT = "conflict"


class IntentStatus(Enum):
    PENDING = "pending"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Intent:
    """Inert, typed intent data; an ID never authorizes execution."""

    dispatch_id: str
    order: str
    operation: str
    pr: int | None = None
    head: str | None = None
    status: IntentStatus = IntentStatus.PENDING


@dataclass(frozen=True)
class Change:
    """Expected version, stable observation revision, and T04 successor."""

    expected: int
    observation: str
    decision: Decision
    intent: Intent | None = None


class Ledger(Protocol):
    """Storage port. All caller-supplied identities are opaque, secret-free data."""

    def record(self, change: Change) -> WriteResult: ...
    def state(self, repository: str) -> State: ...
    def audit(self, repository: str) -> tuple[Change, ...]: ...
    def intents(self, repository: str) -> tuple[Intent, ...]: ...
