"""Fixed coordinator and supervisor entry for offline selected native proof only."""

from __future__ import annotations

import ctypes as c
import importlib
import json
import os
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from ctypes import wintypes as w
from pathlib import Path
from threading import Event, Thread
from typing import Protocol, cast

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import t02_capture_native_cutoff as native_cutoff
from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_composition import CaptureWindow, open_existing_capture
from t02_capture_coordinator import CoordinatorRun
from t02_capture_coordinator_windows import CaptureCoordinatorHost, owned_entry
from t02_capture_handoff import AcceptedHandoff
from t02_capture_host_entry import run_transferred_supervisor
from t02_capture_lifecycle import CaptureRoles
from t02_capture_trusted import Role, TrustedInheritedCapabilities
from t02_capture_windows_host import CaptureSupervisorHost
from t02_capture_windows_ownership import WindowsCaptureOwnership
from t02_event_evidence import PublicGitHub
from t02_event_types import Hold
from t02_event_windows import _Accounting, _kernel
from t02_selected_native_context import (
    FIXTURE_LEDGER,
    FixtureContext,
    mono,
    read_marker,
    spawn_fixture,
    write_marker,
)
from t02_selected_native_roles import FixtureRole, make_listener_role, make_runtime_role


class _Duplicate(Protocol):
    def GetCurrentProcess(self) -> int: ...
    def DuplicateHandle(self, source: int, handle: int, target: int, access: int,
                        inherit: bool, options: int) -> int: ...


class _UnicodeString(c.Structure):
    _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", c.c_void_p)]


def handle_checks() -> tuple[Callable[[int], bool], Callable[[int], bool], Callable[[int], bool]]:
    k = _kernel()
    filetype = k.GetFileType
    filetype.restype, filetype.argtypes = w.DWORD, (w.HANDLE,)
    query = c.WinDLL("ntdll").NtQueryObject
    query.restype, query.argtypes = w.LONG, (w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p)

    def is_event(handle: int) -> bool:
        data = c.create_string_buffer(1024)
        if query(handle, 2, c.byref(data), c.sizeof(data), None) != 0:
            return False
        info = _UnicodeString.from_buffer(data)
        first = c.addressof(data)
        pointer = info.buffer
        return bool(
            info.length == 10 and 10 <= info.maximum <= c.sizeof(data)
            and pointer is not None and first <= pointer <= first + c.sizeof(data) - info.maximum
            and c.wstring_at(pointer, 5) == "Event"
        )

    def is_job(handle: int) -> bool:
        data = _Accounting()
        return bool(k.QueryInformationJobObject(handle, 1, c.byref(data), c.sizeof(data), None))

    return lambda handle: filetype(handle) == 3, is_event, is_job


def trusted(role: Role) -> tuple[TrustedInheritedCapabilities, str]:
    data: object = json.loads(os.environ.get(FIXTURE_LEDGER, ""))
    if (not isinstance(data, dict) or set(data) != {"role", "descriptor", "jobs"}
        or data.get("role") != role or not isinstance(data["descriptor"], str)
        or not isinstance(data["jobs"], list) or any(type(item) is not int for item in data["jobs"])):
        raise Hold("fixture capability ledger held")
    pipe, stop, job = handle_checks()
    expected = InheritedCapture.accept(data["descriptor"], mono, pipe, stop)
    ledger = TrustedInheritedCapabilities(role, expected, tuple(data["jobs"]), pipe, stop, job)
    raw = os.environ.get(ENVIRONMENT_KEY, "")
    owns_pipe, owns_stop = {
        "coordinator": (ledger.owns_coordinator_pipe, ledger.owns_coordinator_stop),
        "supervisor": (ledger.owns_pipe, ledger.owns_stop),
        "listener": (ledger.owns_listener_pipe, ledger.owns_listener_stop),
    }[role]
    observed = InheritedCapture.accept(raw, mono, owns_pipe, owns_stop)
    if not ledger.matches(role, observed):
        raise Hold("fixture inherited capabilities do not match launch")
    return ledger, raw


