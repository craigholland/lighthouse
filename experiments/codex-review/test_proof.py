"""Synthetic failure cases; no network, credentials or real runtime required."""

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import proof
import pytest
from harness import Fake, Journal, Outcome, Proof, Receipt, Record, target_a


class InterruptingJournal(Journal):
    """Inject a process stop immediately before or after one durable write."""

    def __init__(self, path: Path, phase: str, after_write: bool) -> None:
        super().__init__(path)
        self.phase = phase
        self.after_write = after_write

    def save(self, record: Record) -> Record:
        """Simulate loss at a chosen persistence boundary."""
        if record.phase != self.phase:
            return super().save(record)
        if self.after_write:
            super().save(record)
        raise RuntimeError("simulated interruption")


def test_success_replays_without_extra_effects(tmp_path: Path) -> None:
    """A receiver intent is not acceptance or completion; confirmed phases advance once."""
    fake = Fake()
    j = Journal(tmp_path / "receipt.json")
    p = Proof(j, fake, fake)
    t = target_a()
    assert p.dispatch(t).phase == "accepted"
    assert p.publication(t).phase == "accepted"
    assert p.dispatch(t).run is not None
    assert p.observe(t).phase == "complete"
    fake.outcome = "running"
    assert p.observe(t).phase == "complete"
    done = p.publication(t)
    assert done.receipt is not None
    assert (done.receipt.head, done.receipt.reviewer) == (t.head, t.reviewer)
    assert done.receipt.marker == "lighthouse:fake-dispatch-1"
    assert Proof(j, fake, fake).publication(t) == done
    assert fake.starts == fake.posts == 1
    with pytest.raises(ValueError, match="Dispatch scope changed"):
        p.dispatch(replace(t, context="approved-fixture-b"))


@pytest.mark.parametrize(
    ("phase", "after_write", "prior_starts", "resumed_state", "total_starts"),
    [
        ("launch-intent", False, 0, "accepted", 1),
        ("launch-intent", True, 0, "hold", 0),
        ("accepted", False, 1, "hold", 1),
        ("accepted", True, 1, "accepted", 1),
    ],
)
def test_restart_surrounding_persistence(
    tmp_path: Path, phase: str, after_write: bool, prior_starts: int,
    resumed_state: str, total_starts: int,
) -> None:
    """Recovery cannot infer acceptance from an intent, even if no launch occurred."""
    f = Fake()
    path = tmp_path / "receipt.json"
    with pytest.raises(RuntimeError, match="simulated interruption"):
        Proof(InterruptingJournal(path, phase, after_write), f, f).dispatch(target_a())
    assert f.starts == prior_starts
    assert Proof(Journal(path), f, f).dispatch(target_a()).phase == resumed_state
    assert f.starts == total_starts


def test_lost_start_acknowledgement_is_not_replayed(tmp_path: Path) -> None:
    """A lost start reply leaves no usable handle and enters an attention hold."""
    f = Fake()
    f.lost_start = True
    j = Journal(tmp_path / "receipt.json")
    t = target_a()
    hold = Proof(j, f, f).dispatch(t)
    assert (hold.reason, hold.next_actor, hold.run) == ("launch-unknown", "lead", None)
    p = Proof(j, f, f)
    assert p.dispatch(t) == p.reconcile_run(t) == hold
    assert f.starts == 1


def test_lost_observation_reconciles_known_run(tmp_path: Path) -> None:
    """Known-run lookup can recover without a new start."""
    f = Fake()
    j = Journal(tmp_path / "receipt.json")
    t = target_a()
    p = Proof(j, f, f)
    run = p.dispatch(t).run
    f.lost_observation = True
    assert p.observe(t).reason == "launch-unknown"
    assert p.reconcile_run(t).run == run
    f.lost_observation = False
    f.outcome = "running"
    restarted = Proof(j, f, f)
    assert restarted.reconcile_run(t).phase == "accepted"
    f.outcome = "complete"
    assert restarted.observe(t).phase == "complete"
    assert f.starts == 1


@pytest.mark.parametrize(
    ("outcome", "next_actor"),
    [("permission", "owner"), ("unavailable", "lead"), ("rejected", "lead")],
)
def test_permission_or_provider_failure_is_visible(
    tmp_path: Path, outcome: Outcome, next_actor: str
) -> None:
    """Escalation, rejection and unavailable provider capability cannot publish."""
    f = Fake()
    f.outcome = outcome
    p = Proof(Journal(tmp_path / "receipt.json"), f, f)
    t = target_a()
    accepted = p.dispatch(t)
    hold = p.observe(t)
    assert (hold.phase, hold.reason, hold.next_actor, hold.run) == (
        "hold", outcome, next_actor, accepted.run,
    )
    assert p.publication(t) == p.dispatch(t) == hold
    assert f.posts == 0 and f.starts == 1


