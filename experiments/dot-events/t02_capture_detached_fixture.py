"""Fixed offline Windows watchdog and two harmless, non-self-expiring stand-ins."""

import ctypes as c
import json
import sys
import time
from pathlib import Path

# -I discards script-directory imports; bind only the checked-in siblings.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from t02_capture_role_handles import CaptureRoleWitness  # noqa: E402
from t02_event_windows import _Accounting, _OwnedWindowsJob  # noqa: E402

WINDOW_MS = 2000
STARTUP_MS = 800


def now() -> int:
    return time.monotonic_ns() // 1_000_000


def write(name: str, data: object) -> None:
    tmp = Path(name + ".pending")
    with tmp.open("x", encoding="utf-8") as stream:
        json.dump(data, stream)
    tmp.rename(name)


def observe(witness: CaptureRoleWitness) -> tuple[bool, int]:
    kernel = witness._kernel
    accounted = _Accounting()
    state = kernel.WaitForSingleObject(witness._root, 0)
    assert state in (0, 258)
    assert kernel.QueryInformationJobObject(witness._job, 1, c.byref(accounted), c.sizeof(accounted), None)
    return state == 0, int(accounted.active)


def at(cutoff: int) -> None:
    while (remaining := cutoff - now()) > 0:
        time.sleep(remaining / 1000)


def finish(witnesses: list[CaptureRoleWitness], cutoff: int) -> list[tuple[bool, int]]:
    for witness in witnesses:
        witness.signal()
    assert all(witness.confirm_exact_stop(cutoff) for witness in witnesses)
    return [observe(witness) for witness in witnesses]


def main() -> int:
    # No incoming handles, PIDs, executable, packet, or arbitrary arguments.
    if sys.platform != "win32" or not sys.flags.isolated or sys.argv[1:] not in (["signal"], ["disable"]):
        return 2
    # Use the same installed filesystem-backed GUI interpreter, with no console helper.
    standin = Path(sys.executable).resolve(strict=True)
    assert standin.name.casefold() == "pythonw.exe"
    roles: list[_OwnedWindowsJob] = []
    witnesses: list[CaptureRoleWitness] = []
    try:
        setup = now() + 5000
        for _ in range(2):
            role = _OwnedWindowsJob(now)
            roles.append(role)
            assert role._start_owned(
                standin, ["-I", "-S", "-c", "import time\nwhile True: time.sleep(60)"],
                {}, setup, bind_at_creation=True,
            )
            witnesses.append(CaptureRoleWitness(role, now))
        assert len({witness._root for witness in witnesses}) == 2
        assert len({witness._job for witness in witnesses}) == 2
        states = [observe(witness) for witness in witnesses]
        assert states == [(False, 1), (False, 1)], states
        write("armed.json", {"armed": True})
        while not Path("stall.json").is_file():
            assert now() < setup
            time.sleep(0.01)
        marker = json.loads(Path("stall.json").read_text(encoding="utf-8"))
        assert marker["awaiting_startup_ack"] is True
        entered = marker["entered"]
        assert type(entered) is int and 0 <= now() - entered < WINDOW_MS // 2
        cutoff = entered + WINDOW_MS
        states = [observe(witness) for witness in witnesses]
        assert states == [(False, 1), (False, 1)], states
        startup_cutoff = entered + STARTUP_MS
        at(startup_cutoff)
        at_startup = [observe(witness) for witness in witnesses]
        assert at_startup == [(False, 1), (False, 1)], at_startup
        signal_at = None
        if sys.argv[1] == "signal":
            signal_at = now()
            before_cutoff = finish(witnesses, cutoff)
            before_at = now()
            assert before_at < cutoff
        else:
            before_cutoff = None
            before_at = None
        at(cutoff)
        at_cutoff = [observe(witness) for witness in witnesses]
        at_cutoff_at = now()
        if sys.argv[1] == "disable":
            assert at_cutoff == [(False, 1), (False, 1)], at_cutoff
            cleanup = finish(witnesses, now() + WINDOW_MS)
            cleanup_at = now()
        else:
            cleanup = None
            cleanup_at = None
        write("witness.json", {
            "entered": entered, "cutoff": cutoff, "startup_cutoff": startup_cutoff,
            "at_startup": at_startup, "signal_at": signal_at, "before_cutoff": before_cutoff,
            "before_at": before_at, "at_cutoff": at_cutoff, "at_cutoff_at": at_cutoff_at,
            "cleanup": cleanup, "cleanup_at": cleanup_at,
        })
        return 0
    finally:
        for witness in witnesses:
            try:
                witness.signal()
            finally:
                witness.close()
        for role in roles:
            fallback = now() + 2000
            role.request_stop(fallback)
            role.confirmed_quiescent(fallback)


if __name__ == "__main__":
    raise SystemExit(main())
