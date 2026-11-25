"""Verify ownership state and cutoff using only fixed fake role endpoints."""

from dataclasses import dataclass
from unittest.mock import Mock

from t02_capture_host_channel import CaptureHostedRoles
from t02_capture_supervisor import CaptureSupervisor, Command, HostStatus


@dataclass
class Clock:
    now: int = 0

    def read(self) -> int:
        return self.now


@dataclass
class FakeRole:
    name: str
    trace: list[str]
    clock: Clock
    late: bool = False

    def request_start(self, deadline: int) -> bool:
        assert deadline == 20
        self.trace.append("start-" + self.name)
        if self.late:
            self.clock.now = deadline
        return True

    def signal(self) -> None:
        self.trace.append("signal-" + self.name)

    def confirm_exact_stop(self, deadline_ms: int) -> bool:
        assert deadline_ms == 30
        self.trace.append("confirm-" + self.name)
        return True


def test_independent_tick_fences_existing_two_roles_without_controller() -> None:
    clk = Clock()
    effects: list[str] = []
    host = CaptureSupervisor(clk.read, 20, 30, FakeRole("listener", effects, clk),
                             FakeRole("runtime", effects, clk))
    assert host.command(Command.LISTENER).phase == "listener-started"
    assert host.command(Command.RUNTIME).phase == "runtime-started"
    clk.now = 20
    status = host.tick()
    assert status.phase == "confirmed" and status.listener_attempted and status.runtime_attempted
    assert host.command(Command.RUNTIME) == status
    assert effects == ["start-listener", "start-runtime", "signal-listener", "signal-runtime",
                       "confirm-listener", "confirm-runtime"]


def test_late_listener_never_starts_runtime_even_if_reported_successful() -> None:
    clk = Clock()
    effects: list[str] = []
    host = CaptureSupervisor(clk.read, 20, 30, FakeRole("listener", effects, clk, late=True),
                             FakeRole("runtime", effects, clk))
    result = host.command(Command.LISTENER)
    assert result.phase == "confirmed" and result.listener_attempted and not result.runtime_attempted
    assert host.command(Command.RUNTIME) == result
    assert effects == ["start-listener", "signal-listener", "signal-runtime",
                       "confirm-listener", "confirm-runtime"]


def test_controller_rejects_terminal_receipt_missing_an_attempted_role() -> None:
    clk = Clock()
    channel = Mock()
    channel.arm.return_value = HostStatus("armed", False, False)
    channel.request.side_effect = [
        HostStatus("listener-started", True, False), HostStatus("runtime-started", True, True),
    ]
    channel.stop_witness.return_value = HostStatus("confirmed", True, False)
    roles = CaptureHostedRoles(channel, 20, 30, clk.read, lambda _: None)
    roles.arm(30)
    roles.start_listener(20)
    roles.start_runtime(20)
    roles.signal_all()
    roles.signal_all()
    channel.signal_stop.assert_called_once_with()
    assert not roles.confirmed_stopped(30)


def test_controller_does_not_ask_host_for_witness_after_original_cutoff() -> None:
    clk = Clock()
    channel = Mock()
    channel.arm.return_value = HostStatus("armed", False, False)
    roles = CaptureHostedRoles(channel, 20, 30, clk.read, lambda _: None)
    roles.arm(30)
    roles.signal_all()
    clk.now = 30
    assert not roles.confirmed_stopped(30)
    channel.stop_witness.assert_not_called()
