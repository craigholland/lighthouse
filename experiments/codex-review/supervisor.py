"""One bounded timeline for independently contained proof phases."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Action(StrEnum):
    """Nonblocking actions the parent may take on its own jobs."""

    WAIT = "wait"
    INTERRUPT = "interrupt"
    TERMINATE = "terminate"
    HOLD = "hold"
    ADVANCE = "advance"
    SHUTDOWN_UNCONFIRMED = "shutdown-unconfirmed"


@dataclass(frozen=True)
class Observation:
    """Separate local shutdown and attributed operation evidence."""

    worker_exited: bool = False
    active_processes: int | None = None
    completed: bool = False

    @property
    def locally_quiescent(self) -> bool:
        """Both job accounting and the retained worker handle are required."""
        return self.worker_exited and self.active_processes == 0


class Timeline:
    """Never reset the monotonic deadline when changing phases."""

    def __init__(self, entered_at: float) -> None:
        self._entered_at = entered_at
        self._review_interrupted = False

    def verifier(self, now: float, state: Observation) -> Action:
        """Require trusted verification and local exit before 30 seconds."""
        elapsed = now - self._entered_at
        if elapsed >= 900 and not state.locally_quiescent:
            return Action.SHUTDOWN_UNCONFIRMED
        if elapsed >= 30:
            return Action.HOLD if state.locally_quiescent else Action.TERMINATE
        if state.locally_quiescent:
            return Action.ADVANCE if state.completed else Action.HOLD
        return Action.WAIT

    def review(self, now: float, state: Observation, *, known_active: bool) -> Action:
        """Reserve interruption time; a timed out run never becomes publishable."""
        elapsed = now - self._entered_at
        if elapsed >= 900 and not state.locally_quiescent:
            return Action.SHUTDOWN_UNCONFIRMED
        if state.locally_quiescent:
            return Action.ADVANCE if (
                state.completed and elapsed < 780 and not self._review_interrupted
            ) else Action.HOLD
        if elapsed >= 840:
            return Action.SHUTDOWN_UNCONFIRMED
        if elapsed >= 810:
            return Action.TERMINATE
        if elapsed >= 780 and known_active and not self._review_interrupted:
            self._review_interrupted = True
            return Action.INTERRUPT
        return Action.WAIT

    def publisher(self, now: float, state: Observation, *, started: bool) -> Action:
        """Allow one attributed COMMENT only after the caller verifies eligibility."""
        elapsed = now - self._entered_at
        if not started:
            return Action.ADVANCE if elapsed < 840 else Action.HOLD
        if elapsed >= 900 and not state.locally_quiescent:
            return Action.SHUTDOWN_UNCONFIRMED
        if elapsed >= 870:
            return Action.HOLD if state.locally_quiescent else Action.TERMINATE
        if state.locally_quiescent:
            return Action.ADVANCE if state.completed else Action.HOLD
        return Action.WAIT



class Role(StrEnum):
    """Closed list of separately contained stages, never caller-supplied commands."""

    VERIFIER = "verifier"
    REVIEW = "review"
    PUBLISHER = "publisher"


class OwnedJobs(Protocol):
    """Nonblocking local-only control; IO, SDK and network belong in children."""

    def start(self, role: Role) -> None: ...
    def snapshot(self, role: Role) -> Observation: ...
    def request_interrupt(self, role: Role) -> None: ...
    def force(self, role: Role) -> None: ...


class Supervisor:
    """Drive one proof across separate jobs; invalid evidence can only hold."""

    def __init__(self, clock: Callable[[], float], jobs: OwnedJobs) -> None:
        self._clock = clock
        self._timeline = Timeline(clock())
        self._jobs = jobs
        self._stage: Role | None = None
        self._result: Action | None = None
        self._forced = False

    def start(self) -> None:
        """Begin the read-only verifier only; caller already checked invocation shape."""
        if self._stage is not None or self._result is not None:
            raise RuntimeError("Proof already started.")
        if self._timeline.verifier(self._clock(), Observation()) != Action.WAIT:
            self._result = Action.HOLD
            return
        self._start(Role.VERIFIER)

    def tick(self, *, known_active_turn: bool = False) -> Action:
        """Take at most one nonblocking action; no external call runs in the parent."""
        if self._result is not None:
            return self._result
        stage = self._stage
        if stage is None:
            return Action.HOLD
        try:
            state = self._jobs.snapshot(stage)
            now = self._clock()
            if stage == Role.VERIFIER:
                action = self._timeline.verifier(now, state)
            elif stage == Role.REVIEW:
                action = self._timeline.review(now, state, known_active=known_active_turn)
            else:
                action = self._timeline.publisher(now, state, started=True)
            if action == Action.TERMINATE:
                if not self._forced:
                    self._forced = True
                    self._jobs.force(stage)
            elif action == Action.INTERRUPT:
                self._jobs.request_interrupt(stage)
            elif action in (Action.HOLD, Action.SHUTDOWN_UNCONFIRMED):
                if action == Action.SHUTDOWN_UNCONFIRMED and not self._forced:
                    # A late scheduler tick must not skip local containment cleanup.
                    self._forced = True
                    self._jobs.force(stage)
                self._result = action
            elif action == Action.ADVANCE:
                if stage == Role.VERIFIER:
                    self._start(Role.REVIEW)
                elif stage == Role.REVIEW:
                    if self._timeline.publisher(
                        self._clock(), Observation(), started=False
                    ) == Action.ADVANCE:
                        self._start(Role.PUBLISHER)
                    else:
                        self._result = Action.HOLD
                else:
                    self._result = Action.ADVANCE
            return self._result or action
        except (OSError, RuntimeError):
            self._result = Action.SHUTDOWN_UNCONFIRMED
            return self._result

    def _start(self, stage: Role) -> None:
        """A failed child start is a terminal hold; no retry or fallback."""
        self._stage = stage
        self._forced = False
        try:
            self._jobs.start(stage)
        except (OSError, RuntimeError):
            self._result = Action.SHUTDOWN_UNCONFIRMED
