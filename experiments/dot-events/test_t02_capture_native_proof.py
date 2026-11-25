"""Opt-in Windows witness test; starts only two fixed harmless stand-ins."""

import os
import sys
import threading
import time
from pathlib import Path

import pytest
from t02_capture_role_handles import CaptureRoleWitness
from t02_event_windows import _OwnedWindowsJob

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("LIGHTHOUSE_T02_CAPTURE_NATIVE_PROOF") != "1",
    reason="explicitly selected native capture proof only",
)


def now() -> int:
    return time.monotonic_ns() // 1_000_000


@pytest.mark.parametrize("signal_enabled", [True, False], ids=["stalled-positive", "disabled-negative"])
def test_two_exact_standins(signal_enabled: bool) -> None:
    python = Path(getattr(sys, "_base_executable", sys.executable)).resolve(strict=True)
    assert python.name.casefold() == "python.exe"
    roles: list[_OwnedWindowsJob] = []
    owned: list[CaptureRoleWitness] = []
    results: list[bool] = []
    watchdog: threading.Thread | None = None
    try:
        setup_deadline = now() + 3000
        for _ in range(2):
            role = _OwnedWindowsJob(now)
            roles.append(role)
            assert role._start_owned(python, ["-I", "-c", "import time; time.sleep(12)"], {},
                                     setup_deadline, bind_at_creation=True)
            owned.append(CaptureRoleWitness(role, now))
        assert owned[0]._root != owned[1]._root
        assert all(w._kernel.WaitForSingleObject(w._root, 0) == 258 for w in owned)
        deadline = now() + 1200

        def independently_observe() -> None:
            if signal_enabled:
                for witness in owned:
                    witness.signal()
                results.extend(witness.confirm_exact_stop(deadline) for witness in owned)

        watchdog = threading.Thread(target=independently_observe)
        watchdog.start()
        # No work on the controller thread until the fixed causal window closes.
        threading.Event().wait(max(0, deadline - now()) / 1000)
        watchdog.join(0.25)
        assert not watchdog.is_alive()
        if signal_enabled:
            assert results == [True, True]  # exact roots and empty Jobs
        else:
            assert not results
            assert all(w._kernel.WaitForSingleObject(w._root, 0) == 258 for w in owned)
            separate_cleanup = now() + 1200
            for witness in owned:
                witness.signal()
            assert all(w.confirm_exact_stop(separate_cleanup) for w in owned)
    finally:
        cleanup = now() + 2000
        if watchdog is not None:
            watchdog.join(0.25)
        confirmed = []
        for witness in owned:
            try:
                witness.signal()
                confirmed.append(witness.confirm_exact_stop(cleanup))
            finally:
                witness.close()
        for role in roles:
            role.request_stop(cleanup)
            role.confirmed_quiescent(cleanup)
        assert all(confirmed)