class FixtureCoordinatorHost(CaptureCoordinatorHost):
    def __init__(self, context: FixtureContext) -> None:
        super().__init__(context.python.with_name("python.exe"), context.mono)
        self.context = context
        self._outer_job: int | None = None
        self._outer_root: int | None = None
        self.bootstrap_phase = "not-attempted"

    def start_bootstrap(self, descriptor: InheritedCapture) -> bool:
        self.bootstrap_phase = "enter-launch"

        def retain(job: int, root: int) -> None:
            self.bootstrap_phase = "retain-job"
            api = cast(_Duplicate, importlib.import_module("_winapi"))
            process = api.GetCurrentProcess()
            self._outer_job = api.DuplicateHandle(process, job, process, 0x000C, False, 0)
            self.bootstrap_phase = "retain-root"
            self._outer_root = api.DuplicateHandle(process, root, process, 0x100000, False, 0)
            self.bootstrap_phase = "before-resume-retained"

        started = spawn_fixture(self, self.context, "coordinator", descriptor, before_resume=retain)
        if started:
            self.bootstrap_phase = "started"
        elif self.bootstrap_phase == "enter-launch":
            self.bootstrap_phase = "launch-returned-false-before-retain"
        else:
            self.bootstrap_phase = "launch-returned-false-after-retain"
        return started

    def exact_outer_stopped(self, deadline: int, *, terminate: bool = False) -> bool:
        job, root = self._outer_job, self._outer_root
        if job is None or root is None:
            return False
        k = _kernel()
        if terminate and not k.TerminateJobObject(job, 1):
            return False
        while mono() < deadline:
            count = _Accounting()
            if (k.WaitForSingleObject(root, 0) == 0
                and k.QueryInformationJobObject(job, 1, c.byref(count), c.sizeof(count), None)
                and count.active == 0):
                return True
            time.sleep(0.005)
        return False

    def close_outer_witnesses(self) -> None:
        k = _kernel()
        for handle in (self._outer_job, self._outer_root):
            if handle is not None:
                k.CloseHandle(handle)
        self._outer_job = self._outer_root = None


def supervisor_host_class(context: FixtureContext) -> type[CaptureSupervisorHost]:
    class FixtureSupervisorHost(CaptureSupervisorHost):
        def start_owned_transfer(
            self, descriptor: InheritedCapture, jobs: tuple[int, int], supervisor_job: int,
            before_resume: Callable[[int, int], None],
        ) -> bool:
            return spawn_fixture(
                self, context, "supervisor", descriptor, jobs=jobs,
                preowned_job=supervisor_job, before_resume=before_resume,
            )

    return FixtureSupervisorHost


def supervisor(context: FixtureContext) -> int:
    ledger, raw = trusted("supervisor")
    descriptor = ledger.descriptor

    def build(accepted: AcceptedHandoff, job: int, *, listener: bool) -> FixtureRole:
        if not context.exact(accepted.packet, descriptor.peer.intake_ms):
            raise Hold("fixture role packet differs")
        instance = (make_listener_role if listener else make_runtime_role)(accepted, job, descriptor, context)
        if context.mode == "normal":
            return instance

        stage = "listener" if listener else "runtime"
        ready = instance.request_start

        def launch(deadline: int) -> bool:
            if not ready(deadline) or not instance.observes_live() or instance._witness is None:
                return False
            write_marker(context.root, stage + "-root.json", {"root": instance._witness._root})
            if not listener:
                # Deliberately withhold the real fixed supervisor's runtime-start acknowledgement.
                while True:
                    time.sleep(60)
            return True

        instance.request_start = launch  # type: ignore[method-assign]
        return instance

    terminal = run_transferred_supervisor(
        raw, mono, context.wall, ledger.owns_pipe, ledger.owns_stop, ledger.owns_jobs,
        lambda accepted, job: build(accepted, job, listener=True),
        lambda accepted, job: build(accepted, job, listener=False),
        provider=fixture_provider(context), require_coordinator=True,
    )
    write_marker(context.root, "supervisor-result.json", {
        "phase": terminal.phase, "listener_attempted": terminal.listener_attempted,
        "runtime_attempted": terminal.runtime_attempted,
    })
    return 0 if terminal.phase == "confirmed" else 2


def fixture_provider(context: FixtureContext) -> PublicGitHub:
    from t02_selected_native_context import _SyntheticGitHub

    return _SyntheticGitHub(context)


