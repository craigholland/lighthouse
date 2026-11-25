"""Opt-in fixed selected-topology proof: only four harmless Python children."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from unittest.mock import Mock

import pytest
import t02_capture_native_composition as release
from t02_capture_composition import execute_capture, open_existing_capture
from t02_capture_packet import CapturePacket
from t02_capture_pipe_owner import CapturePipeHandles, CapturePipeOwner
from t02_event_types import Hold, encode
from t02_selected_native_context import (
    ACTIVATION,
    FIXTURE_SCOPE,
    REFS,
    FixtureContext,
    mono,
    read_marker,
    write_marker,
)
from t02_selected_native_fixture import FixtureCoordinatorHost, fixture_provider
from t02_selected_native_roles import RPC_CAPTURED
from test_t02_capture_lifecycle import local_observation, record

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("LIGHTHOUSE_T02_SELECTED_NATIVE_PROOF") != "1",
    reason="explicitly selected offline native topology only",
)


@pytest.mark.parametrize("mode", ("normal", "stall", "no-signal", "missing-root"))
def test_fixed_selected_native_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    root = tmp_path / ("lighthouse-native-" + uuid.uuid4().hex)
    root.mkdir()
    python = Path(getattr(sys, "_base_executable", sys.executable)).resolve(strict=True)
    gui = python.with_name("pythonw.exe").resolve(strict=True)
    assert python.name.casefold() == "python.exe" and gui.parent == python.parent
    packet = CapturePacket.parse(encode(record() | {
        "state": str(root / "capture.db"), "proof_id": "synthetic-native-proof",
        "filter": {"proof_id": "synthetic-native-proof"},
        "activation_ms": ACTIVATION, "intake_cutoff_ms": ACTIVATION + 4200,
        "cleanup_cutoff_ms": ACTIVATION + 8000,
    }))
    state = open_existing_capture(packet)
    state.prepare()
    identity = state.path.stat().st_ino
    started = mono()
    write_marker(root, "setup.json", {
        "scope": FIXTURE_SCOPE, "mode": mode, "started": started, "packet": packet.canonical.decode("ascii"),
    })
    ctx = FixtureContext.load(root, mode, gui)
    controller = FixtureCoordinatorHost(ctx)
    ipc_phase = "not-attempted"

    class DiagnosticPipeOwner(CapturePipeOwner):
        def prepare(self, deadline: int) -> CapturePipeHandles:
            nonlocal ipc_phase
            ipc_phase = "enter-prepare"
            try:
                handles = super().prepare(deadline)
            except (Hold, OSError):
                ipc_phase = "prepare-held"
                raise
            ipc_phase = "prepared"
            return handles

    pinned = Mock(python=python)
    from dataclasses import replace

    observed = local_observation(packet)
    pinned.observe.return_value = replace(
        observed, canonical_non_reparse_files=(*observed.canonical_non_reparse_files[:-1], str(state.path)),
    )
    bind = release.InstalledCapture(pinned, Mock())
    launches: list[FixtureCoordinatorHost] = []

    def host(*_: object) -> FixtureCoordinatorHost:
        assert not launches
        launches.append(controller)
        return controller

    monkeypatch.setattr(release, "INSTALLED_CAPTURE", bind)
    monkeypatch.setattr(release, "CaptureCoordinatorHost", host)
    monkeypatch.setattr(release, "CapturePipeOwner", DiagnosticPipeOwner)
    monkeypatch.setattr(release, "GitHubHttps", lambda _: fixture_provider(ctx))
    monkeypatch.setattr(release, "mono", mono)
    monkeypatch.setattr(release, "wall", ctx.wall)
    results: Queue[str | BaseException] = Queue(maxsize=1)

    def drive() -> None:
        try:
            results.put(execute_capture(packet, *REFS))
        except BaseException as exc:
            results.put(exc)

    operation = Thread(target=drive, daemon=True)
    operation.start()
    independently_stopped = False
    try:
        try:
            result = results.get(timeout=max(0, started + 20_000 - mono()) / 1000)
        except Empty:
            pytest.fail("selected native fixture exceeded case time")
        if isinstance(result, BaseException):
            raise result
        independently_stopped = controller.exact_outer_stopped(min(mono() + 250, started + 20_000))
        assert independently_stopped, (
            ipc_phase, controller.bootstrap_phase, controller._terminal,
            controller._outer_job is not None, controller._outer_root is not None, result,
        )
    finally:
        deadline = min(mono() + 5000, started + 25_000)
        try:
            if not independently_stopped and (controller._outer_job is not None or controller._process is not None):
                if controller._outer_job is not None and controller._outer_root is not None:
                    assert controller.exact_outer_stopped(deadline, terminate=True)
                else:
                    controller.request_stop(deadline)
                    assert controller.confirmed_quiescent(deadline)
            operation.join(max(0, deadline - mono()) / 1000)
            assert not operation.is_alive()
        finally:
            controller.close_outer_witnesses()
    elapsed = mono() - started
    assert elapsed < 20_000 and launches == [controller]
    assert controller._terminal is True
    assert state.path.stat().st_ino == identity
    reread = open_existing_capture(packet)
    corroboration = read_marker(root, "coordinator-result.json")
    assert corroboration["outcome"] == result
    if mode == "normal":
        assert result == "candidate-held" and reread.status() == ("stopped", "captured")
        assert (root / RPC_CAPTURED).is_file()
        assert read_marker(root, "supervisor-result.json")["phase"] == "confirmed"
    else:
        assert result == "cleanup-unknown" and reread.status() == ("cleanup-unknown", "new")
        assert not (root / RPC_CAPTURED).exists()
        assert not (root / "supervisor-result.json").exists()
        before = read_marker(root, "before-cutoff.json")
        after = read_marker(root, "cutoff-result.json")
        assert before["roles"] == after["roles"] == [[False, 1], [False, 1]]
        assert after["stopped"] == [[True, 0], [True, 0]]
        milestones = (before["at"], after["cutoff"], after["at"], after["signal_at"], after["confirmed_at"])
        assert all(type(tick) is int for tick in milestones)
        tick_before, cutoff, tick_due, signal, confirmed = (int(str(tick)) for tick in milestones)
        assert started <= tick_before < cutoff <= tick_due <= signal <= confirmed < started + 8000
        assert abs(cutoff - started - 4200) <= 10
        if mode == "no-signal":
            disabled = read_marker(root, "disabled-cutoff.json")
            assert disabled["roles"] == [[False, 1], [False, 1]]
            assert disabled["proof_deadline"] == cutoff + 500
            assert cutoff + 500 <= int(str(disabled["at"])) <= signal
            assert after["independent_proof"] is False
        elif mode == "missing-root":
            assert after["supervisor_root_confirmed"] is False and after["fixture_supervisor_exit"] is True
        else:
            assert after["supervisor_root_confirmed"] is True and after["independent_proof"] is True
            assert confirmed < cutoff + 500
    assert execute_capture(packet, *REFS) in {"admission-unknown", "denied"}
    assert launches == [controller]
    assert reread.status() == state.status() and state.path.stat().st_ino == identity
    print(f"selected native {mode}: {result} after {elapsed} ms")
