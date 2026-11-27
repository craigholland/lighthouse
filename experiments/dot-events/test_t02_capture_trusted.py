"""The selected trusted-account proof binds ordered roles and original deadlines."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_selected_native_fixture as fixture
from t02_capture_bootstrap import InheritedCapture
from t02_capture_peer import PeerBinding
from t02_capture_trusted import TrustedInheritedCapabilities
from t02_event_types import Hold


def test_trusted_ledger_binds_exact_run_role_and_job_order() -> None:
    expected = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100), "b" * 40, "c" * 64)
    pipe, stop, job = Mock(return_value=True), Mock(return_value=True), Mock(return_value=True)
    ledger = TrustedInheritedCapabilities("supervisor", expected, (21, 22), pipe, stop, job)
    assert ledger.matches("supervisor", expected)
    assert not ledger.matches("coordinator", expected)
    assert not ledger.matches("supervisor", replace(expected, packet_digest="d" * 64))
    assert not ledger.matches("supervisor", replace(expected, peer=replace(expected.peer, intake_ms=49)))
    assert not ledger.owns_pipe(19) and not ledger.owns_listener_pipe(11)
    assert not ledger.owns_stop(12) and not ledger.owns_coordinator_stop(13)
    assert not ledger.owns_jobs((22, 21))
    pipe.assert_not_called()
    stop.assert_not_called()
    job.assert_not_called()
    assert ledger.owns_pipe(11) and ledger.owns_stop(13) and ledger.owns_jobs((21, 22))
    job.return_value = False
    assert not ledger.owns_jobs((21, 22))
    with pytest.raises(Hold):
        TrustedInheritedCapabilities("listener", expected, (21, 22), pipe, stop, job)
    with pytest.raises(Hold):
        TrustedInheritedCapabilities("supervisor", expected, (13, 21), pipe, stop, job)


def test_fixture_reports_pre_witness_stage_without_native_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Mock(python=tmp_path / "pythonw.exe", mono=lambda: 0)
    host = fixture.FixtureCoordinatorHost(context)
    descriptor = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100), "b" * 40, "c" * 64)
    fake = Mock(return_value=False)
    monkeypatch.setattr(fixture, "spawn_fixture", fake)
    assert host.bootstrap_phase == "not-attempted"
    assert not host.start_bootstrap(descriptor)
    assert host.bootstrap_phase == "launch-returned-false-before-retain"
    assert host._outer_root is None and host._outer_job is None
    fake.assert_called_once()
