"""Offline cutoff tests and one native test of the harmless owned process tree."""

import os
import time

import pytest
from supervisor import Action, Observation, Role, Supervisor, Timeline
from windows_job import FixtureJob


def test_verifier_must_finish_before_30_on_same_clock() -> None:
    """An incomplete or stuck verifier cannot authorize review."""
    t = Timeline(5)
    assert t.verifier(34, Observation()) == Action.WAIT
    assert t.verifier(34, Observation(True, 0, True)) == Action.ADVANCE
    assert t.verifier(35, Observation()) == Action.TERMINATE
    assert t.verifier(35, Observation(True, 0, True)) == Action.HOLD
    assert t.verifier(905, Observation()) == Action.SHUTDOWN_UNCONFIRMED


def test_review_cutoffs_and_no_late_publication() -> None:
    """A hung start, read, interrupt or close cannot turn into success."""
    t = Timeline(5)
    assert t.review(784, Observation(), known_active=False) == Action.WAIT
    assert t.review(785, Observation(), known_active=False) == Action.WAIT
    assert t.review(785, Observation(), known_active=True) == Action.INTERRUPT
    assert t.review(786, Observation(), known_active=True) == Action.WAIT
    assert t.review(815, Observation(True, 1), known_active=True) == Action.TERMINATE
    assert t.review(845, Observation(False, 0), known_active=True) == Action.SHUTDOWN_UNCONFIRMED
    assert t.review(846, Observation(True, 0, True), known_active=False) == Action.HOLD


def test_publisher_cutoffs_and_dual_shutdown_evidence() -> None:
    """The parent requires both local signals and respects the same deadline."""
    t = Timeline(5)
    assert t.publisher(844, Observation(), started=False) == Action.ADVANCE
    assert t.publisher(845, Observation(), started=False) == Action.HOLD
    assert t.publisher(875, Observation(True, 2, True), started=True) == Action.TERMINATE
    assert t.publisher(904, Observation(False, 0), started=True) == Action.TERMINATE
    assert t.publisher(905, Observation(True, None), started=True) == Action.SHUTDOWN_UNCONFIRMED


@pytest.mark.skipif(os.name != "nt", reason="Requires the Windows Job Object API")
def test_native_fixture_tree_is_contained_and_stopped() -> None:
    """Observe blocked worker/child/grandchild and then both shutdown conditions."""
    job = FixtureJob()
    try:
        job.start()
        deadline = time.monotonic() + 8
        while job.active_count() < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert job.active_count() == 3
        assert not job.wait_quiescent(0.03)
        job.force()
        assert job.wait_quiescent(5)
    finally:
        job.close()



class FakeJobs:
    """Each role emits only injected local/attributed observations."""

    def __init__(self) -> None:
        self.started: list[Role] = []
        self.forced: list[Role] = []
        self.interrupted: list[Role] = []
        self.states: dict[Role, Observation] = {}

    def start(self, role: Role) -> None:
        self.started.append(role)

    def snapshot(self, role: Role) -> Observation:
        return self.states.get(role, Observation())

    def request_interrupt(self, role: Role) -> None:
        self.interrupted.append(role)

    def force(self, role: Role) -> None:
        self.forced.append(role)


def test_distinct_supervised_jobs_advance_once() -> None:
    """No publisher until attributed review completion and both local observations."""
    now = [0.0]
    jobs = FakeJobs()
    supervisor = Supervisor(lambda: now[0], jobs)
    supervisor.start()
    assert jobs.started == [Role.VERIFIER]
    jobs.states[Role.VERIFIER] = Observation(True, 0, True)
    assert supervisor.tick() == Action.ADVANCE
    jobs.states[Role.REVIEW] = Observation(True, 1, True)
    assert supervisor.tick() == Action.WAIT
    jobs.states[Role.REVIEW] = Observation(True, 0, True)
    assert supervisor.tick() == Action.ADVANCE
    jobs.states[Role.PUBLISHER] = Observation(True, 0, True)
    assert supervisor.tick() == supervisor.tick() == Action.ADVANCE
    assert jobs.started == [Role.VERIFIER, Role.REVIEW, Role.PUBLISHER]


def test_hung_review_cannot_publish_even_after_late_success() -> None:
    """Interrupt and force are sent once, and local shutdown is not remote success."""
    now = [0.0]
    jobs = FakeJobs()
    supervisor = Supervisor(lambda: now[0], jobs)
    supervisor.start()
    jobs.states[Role.VERIFIER] = Observation(True, 0, True)
    supervisor.tick()
    now[0] = 780
    assert supervisor.tick(known_active_turn=True) == Action.INTERRUPT
    supervisor.tick(known_active_turn=True)
    now[0] = 810
    assert supervisor.tick(known_active_turn=True) == Action.TERMINATE
    supervisor.tick(known_active_turn=True)
    now[0] = 840
    assert supervisor.tick(known_active_turn=True) == Action.SHUTDOWN_UNCONFIRMED
    jobs.states[Role.REVIEW] = Observation(True, 0, True)
    assert supervisor.tick() == Action.SHUTDOWN_UNCONFIRMED
    assert jobs.started == [Role.VERIFIER, Role.REVIEW]
    assert jobs.interrupted == jobs.forced == [Role.REVIEW]



def test_late_scheduler_tick_still_signals_owned_job() -> None:
    """A missed intermediate tick cannot prevent the fail-closed force attempt."""
    now = [0.0]
    jobs = FakeJobs()
    supervisor = Supervisor(lambda: now[0], jobs)
    supervisor.start()
    jobs.states[Role.VERIFIER] = Observation(True, 0, True)
    assert supervisor.tick() == Action.ADVANCE
    now[0] = 900
    assert supervisor.tick() == Action.SHUTDOWN_UNCONFIRMED
    assert jobs.forced == [Role.REVIEW]
