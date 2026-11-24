"""Test the private permission disposition across SDK, child and parent boundaries."""

import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
import sdk_worker
from live import Stage, run
from live_stage import read_signal, run_stage
from supervisor import Role
from test_live import Job, _operator_request
from test_live_stage import _checkout, _verify
from test_sdk_worker import FakeClient


@pytest.mark.parametrize("permission", [True, False])
def test_composed_hold_records_only_permission_attention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permission: bool,
) -> None:
    env, _ = _operator_request(tmp_path)
    roles: list[Stage] = []
    actual_review = sdk_worker.review

    class Client(FakeClient):
        def close(self) -> None:
            if permission:
                [attention] = (tmp_path / "receipt").glob("*/review.attention.json")
                assert read_signal(attention)["reason"] == "permission-request"
            raise OSError("synthetic private provider detail")

    def fake_client(path: Path, _env: dict[str, str], _attention: Callable[[], None]) -> Client:
        return Client(path, "approval" if permission else "runtime")

    monkeypatch.setattr(sdk_worker, "review", partial(actual_review, factory=fake_client))

    class StageJob(Job):
        def start(self, role: Stage, control: Path, environment: dict[str, str]) -> None:
            if role not in (Role.VERIFIER, Role.REVIEW):
                pytest.fail("A held review cannot reach another role")
            self.roles.append(role)
            self.role, self.control = role, control
            if role == Role.REVIEW:
                primary = "permission request" if permission else "runtime does not match"
                with pytest.raises(sdk_worker.ReviewHold, match=primary):
                    run_stage("review", control, env=environment, clock=lambda: 0.0,
                              parent_pid=os.getpid, checkout_call=_checkout)
            else:
                run_stage("verifier", control, env=environment, clock=lambda: 0.0,
                          parent_pid=os.getpid, verify_call=_verify)

        def worker_exited(self) -> bool:
            return True

    assert run(0, command="fixture-command", environ=env, clock=lambda: 0.0,
               sleep=lambda _: None, factory=lambda: StageJob(roles, True)) == 1
    assert roles == [Role.VERIFIER, Role.REVIEW]
    [control] = (tmp_path / "receipt").glob("t01-private-*")
    assert not (control / "review.result.json").exists()
    assert not (control / "review.shutdown.json").exists()
    primary_diagnostic = control / "review.startup.json"
    cleanup_diagnostic = control / "review.cleanup.json"
    startup = read_signal(primary_diagnostic)
    cleanup = read_signal(cleanup_diagnostic)
    assert startup["outcome"] == ("permission_requested" if permission else "initialization_failed")
    assert cleanup["outcome"] == "cleanup_failed"
    assert {k: v for k, v in startup.items() if k != "outcome"} == {
        k: v for k, v in cleanup.items() if k != "outcome"
    }
    assert all("private provider detail" not in path.read_text(encoding="utf-8")
               for path in (primary_diagnostic, cleanup_diagnostic))
    attention = control / "review.attention.json"
    assert attention.exists() == permission
    if permission:
        result = read_signal(attention)
        assert result["reason"] == "permission-request" and result["next_actor"] == "owner"
        assert "private provider detail" not in attention.read_text(encoding="utf-8")
