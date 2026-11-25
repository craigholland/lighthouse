"""Internal fixed helper composition behind the disabled operator entry."""

from collections.abc import Callable

from t02_capture_bootstrap import InheritedCapture
from t02_capture_evidence import CaptureEvidence
from t02_capture_handoff import AcceptedHandoff, read_handoff, receive_handoff
from t02_capture_native_peer import run_native_peer
from t02_capture_supervisor import CaptureSupervisor, HostedRole, HostStatus
from t02_capture_terminal import CaptureTerminalOwner
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_evidence import PublicGitHub
from t02_event_https import GitHubHttps
from t02_event_types import Hold


class _ApprovalBoundRole:
    """Refresh source-derived authority immediately before an actual role attempt."""

    def __init__(self, role: HostedRole, authorize: Callable[[], bool]) -> None:
        self._role = role
        self._authorize = authorize

    def request_start(self, deadline: int) -> bool:
        return self._authorize() and self._role.request_start(deadline)

    def signal(self) -> None:
        self._role.signal()

    def confirm_exact_stop(self, deadline_ms: int) -> bool:
        return self._role.confirm_exact_stop(deadline_ms)


def run_transferred_supervisor(
    raw_descriptor: str,
    mono: Callable[[], int],
    wall: Callable[[], int],
    owns_pipe: Callable[[int], bool],
    owns_stop: Callable[[int], bool],
    owns_exact_jobs: Callable[[tuple[int, int]], bool],
    listener_factory: Callable[[AcceptedHandoff, int], HostedRole],
    runtime_factory: Callable[[AcceptedHandoff, int], HostedRole],
    *, provider: PublicGitHub | None = None,
) -> HostStatus:
    """Read the authenticated inherited channel; admit both Jobs before role effects.

    This topology leaves terminal writing with the detached owner, not the
    listener or controller. Direct helper and public activation remain denied.
    """
    descriptor = InheritedCapture.accept(raw_descriptor, mono, owns_pipe, owns_stop)
    pipe = WindowsCapturePipe(*descriptor.peer.handles, mono)
    wire = read_handoff(pipe, descriptor.peer.intake_ms, mono)
    evidence = CaptureEvidence(GitHubHttps(wall) if provider is None else provider, wall)
    accepted = receive_handoff(descriptor, wire, mono, wall, owns_exact_jobs, evidence=evidence)
    if not descriptor.verifies_packet_window(accepted.packet, mono, wall):
        raise Hold("capture owner handoff expired")
    listener = listener_factory(accepted, accepted.jobs[0])
    if not descriptor.verifies_packet_window(accepted.packet, mono, wall):
        raise Hold("capture listener construction crossed cutoff")
    runtime = runtime_factory(accepted, accepted.jobs[1])

    def authorize_start() -> bool:
        return (
            descriptor.verifies_packet_window(accepted.packet, mono, wall)
            and evidence.allows(accepted.packet.approval, *accepted.approval_refs,
                                before_ms=descriptor.approval_deadline(accepted.packet, mono, wall))
            and descriptor.verifies_packet_window(accepted.packet, mono, wall)
        )

    host = CaptureSupervisor(
        mono, descriptor.peer.intake_ms, descriptor.peer.cleanup_ms,
        _ApprovalBoundRole(listener, authorize_start), _ApprovalBoundRole(runtime, authorize_start),
        CaptureTerminalOwner(accepted.store),
    )
    return run_native_peer(descriptor.peer, host, mono)
