"""Real local SQLite tests using T04 decisions and fixed Python fixtures."""

import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_workflow import APPROVAL, CHECK, FACTS, ISSUE, PROJECT, PULL

from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.application.ledger import (
    Change,
    Intent,
    IntentStatus,
    Ledger,
    LedgerError,
    WriteResult,
)
from lighthouse.domain.workflow import Execution, Outcome, State, Workflow


def claim(repo: str = PROJECT.repository, *, order: str = "order") -> Change:
    snapshot = replace(FACTS, repository=repo, order=order, candidates=(replace(ISSUE, repository=repo),))
    decision = Workflow(replace(PROJECT, repository=repo)).evaluate(State(repo), snapshot)
    return Change(-1, "observation-1", decision, Intent("dispatch-" + order, order, "implement"))


def test_round_trip_and_reconciled_phase_without_another_intent(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger: Ledger = SQLiteLedger.initialize(path)
    seed = claim()
    assert ledger.record(seed) is WriteResult.COMMITTED
    engine = Workflow(PROJECT)
    facts = replace(FACTS, version=2, pull=PULL)
    review = engine.evaluate(seed.decision.state, facts)
    assert ledger.record(Change(1, "review", review,
                                Intent("review-dispatch", "order", "review", 8, "head-a"))
                         ) is WriteResult.COMMITTED
    approved = replace(facts, version=3, review=APPROVAL, verification=CHECK)
    waiting = engine.evaluate(review.state, approved)
    assert ledger.record(Change(2, "waiting", waiting)) is WriteResult.COMMITTED
    lost = engine.evaluate(waiting.state, replace(approved, version=4, verification=None))
    assert ledger.record(Change(3, "lost", lost)) is WriteResult.COMMITTED
    restored = engine.evaluate(lost.state, replace(approved, version=5))
    assert restored.outcome is Outcome.UNCHANGED and restored.state.outcome is Outcome.AWAIT_OWNER
    rejected = Change(4, "restored", restored, Intent("extra", "order", "review", 8, "head-a"))
    assert ledger.record(rejected) is WriteResult.CONFLICT
    assert ledger.record(replace(rejected, intent=None)) is WriteResult.COMMITTED
    ledger = SQLiteLedger(path)
    assert ledger.state(PROJECT.repository) == restored.state
    assert ledger.audit(PROJECT.repository)[-1].decision == restored
    assert len(ledger.intents(PROJECT.repository)) == 2


def test_dedup_stale_reservation_and_dispatch_collision(tmp_path: Path) -> None:
    ledger = SQLiteLedger.initialize(tmp_path / "ledger.db")
    seed = claim()
    assert ledger.record(seed) is WriteResult.COMMITTED
    assert ledger.record(seed) is WriteResult.DUPLICATE
    assert ledger.record(claim(order="other")) is WriteResult.CONFLICT
    assert ledger.record(replace(claim(order="other"), observation="different")) is WriteResult.STALE
    other = claim("sample/two")
    assert ledger.record(other) is WriteResult.CONFLICT
    assert ledger.state("sample/two").work is None
    assert ledger.record(claim("sample/two", order="two")) is WriteResult.COMMITTED
    assert ledger.state(PROJECT.repository) == seed.decision.state
    assert ledger.audit(PROJECT.repository) == (seed,)


def test_late_statement_failure_rolls_back_everything(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger.initialize(path)
    seed = claim()

    class FailingInsert(sqlite3.Connection):
        def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
            if sql.startswith("INSERT INTO intents"):
                raise sqlite3.OperationalError("injected write failure")
            return super().execute(sql, parameters)

    connect = sqlite3.connect
    with pytest.MonkeyPatch.context() as patch:
        def injected(*args: object, **kwargs: object) -> sqlite3.Connection:
            return connect(*args, **kwargs, factory=FailingInsert)
        patch.setattr(sqlite3, "connect", injected)
        with pytest.raises(LedgerError, match="stop and inspect"):
            ledger.record(seed)
    assert ledger.state(PROJECT.repository).work is None
    assert ledger.audit(PROJECT.repository) == ledger.intents(PROJECT.repository) == ()
    assert ledger.record(seed) is WriteResult.COMMITTED


_CHILD = """
import runpy, sys, time
from dataclasses import replace
from pathlib import Path
from lighthouse.adapters.sqlite.ledger import SQLiteLedger
from lighthouse.domain.workflow import State
helpers = runpy.run_path(sys.argv[1])
db = SQLiteLedger(Path(sys.argv[2]))
mode = sys.argv[3]
if mode == "inspect":
    state = db.state("sample/one")
    print(state.work.order if state.work else "", *(i.status.value for i in db.intents("sample/one")))
else:
    request = replace(helpers["claim"](order=mode), observation=mode)
    assert db.state("sample/one") == State("sample/one")
    Path(sys.argv[4]).with_name(mode + ".ready").touch()
    print("ready", flush=True)
    limit = time.monotonic() + 5
    while not Path(sys.argv[4]).exists():
        if time.monotonic() >= limit:
            raise SystemExit("fixture release timeout")
        time.sleep(.01)
    print(db.record(request).value)
"""


def _fixture(path: Path, mode: str, gate: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD, __file__, str(path), mode, str(gate)],
        env=None, cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_real_competing_processes_and_fresh_process_recovery(tmp_path: Path) -> None:
    path, gate = tmp_path / "ledger.db", tmp_path / "gate"
    ledger = SQLiteLedger.initialize(path)
    children: list[subprocess.Popen[str]] = []
    try:
        for claim_id in ("a", "b"):
            children.append(_fixture(path, claim_id, gate))
        # Both children must witness the unclaimed database before the first commit.
        deadline = time.monotonic() + 5
        for key in ("a", "b"):
            while not (tmp_path / (key + ".ready")).exists():
                if time.monotonic() >= deadline:
                    pytest.fail("child did not confirm readiness")
                time.sleep(.01)
        gate.touch()
        results = []
        for child in children:
            output, error = child.communicate(timeout=8)
            assert child.returncode == 0, error
            results.append(output.splitlines())
        assert sorted(results) == [["ready", "committed"], ["ready", "stale"]]

        state = ledger.state(PROJECT.repository)
        assert state.work is not None
        decision = Workflow(PROJECT).evaluate(
            state, replace(FACTS, version=2, implementation=Execution.UNKNOWN),
        )
        original, = ledger.intents(PROJECT.repository)
        assert original.status is IntentStatus.PENDING
        uncertain = replace(original, status=IntentStatus.UNCERTAIN)
        assert ledger.record(Change(1, "unknown", decision, uncertain)) is WriteResult.COMMITTED
        inspector = _fixture(path, "inspect", gate)
        children.append(inspector)
        output, error = inspector.communicate(timeout=8)
        assert inspector.returncode == 0, error
        assert output.strip() == state.work.order + " uncertain"
        assert ledger.intents(PROJECT.repository) == (uncertain,)
        reopened = SQLiteLedger(path)
        held = reopened.state(PROJECT.repository)
        assert held.work == state.work and held.outcome is Outcome.HOLD
        later = Workflow(PROJECT).evaluate(held, replace(FACTS, version=3,
                                                         implementation=Execution.UNKNOWN))
        assert reopened.record(Change(2, "later", later, original)) is WriteResult.CONFLICT
        assert reopened.state(PROJECT.repository) == held
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=3)


def test_initialize_is_deliberate_and_rejected_files_are_not_reset(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with pytest.raises(LedgerError):
        SQLiteLedger(path)
    assert not path.exists()
    path.write_bytes(b"not sqlite")
    with pytest.raises(LedgerError):
        SQLiteLedger(path)
    with pytest.raises(LedgerError):
        SQLiteLedger.initialize(path)
    assert path.read_bytes() == b"not sqlite"
    path = tmp_path / "unknown.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated (n INTEGER)")
    conn.close()
    with pytest.raises(LedgerError):
        SQLiteLedger(path)


@pytest.mark.parametrize("modification", ["PRAGMA user_version=2", "UPDATE projects SET state='{}'"])
def test_rejects_unsupported_version_and_malformed_state(tmp_path: Path, modification: str) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger.initialize(path)
    assert ledger.record(claim()) is WriteResult.COMMITTED
    with sqlite3.connect(path) as conn:
        conn.execute(modification)
    conn.close()
    before = path.read_bytes()
    with pytest.raises(LedgerError, match="without resetting"):
        SQLiteLedger(path)
    assert path.read_bytes() == before
