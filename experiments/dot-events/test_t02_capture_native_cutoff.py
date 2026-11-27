"""Fake Win32 proof of cutoff dispatch while the fixed launch lane is blocked."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_native_cutoff as cutoff
import t02_capture_owned_jobs as jobs
from t02_capture_bootstrap import InheritedCapture
from t02_capture_peer import PeerBinding
from t02_event_types import Hold


def test_cutoff_owns_its_jobs_even_during_a_stalled_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = Mock()
    kernel.CreateJobObjectW.side_effect = [20, 21, 22]
    kernel.SetInformationJobObject.return_value = True
    kernel.TerminateJobObject.return_value = True
    kernel.QueryInformationJobObject.return_value = True
    monkeypatch.setattr(cutoff, "_kernel", lambda: kernel)
    monkeypatch.setattr(jobs, "_kernel", lambda: kernel)
    tick = 0
    owner = cutoff.FixedWindowsCutoff(tmp_path / "python.exe", lambda: tick)
    owner.allocate_supervisor(50, 100)
    owner.roles.allocate(50)
    exact = owner.roles.inherited(lambda handle: handle + 10, 50)
    descriptor = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100), "b" * 40, "c" * 64)
    with pytest.raises(Hold, match="not due"):
        owner.stop_due()
    with pytest.raises(Hold, match="start held"):
        owner.start_fixed(descriptor, (31, 33), lambda value: value + 20)

    def stalled(
        actual: InheritedCapture, passed: tuple[int, int], job: int, registrar: Callable[[int, int], None],
    ) -> bool:
        nonlocal tick
        assert (actual, passed, job) == (descriptor, exact, 40)
        tick = 50
        # No exact root was returned by the stalled native creation call.
        result = owner.stop_due()
        assert result == cutoff.CutoffReceipt(False, True, True)
        assert [call.args[0] for call in kernel.TerminateJobObject.call_args_list] == [20, 21, 22]
        kernel.WaitForSingleObject.assert_not_called()
        with pytest.raises(Hold, match="handoff held"):
            registrar(job, 70)
        return False

    launch = Mock(side_effect=stalled)
    monkeypatch.setattr(owner.host, "start_owned_transfer", launch)
    assert not owner.start_fixed(descriptor, exact, lambda value: value + 20)
    launch.assert_called_once()
    with pytest.raises(Hold, match="start held"):
        owner.start_fixed(descriptor, exact, lambda value: value + 20)
    owner.close()