@pytest.mark.parametrize(("outcome", "reason"), [
    ("interrupted", "interrupted"), ("running", "cancel-unknown"), ("complete", "cancel-unknown")
])
def test_interruption_does_not_launch_or_post(
    tmp_path: Path, outcome: Outcome, reason: str,
) -> None:
    """An unconfirmed interruption is not taken as successful cancellation or review."""
    f = Fake()
    f.outcome = outcome
    p = Proof(Journal(tmp_path / "receipt.json"), f, f)
    t = target_a()
    p.dispatch(t)
    hold = p.cancel(t)
    assert hold.reason == reason
    assert p.cancel(t) == p.publication(t) == hold
    assert f.cancels == 1 and f.posts == 0 and f.starts == 1


def test_changed_head_blocks_fake_comment(tmp_path: Path) -> None:
    """Target freshness is checked at publication, not only at dispatch."""
    f = Fake()
    f.current_head = "b"*40
    t = target_a()
    p = Proof(Journal(tmp_path / "receipt.json"), f, f)
    p.dispatch(t)
    p.observe(t)
    assert p.publication(t).reason == "stale-target"
    assert f.posts == 0


def test_lost_fake_post_acknowledgement_looks_up_only(tmp_path: Path) -> None:
    """Retry reconciles the marker rather than posting again."""
    f = Fake()
    f.lost_post = True
    j = Journal(tmp_path / "receipt.json")
    t = target_a()
    p = Proof(j, f, f)
    p.dispatch(t)
    p.observe(t)
    assert p.publication(t).reason == "review-unknown"
    assert f.receipt is not None
    existing = f.receipt
    f.receipt = None
    restarted = Proof(j, f, f)
    assert restarted.publication(t).reason == "review-unknown"
    f.receipt = existing.model_copy(update={"reviewer": 999})
    assert restarted.publication(t).reason == "review-unknown"
    f.receipt = existing
    assert restarted.publication(t).receipt == existing
    assert f.posts == 1


def test_lost_review_persistence_never_posts_twice(tmp_path: Path) -> None:
    """Restore by marker after a process stops before the review receipt is saved."""
    f = Fake()
    path = tmp_path / "receipt.json"
    p = Proof(InterruptingJournal(path, "reviewed", False), f, f)
    t = target_a()
    p.dispatch(t)
    p.observe(t)
    with pytest.raises(RuntimeError):
        p.publication(t)
    assert Proof(Journal(path), f, f).publication(t).phase == "reviewed"
    assert f.posts == 1


def test_journal_rejects_unsanitized_values(tmp_path: Path) -> None:
    """Untrusted values cannot leak through deserialization errors or reports."""
    path = tmp_path / "receipt.json"
    unsafe = "example-untrusted-token"
    path.write_text('{"dispatch":"' + unsafe + '","phase":"accepted"}', encoding="utf-8")
    with pytest.raises(RuntimeError) as captured:
        Journal(path).load()
    assert unsafe not in str(captured.value)
    assert str(tmp_path) not in str(captured.value)
    assert Receipt.model_fields["marker"].is_required()


@pytest.mark.parametrize("operation", ["import", "--help", "--dry-run", "--live", "example-untrusted-secret"])
def test_real_entry_point_is_fenced(operation: str, tmp_path: Path) -> None:
    """Guard real dry-run, help and import from provider capabilities and credentials."""
    script = """
import importlib.abc
import runpy
import sys

class NoProvider(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in {"openai_codex", "openai_codex_cli_bin", "requests",
                                          "httpx", "github", "keyring"}:
            raise AssertionError("Provider import in offline path")
        return None

def fence(event, args):
    if event.startswith(("socket.", "subprocess.", "os.startfile")) or event == "os.system":
        raise AssertionError("Forbidden effect in offline path")
    if event == "open" and isinstance(args[0], str):
        name = args[0].lower().replace(chr(92), "/")
        if any(value in name for value in ("/credentials/", "/.codex/", "fake-credentials")):
            raise AssertionError("Credential read in offline path")

sys.meta_path.insert(0, NoProvider())
sys.addaudithook(fence)
folder, operation = sys.argv[1:]
sys.path.insert(0, folder)
if operation == "import":
    import proof
else:
    sys.argv = ["proof.py", operation]
    runpy.run_module("proof", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(Path(__file__).resolve().parent), operation],
        cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False,
    )
    if operation in {"--live", "example-untrusted-secret"}:
        assert result.returncode == 2
        assert "live execution is disabled" in result.stderr
        assert operation not in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert not result.stderr
        if operation == "import":
            assert not result.stdout
        else:
            assert "dry-run" in result.stdout or "Offline fake result" in result.stdout
    assert str(tmp_path) not in result.stdout + result.stderr

def test_cli_hides_scratch_path_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A journal failure does not print a machine path or traceback."""
    def fail(*, prefix: str) -> None:
        raise OSError("X:/synthetic/private")
    monkeypatch.setattr(sys, "argv", ["proof.py", "--dry-run"])
    monkeypatch.setattr(proof, "TemporaryDirectory", fail)
    assert proof.main() == 1
    result = capsys.readouterr()
    assert not result.out
    assert result.err == "Offline proof could not use its scratch journal.\n"