class CutoffObservation:
    """Keep native role root duplicates obtained only from this supervisor handle."""

    def __init__(self, context: FixtureContext, fixed: native_cutoff.FixedWindowsCutoff) -> None:
        self.context, self.fixed = context, fixed
        self.roots: list[int] = []
        self.done = Event()
        self.k = _kernel()
        match = self.k.IsProcessInJob
        match.restype, match.argtypes = w.BOOL, (w.HANDLE, w.HANDLE, c.POINTER(w.BOOL))
        self.match = match
        self.originals = fixed.roles._handles
        if self.originals is None:
            raise Hold("fixture originals missing")
        self.failure = False

    def follow_spawn(self, deadline: int) -> None:
        try:
            while mono() < deadline and not all(
                (self.context.root / (name + "-root.json")).is_file() for name in ("listener", "runtime")
            ):
                time.sleep(0.005)
            if mono() >= deadline:
                raise Hold("fixture role witness missed cutoff")
            source = self.fixed.host._process
            if source is None or self.k.WaitForSingleObject(source, 0) != 258:
                raise Hold("fixture exact supervisor root unavailable")
            api = cast(_Duplicate, importlib.import_module("_winapi"))
            current = api.GetCurrentProcess()
            assert self.originals is not None
            for index, name in enumerate(("listener", "runtime")):
                marker = read_marker(self.context.root, name + "-root.json")
                value = marker.get("root")
                if type(value) is not int or not 0 < value < 2**63:
                    raise Hold("fixture role receipt malformed")
                duplicate = api.DuplicateHandle(source, value, current, 0x00100400, False, 0)
                self.roots.append(duplicate)
                matched = w.BOOL()
                if not self.match(duplicate, self.originals[index], c.byref(matched)) or not matched.value:
                    raise Hold("fixture root is outside the exact original role Job")
            states = self.sample()
            if states != [(False, 1), (False, 1)] or mono() >= deadline:
                raise Hold("fixture roles not observed live before cutoff")
            write_marker(self.context.root, "before-cutoff.json", {"at": mono(), "roles": states})
        except (Hold, OSError, ValueError):
            self.failure = True
        finally:
            self.done.set()

    def sample(self) -> list[tuple[bool, int]]:
        assert self.originals is not None and len(self.roots) == 2
        result = []
        for root, job in zip(self.roots, self.originals, strict=True):
            data = _Accounting()
            status = self.k.WaitForSingleObject(root, 0)
            if status not in (0, 258) or not self.k.QueryInformationJobObject(
                job, 1, c.byref(data), c.sizeof(data), None,
            ):
                raise Hold("fixture role witness unavailable")
            result.append((status == 0, int(data.active)))
        return result

    def await_stopped(self, cleanup: int) -> list[tuple[bool, int]]:
        while mono() < cleanup:
            states = self.sample()
            if states == [(True, 0), (True, 0)]:
                return states
            time.sleep(0.005)
        raise Hold("fixture exact role cleanup not observed")

    def close(self) -> None:
        for handle in self.roots:
            self.k.CloseHandle(handle)


class FixtureRoleTrace:
    """Collect fixed stage labels without writing files during role execution."""

    def __init__(self, roles: CaptureRoles) -> None:
        self._roles = roles
        self.stages: list[str] = []

    def _step[R](self, label: str, operation: Callable[[int], R], deadline: int) -> R:
        self.stages.append(label + "-entered")
        try:
            result = operation(deadline)
        except (Hold, OSError, ValueError, KeyboardInterrupt):
            self.stages.append(label + "-held")
            raise
        self.stages.append(label + ("-unconfirmed" if result is False else "-returned"))
        return result

    def arm(self, cleanup_deadline_ms: int) -> None:
        self._step("arm", self._roles.arm, cleanup_deadline_ms)

    def start_listener(self, intake_deadline_ms: int) -> None:
        self._step("listener", self._roles.start_listener, intake_deadline_ms)

    def start_runtime(self, intake_deadline_ms: int) -> None:
        self._step("runtime", self._roles.start_runtime, intake_deadline_ms)

    def wait_candidate(self, intake_deadline_ms: int) -> None:
        self._step("candidate", self._roles.wait_candidate, intake_deadline_ms)

    def signal_all(self) -> None:
        self._step("stop", lambda _: self._roles.signal_all(), 0)

    def confirmed_stopped(self, cleanup_deadline_ms: int) -> bool:
        return self._step("reconcile", self._roles.confirmed_stopped, cleanup_deadline_ms)


