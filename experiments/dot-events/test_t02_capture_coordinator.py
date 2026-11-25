"""Full fixed coordinator offer-to-receipt proof using no real process or provider."""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
import t02_capture_coordinator_windows as native
from t02_capture_bootstrap import InheritedCapture
from t02_capture_composition import open_existing_capture
from t02_capture_coordinator import (
    CoordinatorRun,
    accept_offer,
    make_offer,
    make_receipt,
    run_coordinator,
    verify_receipt,
)
from t02_capture_evidence import PREFIX, SCOPE, CaptureEvidence
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeHandles
from t02_event_types import Hold, encode
from test_t02_capture_evidence import ACTIVATION, Provider
from test_t02_capture_lifecycle import record


def source(packet: CapturePacket, fake: Provider) -> CaptureEvidence:
    fake.expected_deadline = packet.intake_cutoff_ms
    for ref in (1, 2):
        fake.records[f"/issues/comments/{ref}"]["body"] = PREFIX + encode({
            "head": packet.approval.head, "digest": packet.approval.digest, "scope": SCOPE,
            "not_before": ACTIVATION, "expires": packet.approval.cutoff_ms,
        }).decode()
    return CaptureEvidence(fake, lambda: fake.now)


@pytest.mark.parametrize(("stalled", "cutoff_error"), [(False, False), (True, False), (True, True)])
def test_dispatch_reaches_independent_coordinator_via_exact_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stalled: bool, cutoff_error: bool,
) -> None:
    packet = CapturePacket.parse(encode(record() | {"state": str(tmp_path / "coordinator.db")}))
    state = open_existing_capture(packet)
    state.prepare()
    state.claim(lambda: ACTIVATION)
    fake = Provider()
    evidence = source(packet, fake)
    local = Mock(return_value=True)
    host, pipes, outer, child = Mock(), Mock(), Mock(), Mock()
    host.start_bootstrap.return_value = True
    host.confirmed_quiescent.return_value = True
    pipes.prepare.return_value = CapturePipeHandles((1, 2, 3), (11, 12, 13))
    pending, response = bytearray(), bytearray()
    out: list[str] = []
    originals = Mock()
    if cutoff_error:
        originals.stop_due.side_effect = Hold("synthetic unconfirmed native shutdown")
    tick = 0
    descriptor = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100),
                                  packet.approval.head, packet.approval.digest)
    outer.write.side_effect = lambda chunk, _deadline: pending.extend(chunk)
    child.write.side_effect = lambda chunk, _deadline: response.extend(chunk)

    def take(wire: bytearray, count: int) -> bytes:
        result = bytes(wire[:min(count, 23)])
        del wire[:len(result)]
        return result

    child.read.side_effect = lambda count, _deadline: take(pending, count)

    def wait(event: Event, deadline: int) -> bool:
        nonlocal tick
        assert deadline == 50
        if stalled:
            assert not event.is_set()
            tick = deadline
        return event.is_set()

    def start(action: Callable[[], None]) -> None:
        out.append("start-lane")
        if not stalled:
            action()

    def maker(run: CoordinatorRun) -> native.FixedCoordinatorLane:
        assert run.descriptor == descriptor and run.refs == (1, 2)
        fake_roles = Mock()

        def arm(cleanup: int) -> None:
            assert cleanup == 100 and run.store.status() == ("claimed", "new")
            assert out == ["allocated-local-originals", "start-lane"]
            out.append("armed")
            run.store.reserve_handoff(lambda: ACTIVATION, require_coordinator=True)

        def signal() -> None:
            run.store.stop()
            run.store.finish_cleanup(confirmed=True)

        def allocate() -> tuple[Mock, Mock]:
            out.append("allocated-local-originals")
            assert fake.calls == 4
            return originals, fake_roles

        fake_roles.arm.side_effect = arm
        fake_roles.signal_all.side_effect = signal
        fake_roles.confirmed_stopped.return_value = True
        return native.FixedCoordinatorLane(run, lambda: tick, allocate, lambda: True)

    def incoming(count: int, _deadline: int) -> bytes:
        if not response:
            host.start_bootstrap.assert_called_once_with(descriptor)
            outcome = run_coordinator(descriptor, child, lambda: tick, lambda: fake.now, evidence, local,
                                      maker, wait, start)
            assert outcome == ("cleanup-unknown" if stalled else "held")
        return take(response, count)

    outer.read.side_effect = incoming
    monkeypatch.setattr(native, "WindowsCapturePipe", Mock(return_value=outer))
    outcome = native.dispatch_owned(packet, state, (1, 2), 50, 100, lambda: tick, host, pipes, "a" * 64)
    assert outcome == ("cleanup-unknown" if stalled else "held")
    assert state.status()[0] == ("cleanup-unknown" if stalled else "stopped")
    if stalled:
        originals.stop_due.assert_called_once_with()
        assert out == ["allocated-local-originals", "start-lane"]
    else:
        originals.stop_due.assert_not_called()
    host.confirmed_quiescent.assert_called_once_with(100)
    pipes.close.assert_called_once_with()


def test_offer_changed_head_cannot_reach_local_and_replay_cannot_rearm(tmp_path: Path) -> None:
    packet = CapturePacket.parse(encode(record() | {"state": str(tmp_path / "replay.db")}))
    state = open_existing_capture(packet)
    state.prepare()
    state.claim(lambda: ACTIVATION)
    gate = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100),
                             packet.approval.head, packet.approval.digest)
    offer = make_offer(gate, packet, (1, 2), state)
    assert verify_receipt(gate, make_receipt(gate, "held"), state) == "cleanup-unknown"
    with pytest.raises(Hold):
        verify_receipt(gate, offer, state)
    fake = Provider()
    check = source(packet, fake)
    local = Mock(return_value=True)
    fake.records["/pulls/15"]["head"] = {"sha": "f" * 40}
    with pytest.raises(Hold, match="authority held"):
        accept_offer(gate, offer, lambda: 0, lambda: fake.now, check, local)
    local.assert_not_called()
    fake.records["/pulls/15"]["head"] = {"sha": packet.approval.head}
    assert accept_offer(gate, offer, lambda: 0, lambda: fake.now, check, local).refs == (1, 2)
    with pytest.raises(Hold, match="already consumed"):
        accept_offer(gate, offer, lambda: 0, lambda: fake.now, check, local)
