"""Opt-in fixed selected-topology proof: only four harmless Python children."""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import cast
from unittest.mock import Mock

import pytest
import t02_capture_native_composition as release
from t02_capture_composition import execute_capture, open_existing_capture
from t02_capture_packet import CapturePacket
from t02_capture_pipe_owner import (
    CapturePipeHandles,
    CapturePipeOwner,
    _ChannelApi,
    _Connect,
    _event,
)
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

_native_only = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("LIGHTHOUSE_T02_SELECTED_NATIVE_PROOF") != "1",
    reason="explicitly selected offline native topology only",
)


class _PipeTrace:
    """Only fixed operation labels; never arguments, handles or exception text."""

    _STAGES = {
        "CreateNamedPipe": "server-create", "CreateFile": "client-open",
        "ConnectNamedPipe": "connect-begin", "GetCurrentProcess": "current-process",
        "DuplicateHandle": "handle-duplicate",
    }

    def __init__(self, api: object, event: Callable[[], int]) -> None:
        self.api = api
        self.event = event
        self.stage = "none"

    def __getattr__(self, name: str) -> object:
        original = getattr(self.api, name)
        if name not in self._STAGES:
            return original

        def call(*args: object) -> object:
            self.stage = self._STAGES[name]
            result = original(*args)
            self.stage += "-returned"
            if name == "ConnectNamedPipe":
                return _ConnectTrace(self, cast(_Connect, result))
            return result

        return call

    def make_event(self) -> int:
        self.stage = "stop-event"
        handle = self.event()
        self.stage = "stop-event-returned"
        return handle


class _ConnectTrace:
    def __init__(self, trace: _PipeTrace, result: _Connect) -> None:
        self.trace = trace
        self.result = result

    def GetOverlappedResult(self, wait: bool) -> tuple[int, int]:
        self.trace.stage = "connect-confirm"
        result = self.result.GetOverlappedResult(wait)
        self.trace.stage = "connect-confirmed" if result[1] == 0 else "connect-unconfirmed"
        return result


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("CreateNamedPipe", "server-create"), ("CreateFile", "client-open"),
        ("ConnectNamedPipe", "connect-begin"), ("confirm", "connect-confirm"),
        ("pending", "connect-unconfirmed"), ("event", "stop-event"),
        ("DuplicateHandle", "handle-duplicate"),
    ],
)
def test_pipe_trace_fault_labels_are_fixed(operation: str, expected: str) -> None:
    api = Mock()
    api.CreateNamedPipe.side_effect = [11, 21]
    api.CreateFile.side_effect = [12, 22]
    api.ConnectNamedPipe.return_value.GetOverlappedResult.return_value = (0, 0)
    event = Mock(return_value=31)
    cause = OSError("untrusted detail")
    if operation == "event":
        event.side_effect = cause
    elif operation == "confirm":
        api.ConnectNamedPipe.return_value.GetOverlappedResult.side_effect = cause
    elif operation == "pending":
        api.ConnectNamedPipe.return_value.GetOverlappedResult.return_value = (0, 996)
    else:
        getattr(api, operation).side_effect = cause
    trace = _PipeTrace(api, event)
    owner = CapturePipeOwner(lambda: 0, api=cast(_ChannelApi, trace), make_event=trace.make_event)
    with pytest.raises(Hold, match="capture private channel setup held"):
        owner.prepare(1)
    assert trace.stage == expected


@_native_only
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
    ipc_trace = _PipeTrace(importlib.import_module("_winapi"), _event)

    class DiagnosticPipeOwner(CapturePipeOwner):
        def __init__(self, clock: Callable[[], int]) -> None:
            super().__init__(clock, api=cast(_ChannelApi, ipc_trace), make_event=ipc_trace.make_event)

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
            ipc_phase, ipc_trace.stage, controller.bootstrap_phase, controller._terminal,
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
