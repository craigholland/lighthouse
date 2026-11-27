"""Real Windows ownership test, only fixed isolated Python children."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from t02_event_native_fixture import _api, _ms, _publish, _wait_file, witness

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows containment")

@pytest.mark.parametrize("case", ["explicit", "owner-loss", "owner-loss-negative"])
def test_native_t02_same_owner_root_and_descendant(tmp_path: Path, case: str) -> None:
    directory = tmp_path / ("native-t02-" + case)
    directory.mkdir()
    fixture = Path(__file__).with_name("t02_event_native_fixture.py").resolve()
    # -I excludes the script path; add only this tracked fixture's directory.
    launch = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
              "runpy.run_path(sys.argv.pop(1),run_name='__main__')")
    k = _api()
    environment = {"SystemRoot": os.environ["SystemRoot"]}
    supervisor = subprocess.Popen(
        [getattr(sys, "_base_executable", sys.executable), "-I", "-c", launch, str(fixture.parent), str(fixture), "owner", str(directory), case],
        env=environment, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    began = _ms()
    deadline = began + 20_000
    handles: list[int] = []
    try:
        root_pid, leaf_pid = json.loads(_wait_file(directory / "owned.json", deadline - 6000))
        handles.append(witness(k, root_pid))
        handles.append(witness(k, leaf_pid))
        assert len(set(handles)) == 2
        assert all(k.WaitForSingleObject(handle, 0) == 258 for handle in handles)
        _publish(directory / "release.json", "release")
        assert supervisor.wait(timeout=max(0.01, (deadline - _ms()) / 1000)) == 0
        # The owner must go away well ahead of fixture self-expiry. Only
        # termination in this strictly shorter causal window can qualify.
        assert _ms() - began < 12_000
        causal = _ms() + 2_000
        outcomes = [k.WaitForSingleObject(handle, max(0, causal - _ms())) for handle in handles]
        assert not (directory / "fixture-natural-cleanup.json").exists()
        if case == "owner-loss-negative":
            assert outcomes == [258, 258]  # The exact same proof rejects these live witnesses.
            _publish(directory / "fixture-cleanup.json", True)
            assert all(k.WaitForSingleObject(handle, max(0, deadline - _ms())) == 0 for handle in handles)
            assert (directory / "fixture-natural-cleanup.json").is_file()
            print("native owner-loss negative: containment rejected; fixture cleanup witnessed")
        else:
            assert outcomes == [0, 0]
            print(f"native {case}: root and descendant witness confirmed in {_ms() - began} ms")
    finally:
        if supervisor.poll() is None:
            supervisor.kill()  # This exact owned supervisor only; kill-on-close contains its job.
            supervisor.wait(timeout=3)
        try:
            if handles and not (directory / "fixture-cleanup.json").exists():
                _publish(directory / "fixture-cleanup.json", True)
            limit = _ms() + 3000
            assert all(k.WaitForSingleObject(handle, max(0, limit - _ms())) == 0 for handle in handles)
        finally:
            for handle in handles:
                k.CloseHandle(handle)
