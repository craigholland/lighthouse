"""Offline entry-to-lifecycle checks with disposable state and synthetic effects."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from t02_capture_composition import (
    CaptureWindow,
    SelectedCapture,
    execute_capture,
    open_existing_capture,
    run_selected_capture,
)
from t02_capture_evidence import PREFIX, SCOPE, CaptureEvidence
from t02_capture_packet import CapturePacket
from t02_event_types import encode
from test_t02_capture_evidence import ACTIVATION, Provider
from test_t02_capture_lifecycle import Roles, local_observation, record


def test_selected_lifecycle_requires_approval_local_state_and_one_terminal_owner(tmp_path: Path) -> None:
    packet = CapturePacket.parse(encode(record() | {"state": str(tmp_path / "selected.db")}))
    store = open_existing_capture(packet)
    store.prepare()
    reference = local_observation(packet)
    original = replace(reference, canonical_non_reparse_files=(
        *reference.canonical_non_reparse_files[:-1], str(store.path),
    ))
    fake = Provider()
    fake.expected_deadline = packet.intake_cutoff_ms
    for ref in (1, 2):
        fake.records[f"/issues/comments/{ref}"]["body"] = PREFIX + encode({
            "head": packet.approval.head, "digest": packet.approval.digest, "scope": SCOPE,
            "not_before": ACTIVATION, "expires": packet.approval.cutoff_ms,
        }).decode()
    local = Mock(return_value=original)
    connect = Mock()
    role = connect.return_value
    trace: list[str] = []

    def connect_once(p: CapturePacket, state: object, window: CaptureWindow, refs: tuple[int, int]) -> object:
        assert p == packet and refs == (1, 2) and window == CaptureWindow(50, 100)
        assert getattr(state, "status")() == ("claimed", "new")
        trace.append("connect-after-claim")
        return role

    connect.side_effect = connect_once
    role.arm.side_effect = lambda deadline: trace.append(f"arm-{deadline}")
    role.start_listener.side_effect = lambda deadline: trace.append(f"listener-{deadline}")
    role.start_runtime.side_effect = lambda deadline: trace.append(f"runtime-{deadline}")
    role.wait_candidate.side_effect = Roles(store, "ok").wait_candidate

    def stop() -> None:
        trace.append("stop")
        store.stop()
        store.finish_cleanup(confirmed=True)

    role.signal_all.side_effect = stop
    role.confirmed_stopped.return_value = True
    selected = SelectedCapture(lambda: fake.now, lambda: 0, CaptureEvidence(fake, lambda: fake.now), local, connect)
    assert execute_capture(packet, 1, 2) == "denied"
    assert run_selected_capture(packet, 2, 1, selected) == "denied"
    local.assert_not_called()
    connect.assert_not_called()
    local.return_value = replace(original, tracked_clean=False)
    assert run_selected_capture(packet, 1, 2, selected) == "denied"
    connect.assert_not_called()
    local.return_value = original
    assert run_selected_capture(packet, 1, 2, selected) == "candidate-held"
    assert trace == ["connect-after-claim", "arm-100", "listener-50", "runtime-50", "stop"]
    assert store.status() == ("stopped", "captured")
    assert run_selected_capture(packet, 1, 2, selected) == "admission-unknown"
    assert connect.call_count == 1
