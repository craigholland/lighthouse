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
from t02_selected_native_fixture import (
    FixtureCoordinatorHost,
    FixtureRoleTrace,
    fixture_provider,
    fixture_role_start,
    observe_after_terminal,
)
from t02_selected_native_roles import RPC_CAPTURED, trace_capture_stage
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
        "DuplicateHandle": "handle-duplicate", "WaitForSingleObject": "connect-wait",
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

    @property
    def event(self) -> int:
        return self.result.event

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
        ("WaitForSingleObject", "connect-wait"),
        ("DuplicateHandle", "handle-duplicate"),
    ],
)
def test_pipe_trace_fault_labels_are_fixed(operation: str, expected: str) -> None:
    api = Mock()
    api.CreateNamedPipe.side_effect = [11, 21]
    api.CreateFile.side_effect = [12, 22]
    api.WaitForSingleObject.return_value = 0
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


def test_fixture_role_trace_preserves_held_and_unconfirmed_results() -> None:
    roles = Mock()
    roles.start_runtime.side_effect = Hold("private synthetic diagnostics must not escape")
    roles.confirmed_stopped.return_value = False
    trace = FixtureRoleTrace(roles)
    trace.arm(40)
    trace.start_listener(20)
    with pytest.raises(Hold):
        trace.start_runtime(20)
    trace.signal_all()
    assert not trace.confirmed_stopped(40)
    assert trace.stages == [
        "arm-entered", "arm-returned", "listener-entered", "listener-returned",
        "runtime-entered", "runtime-held", "stop-entered", "stop-returned",
        "reconcile-entered", "reconcile-unconfirmed",
    ]
    roles.wait_candidate.assert_not_called()
    roles.signal_all.assert_called_once_with()


@pytest.mark.parametrize("terminal", (False, "cutoff", "raised", "unknown"))
def test_independent_witness_runs_without_promoting_production(terminal: str | bool) -> None:
    effects = Mock()
    effects.production.return_value = terminal
    if terminal == "raised":
        effects.production.side_effect = Hold("production held")
        with pytest.raises(Hold, match="production held"):
            observe_after_terminal(effects.production, effects.independent)
    else:
        if terminal == "unknown":
            effects.independent.side_effect = Hold("independent unavailable")
        assert observe_after_terminal(effects.production, effects.independent) == terminal
    assert [call[0] for call in effects.mock_calls] == ["production", "independent"]


@pytest.mark.parametrize("stalled", (False, True))
def test_fixture_role_start_publishes_before_ack_or_stall(stalled: bool) -> None:
    calls = Mock()
    calls.ready.return_value = True
    calls.live.return_value = True
    launch = fixture_role_start(calls.ready, calls.live, calls.publish, calls.stall if stalled else None)
    assert launch(25)
    assert [call[0] for call in calls.mock_calls] == ["ready", "live", "publish"] + (["stall"] if stalled else [])
    calls.reset_mock()
    calls.live.return_value = False
    assert not launch(25)
    calls.publish.assert_not_called()
    calls.stall.assert_not_called()


def test_one_shot_capture_trace_reports_held_without_retry() -> None:
    emit = Mock()
    action = Mock(side_effect=Hold("private trace text"))
    with pytest.raises(Hold, match="private trace text"):
        trace_capture_stage("subscribe", emit, action)
    action.assert_called_once_with()
    assert [call.args for call in emit.call_args_list] == [("subscribe-entered",), ("subscribe-held",)]
    emit.side_effect = OSError("trace unavailable")
    success = Mock(return_value=True)
    assert trace_capture_stage("store", emit, success)
    success.assert_called_once_with()


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

    from dataclasses import replace

    observed = local_observation(packet)
    projection = replace(
        observed, canonical_non_reparse_files=(*observed.canonical_non_reparse_files[:-1], str(state.path)),
    )
    bind, _ = ctx.installation(None)
    monkeypatch.setattr(release.ReviewedHost, "observe", lambda *_: projection)
    launches: list[FixtureCoordinatorHost] = []

    def host(*_: object) -> FixtureCoordinatorHost:
        assert not launches
        launches.append(controller)
        return controller

    import t02_capture_installation as installation

    monkeypatch.setattr(installation, "select_installation", lambda role=None: bind if role is None else None)
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
        supervisor = read_marker(root, "supervisor-result.json") if (root / "supervisor-result.json").is_file() else {}
        assert result == "candidate-held" and reread.status() == ("stopped", "captured"), (
            corroboration["fixed_role_stages"], corroboration["durable_status"],
            supervisor.get("phase"), supervisor.get("listener_attempted"), supervisor.get("runtime_attempted"),
            (root / "listener-ready.pending").is_file(), (root / "listener-ready.json").is_file(),
            (root / "runtime-ready.json").is_file(),
            tuple(
                f"{stage}-{status}"
                for stage in ("receiver", "initialize", "initialized", "list", "subscribe", "store", "capture-marker")
                for status in ("entered", "returned", "held")
                if (root / f"capture-{stage}-{status}.json").is_file()
            ),
        )
        assert (root / RPC_CAPTURED).is_file()
        before = read_marker(root, "before-cutoff.json")
        after = read_marker(root, "normal-role-stop.json")
        assert before["roles"] == [[False, 1], [False, 1]]
        assert after["status"] == "confirmed" and after["roles"] == [[True, 0], [True, 0]]
        live_at, stopped_at = before["at"], after["at"]
        assert type(live_at) is int and type(stopped_at) is int
        assert started <= live_at < started + 4200 and live_at <= stopped_at < started + 8000
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
