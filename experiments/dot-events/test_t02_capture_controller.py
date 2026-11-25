"""Selection checks for the fixed transferred supervisor and deadline owner."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_controller as controller
from t02_capture_composition import CaptureWindow, open_existing_capture
from t02_capture_packet import CapturePacket
from t02_capture_private_channel import CaptureHostFrames
from t02_capture_supervisor import CaptureSupervisor
from t02_capture_terminal import CaptureTerminalOwner
from t02_event_types import Hold, encode
from test_t02_capture_evidence import ACTIVATION
from test_t02_capture_lifecycle import record


@pytest.mark.parametrize("owner_ready", [True, False])
def test_independent_owner_arms_before_fixed_supervisor_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner_ready: bool,
) -> None:
    packet = CapturePacket.parse(encode(record() | {"state": str(tmp_path / "controller.db")}))
    store = open_existing_capture(packet)
    store.prepare()
    store.claim(lambda: ACTIVATION)
    calls: list[str] = []
    listen, tunnel = Mock(), Mock()
    def started(kind: str) -> bool:
        calls.append(kind)
        return True

    listen.request_start.side_effect = lambda _: started("listener")
    tunnel.request_start.side_effect = lambda _: started("runtime")
    supervisor = CaptureSupervisor(lambda: 0, 50, 100, listen, tunnel, CaptureTerminalOwner(store))
    frames = CaptureHostFrames(supervisor, "a" * 64, 50, 100, lambda: 0)
    pending = bytearray()
    pipe = Mock()
    pipe.write.side_effect = lambda frame, _: pending.extend(frames.on_frame(frame))

    def get(count: int, _deadline: int) -> bytes:
        value = bytes(pending[:count])
        del pending[:count]
        return value

    pipe.read.side_effect = get
    pipe.signal_stop.side_effect = frames.stop_event
    prepared, host, pipes, jobs, watchdog = Mock(), Mock(), Mock(), Mock(), Mock()
    watchdog.confirmed.return_value = True

    def prepare(*_args: object, **_kwargs: object) -> object:
        assert store.status()[0] == "claimed"
        calls.append("prepare")
        return prepared

    def independent_arm(transfer: object, native_jobs: object, native_host: object) -> None:
        assert (transfer, native_jobs, native_host) == (prepared, jobs, host)
        calls.append("owner-armed")
        if not owner_ready:
            raise Hold("synthetic owner held")

    watchdog.arm_exact.side_effect = independent_arm

    def launch(*_args: object, **kwargs: object) -> object:
        assert kwargs == {"spawn": watchdog.start_fixed}
        assert calls == ["prepare", "owner-armed"]
        calls.append("spawn")
        return pipe

    start = Mock(side_effect=launch)
    monkeypatch.setattr(controller, "prepare_transfer", prepare)
    monkeypatch.setattr(controller, "start_transferred_host", start)
    role = controller.TransferredCaptureRoles(
        packet, store, CaptureWindow(50, 100), (1, 2), lambda: ACTIVATION, lambda: 0,
        pipes, jobs, host, watchdog, lambda h: h, "a" * 64, Mock(),
    )
    if owner_ready:
        role.arm(100)
        role.start_listener(50)
        role.start_runtime(50)
        role.wait_candidate(50)
        assert calls == ["prepare", "owner-armed", "spawn", "listener", "runtime"]
    else:
        with pytest.raises(Hold):
            role.arm(100)
        start.assert_not_called()
    with pytest.raises(Hold, match="not repeatable"):
        role.arm(100)
    role.signal_all()
    watchdog.signal.assert_called_once_with()
    assert role.confirmed_stopped(100) is owner_ready
    pipes.close.assert_called_once_with()
    jobs.close.assert_called_once_with()
    assert store.status()[0] == ("stopped" if owner_ready else "claimed")
