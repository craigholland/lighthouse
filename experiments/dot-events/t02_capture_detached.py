"""Detached outer watchdog for an owned supervisor Job and its original cutoff."""

from collections.abc import Callable
from typing import Protocol

from t02_capture_supervisor import TerminalOwner
from t02_event_types import Hold


class OwnedHost(Protocol):
    def signal(self) -> None: ...
    def confirm_exact_stop(self, deadline_ms: int) -> bool: ...


def watch_owned_supervisor(
    host: OwnedHost,
    terminal: TerminalOwner,
    stop_roles: Callable[[], None],
    wait_until_stop_or_cutoff: Callable[[int], None],
    exact_role_receipts: Callable[[], bool],
    clock: Callable[[], int],
    intake: int,
    cleanup: int,
) -> str:
    """Run outside the controller and supervisor; never create or replace a role."""
    if not clock() < intake < cleanup:
        raise Hold("capture detached deadline held")
    try:
        wait_until_stop_or_cutoff(intake)
    except (Hold, OSError, KeyboardInterrupt):
        pass
    signals = True
    try:
        stop_roles()
    except (Hold, OSError):
        signals = False
    try:
        host.signal()
    except (Hold, OSError):
        signals = False
    try:
        sealed = terminal.seal()
    except (Hold, OSError):
        sealed = False
    try:
        host_stopped = host.confirm_exact_stop(cleanup)
        receipts = exact_role_receipts()
    except (Hold, OSError):
        host_stopped = receipts = False
    confirmed = signals and sealed and host_stopped and receipts and clock() < cleanup
    if sealed:
        try:
            if not terminal.finish(confirmed):
                confirmed = False
        except (Hold, OSError):
            confirmed = False
    return "confirmed" if confirmed and clock() < cleanup else "cleanup-unknown"
