"""Exercise inherited bootstrap and separate listener lifecycle with fake I/O."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_roles as roles
from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_detached import watch_owned_supervisor
from t02_capture_listener import listen_bound
from t02_capture_local_windows import observe_local_capture
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_terminal import CaptureTerminalOwner
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_gate import ARCHIVE_SHA256
from t02_event_types import Hold, encode
from test_t02_capture_evidence import ACTIVATION
from test_t02_capture_lifecycle import record


def state(tmp_path: Path) -> tuple[InheritedCapture, CapturePacket, CaptureStore]:
    packet = CapturePacket.parse(encode(record()))
    descriptor = InheritedCapture(PeerBinding((11, 12, 13), "b" * 64, 50, 100),
                                  packet.approval.head, packet.approval.digest)
    store = CaptureStore(tmp_path / "store.db",
                         CaptureBinding(packet.approval.head, packet.proof_id,
                                        packet.principal, ACTIVATION, ACTIVATION + 50),
                         operation_digest=packet.approval.digest)
    store.prepare()
    return descriptor, packet, store


def test_exact_descriptor_requires_inherited_capabilities_and_original_window(tmp_path: Path) -> None:
    descriptor, _, _ = state(tmp_path)
    raw = descriptor.to_environment()[ENVIRONMENT_KEY]
    owns_pipe = Mock(side_effect=lambda handle: handle in (11, 12))
    owns_stop = Mock(side_effect=lambda handle: handle == 13)
    assert InheritedCapture.accept(raw, lambda: 0, owns_pipe, owns_stop) == descriptor
    assert [call.args[0] for call in owns_pipe.call_args_list] == [11, 12]
    owns_stop.assert_called_once_with(13)
    with pytest.raises(Hold):
        InheritedCapture.accept(raw, lambda: 50, owns_pipe, owns_stop)
    with pytest.raises(Hold):
        InheritedCapture.accept(raw, lambda: 0, owns_pipe, Mock(return_value=False))


def test_fixed_listener_helper_loads_only_after_claims_and_uses_separate_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor, packet, store = state(tmp_path)
    factory = Mock()
    monkeypatch.setattr(roles, "fixed_capture_listener", factory)
    bearer, wait = Mock(return_value="S" * 32), Mock(return_value=True)
    with pytest.raises(Hold):
        listen_bound(descriptor, packet, store, bearer, wait, lambda: 0, lambda: ACTIVATION)
    bearer.assert_not_called()
    store.claim(lambda: ACTIVATION)
    factory.return_value.start.return_value = True
    factory.return_value.confirmed_quiescent.return_value = True
    assert listen_bound(descriptor, packet, store, bearer, wait, lambda: 0, lambda: ACTIVATION) == "stopped"
    wait.assert_called_once_with(13, 50)
    factory.return_value.request_stop.assert_called_once_with(100)
    factory.return_value.confirmed_quiescent.assert_called_once_with(100)
    assert store.status()[0] == "claimed"  # Detached terminal owner is separate.


def test_detached_owner_seals_and_cannot_substitute_host_exit_for_role_receipts(tmp_path: Path) -> None:
    _, _, store = state(tmp_path)
    store.claim(lambda: ACTIVATION)
    terminal = CaptureTerminalOwner(store)
    host = Mock()
    host.confirm_exact_stop.return_value = True
    stop_roles, wait = Mock(), Mock()
    result = watch_owned_supervisor(host, terminal, stop_roles, wait, lambda: False, lambda: 0, 50, 100)
    assert result == "cleanup-unknown" and store.status()[0] == "cleanup-unknown"
    wait.assert_called_once_with(50)
    stop_roles.assert_called_once_with()
    host.signal.assert_called_once_with()
    host.confirm_exact_stop.assert_called_once_with(100)


def test_local_observer_never_hashes_secret_paths() -> None:
    packet = CapturePacket.parse(encode(record()))
    canonical = Mock(side_effect=lambda path, **_: str(path))
    hash_file = Mock(side_effect=(ARCHIVE_SHA256, "e" * 64))
    observe = observe_local_capture(
        packet, lambda: str(record()["host"]),
        lambda root, deadline: ("craigholland/lighthouse", packet.approval.head, True),
        lambda: 0, 100, canonical=canonical, digest=hash_file,
    )
    assert observe.tracked_clean and canonical.call_count == 6
    assert [call.args[0] for call in hash_file.call_args_list] == [
        Path(str(record()["runtime_archive"])), Path(str(record()["runtime_executable"])),
    ]