def coordinator(context: FixtureContext) -> int:
    ledger, _ = trusted("coordinator")
    cap = ledger.descriptor.peer
    setattr(native_cutoff, "CaptureSupervisorHost", supervisor_host_class(context))
    native = WindowsCaptureOwnership(context.python.with_name("python.exe"), context.wall, mono, ledger)
    observation: CutoffObservation | None = None
    trace: FixtureRoleTrace | None = None

    def lane(run: CoordinatorRun) -> tuple[native_cutoff.FixedWindowsCutoff, CaptureRoles]:
        nonlocal observation, trace
        fixed, roles = native.coordinator_objects(
            run.packet, run.store, CaptureWindow(cap.intake_ms, cap.cleanup_ms), run.refs,
        )
        if context.mode == "normal":
            trace = FixtureRoleTrace(roles)
            return fixed, trace
        observation = witness = CutoffObservation(context, fixed)
        original_stop = fixed.stop_due
        original_signal = roles.signal_all
        released = Event()
        observed = Thread(target=witness.follow_spawn, args=(cap.intake_ms,), daemon=True)
        observed.start()

        def independently_stop() -> native_cutoff.CutoffReceipt:
            try:
                if not witness.done.is_set() or witness.failure:
                    raise Hold("fixture missing pre-cutoff root witnesses")
                prefix: dict[str, object] = {"cutoff": cap.intake_ms, "at": mono(), "roles": witness.sample()}
                proof_deadline = cap.intake_ms + 500
                if context.mode == "no-signal":
                    # Do not call the ordinary watchdog signal. At the same
                    # proof deadline used by the positive, both roots must live.
                    while mono() < proof_deadline:
                        time.sleep(0.005)
                    still_live = witness.sample()
                    write_marker(context.root, "disabled-cutoff.json", {
                        "at": mono(), "proof_deadline": proof_deadline, "roles": still_live,
                    })
                    assert still_live == [(False, 1), (False, 1)]
                    signal_at = mono()
                    assert fixed._supervisor is not None and fixed._root is not None
                    signal_host = bool(fixed._native.TerminateJobObject(fixed._supervisor, 1))
                    fixed.roles.signal_both()
                    assert signal_host
                    assert fixed._native.WaitForSingleObject(fixed._root, max(0, cap.cleanup_ms - mono())) == 0
                    states = witness.await_stopped(cap.cleanup_ms)
                    write_marker(context.root, "cutoff-result.json", prefix | {
                        "signal_at": signal_at, "confirmed_at": mono(), "stopped": states,
                        "independent_proof": False, "supervisor_root_confirmed": True,
                    })
                    return native_cutoff.CutoffReceipt(False, False, False)
                signal_at = mono()
                # Exercise an unknown production supervisor-root receipt while
                # retaining the fixture-owned original for teardown observation.
                supervisor_root = fixed._root
                if context.mode == "missing-root":
                    fixed._root = None
                try:
                    receipt = original_stop()
                finally:
                    if context.mode == "missing-root":
                        fixed._root = supervisor_root
                states = witness.await_stopped(proof_deadline if context.mode == "stall" else cap.cleanup_ms)
                supervisor_cleaned = receipt.supervisor_root_exited
                if context.mode == "missing-root":
                    assert supervisor_root is not None
                    supervisor_cleaned = fixed._native.WaitForSingleObject(
                        supervisor_root, max(0, cap.cleanup_ms - mono()),
                    ) == 0
                    assert supervisor_cleaned and receipt.supervisor_job_empty
                write_marker(context.root, "cutoff-result.json", prefix | {
                    "signal_at": signal_at, "confirmed_at": mono(), "stopped": states,
                    "independent_proof": context.mode == "stall",
                    "supervisor_root_confirmed": receipt.supervisor_root_exited,
                    "fixture_supervisor_exit": supervisor_cleaned,
                })
                return receipt
            finally:
                released.set()

        def no_early_role_lane_signal() -> None:
            # At the shared cutoff, the primary coordinator watchdog owns stop,
            # rather than counting an ordinary launch-lane failure as its proof.
            if not released.wait(max(0.0, (cap.cleanup_ms - mono()) / 1000)):
                raise Hold("fixture stop witness unavailable")
            original_signal()

        fixed.stop_due = independently_stop  # type: ignore[method-assign]
        roles.signal_all = no_early_role_lane_signal  # type: ignore[method-assign]
        return fixed, roles

    try:
        disposition = owned_entry(ledger.descriptor, mono, context.wall, context.evidence(), context.exact, lane)
        status = None
        with suppress(Hold, OSError, ValueError):
            status = open_existing_capture(context.packet).status()
        write_marker(context.root, "coordinator-result.json", {
            "outcome": disposition, "at": mono(),
            "fixed_role_stages": trace.stages if trace is not None else [],
            "durable_status": status,
        })
        return 0
    finally:
        if observation is not None:
            observation.close()


def main() -> int:
    if (
        sys.platform != "win32" or not sys.flags.isolated or len(sys.argv) != 4
        or sys.argv[1] not in {"coordinator", "supervisor"}
    ):
        return 2
    root = Path(sys.argv[2])
    try:
        context = FixtureContext.load(root, sys.argv[3], Path(sys.executable).resolve(strict=True))
        return coordinator(context) if sys.argv[1] == "coordinator" else supervisor(context)
    except (Hold, OSError, ValueError, KeyboardInterrupt) as exc:
        with suppress(Hold, OSError, ValueError):
            write_marker(root, sys.argv[1] + "-held.json", {"type": type(exc).__name__})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
