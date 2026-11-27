"""Opt-in detached Windows proof using only an offline Python fixture."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("LIGHTHOUSE_T02_CAPTURE_DETACHED_PROOF") != "1",
    reason="explicitly selected detached capture proof only",
)


def now() -> int:
    return time.monotonic_ns() // 1_000_000


@pytest.mark.parametrize("signal_enabled", [True, False], ids=["stalled-positive", "disabled-negative"])
def test_detached_exact_role_cessation(tmp_path: Path, signal_enabled: bool) -> None:
    fixture = Path(__file__).with_name("t02_capture_detached_fixture.py").resolve(strict=True)
    python = Path(getattr(sys, "_base_executable", sys.executable)).resolve(strict=True)
    assert python.name.casefold() == "python.exe"
    gui = python.with_name("pythonw.exe").resolve(strict=True)
    assert gui.parent == python.parent and gui.name.casefold() == "pythonw.exe"
    control = tmp_path / "detached-fixture"
    control.mkdir()
    with subprocess.Popen(
        [str(gui), "-I", "-S", str(fixture), "signal" if signal_enabled else "disable"],
        cwd=control, env={"SystemRoot": os.environ["SystemRoot"]},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ) as watchdog:
        try:
            assert watchdog.pid != os.getpid()
            ready_by = now() + 7000
            while not (control / "armed.json").is_file():
                if watchdog.poll() is not None:
                    _, errors = watchdog.communicate(timeout=3)
                    pytest.fail(errors.decode(errors="replace"))
                assert now() < ready_by
                time.sleep(0.01)
            entered = now()
            pending = control / "stall.pending"
            pending.write_text(json.dumps({"entered": entered, "awaiting_startup_ack": True}), encoding="utf-8")
            pending.rename(control / "stall.json")
            # Stall in startup awaiting a deliberately unsignaled synthetic acknowledgment.
            startup_ack = threading.Event()
            assert not startup_ack.wait(4)
            resumed = now()
            _, errors = watchdog.communicate(timeout=3)
            assert watchdog.returncode == 0, errors.decode(errors="replace")
            receipt = json.loads((control / "witness.json").read_text(encoding="utf-8"))
        finally:
            if watchdog.poll() is None:
                watchdog.kill()
                watchdog.wait(timeout=3)

    assert receipt["entered"] == entered
    assert receipt["startup_cutoff"] == entered + 800
    assert receipt["cutoff"] == entered + 2000
    assert receipt["cutoff"] <= receipt["at_cutoff_at"] < resumed
    assert receipt["at_startup"] == [[False, 1], [False, 1]]
    if signal_enabled:
        assert receipt["startup_cutoff"] <= receipt["signal_at"] <= receipt["before_at"] < receipt["cutoff"]
        assert receipt["before_cutoff"] == receipt["at_cutoff"] == [[True, 0], [True, 0]]
        assert receipt["cleanup"] is None and receipt["cleanup_at"] is None
    else:
        assert receipt["before_cutoff"] is None and receipt["before_at"] is None
        assert receipt["signal_at"] is None
        assert receipt["at_cutoff"] == [[False, 1], [False, 1]]
        assert receipt["at_cutoff_at"] <= receipt["cleanup_at"] < resumed
        assert receipt["cleanup"] == [[True, 0], [True, 0]]


    before_at = receipt["before_at"]
    cleanup_at = receipt["cleanup_at"]
    print(
        f"detached signal={signal_enabled} startup={receipt['at_startup']} "
        f"exact_stop_ms={None if before_at is None else before_at - entered} "
        f"cutoff_ms={receipt['at_cutoff_at'] - entered} cutoff_state={receipt['at_cutoff']} "
        f"negative_cleanup_ms={None if cleanup_at is None else cleanup_at - entered} "
        f"cleanup_state={receipt['cleanup']} controller_resumed_ms={resumed - entered}",
    )
