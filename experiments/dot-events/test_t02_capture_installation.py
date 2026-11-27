"""Exercise the actual dormant install selector using disposable synthetic profile inputs."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_installation as install
from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_peer import PeerBinding
from t02_capture_trusted import (
    CHILD_LEDGER,
    bound_child_environment,
    read_child_binding,
)
from t02_event_types import Hold, encode


def synthetic(checkout: Path) -> dict[str, object]:
    return {
        "version": 1, "scope": "lighthouse-t02-callback-capture-only", "repository": "craigholland/lighthouse",
        "roles": ["coordinator", "supervisor", "listener"], "checkout": str(checkout), "host": "synthetic-host",
        "release": "e" * 40, "git": str(checkout / "git.exe"), "git_sha256": "a" * 64,
        "python": str(checkout / "python.exe"), "python_sha256": "b" * 64,
        "archive": str(checkout / "fixture-archive.zip"), "archive_sha256": "c" * 64,
        "runtime": str(checkout / "inert-runtime.exe"), "runtime_sha256": "d" * 64,
    }


@pytest.mark.parametrize(("field", "value"), [
    ("version", True), ("repository", "different/example"), ("host", "foreign-host"),
    ("roles", ["listener", "supervisor", "coordinator"]), ("release", "not-a-commit"),
    ("python", "python.exe"), ("runtime_sha256", "not-a-sha"),
    ("unexpected", "extra"), ("checkout", "not-the-source"),
])
def test_bad_profile_cannot_be_planned(tmp_path: Path, field: str, value: object) -> None:
    checkout = tmp_path / "checkout"
    with pytest.raises(Hold):
        install.installation_plan(encode(synthetic(checkout) | {field: value}), checkout, "synthetic-host")
    assert not install.profile_location(checkout).exists()


def test_actual_private_reader_and_fixed_profile_plans(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    wire = encode(synthetic(checkout))
    destination, contents = install.installation_plan(wire, checkout, "synthetic-host")
    assert destination == install.profile_location(checkout)
    active, disabled = install.disable_plan(checkout)
    assert active == destination and active.parent == disabled.parent
    assert not active.exists() and not disabled.exists()
    inert = tmp_path / "inert-only.json"
    inert.write_bytes(contents)
    assert install._read_profile(inert) == contents


def test_actual_child_ledger_and_fixed_role_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    python = checkout / "python.exe"
    python.write_bytes(b"no executable fixture effects")
    profile = install.CaptureInstallation.parse(encode(synthetic(checkout)), checkout, "synthetic-host")
    descriptor = InheritedCapture(PeerBinding((11, 12, 13), "d" * 64, 50, 100), "e" * 40, "f" * 64)
    raw = bound_child_environment("supervisor", descriptor, (21, 22))
    for key, value in raw.items():
        monkeypatch.setenv(key, value)
    checks = (lambda h: h in (11, 12), lambda h: h == 13, lambda h: h in (21, 22))
    ledger, _ = read_child_binding("supervisor", lambda: 0, checks=lambda: checks)
    bound = Mock(return_value=(ledger, raw[ENVIRONMENT_KEY]))
    result = install.assemble_installation(profile, python, "supervisor", bound_child=bound)
    assert result.native is not None and result.native.owns_jobs((21, 22))
    assert not result.native.owns_jobs((22, 21))
    with pytest.raises(Hold):
        install.assemble_installation(profile, python, "listener", bound_child=bound)
    assert install.assemble_installation(profile, python, None, bound_child=bound).native is None
    with pytest.raises(Hold):
        install.assemble_installation(profile, checkout / "foreign.exe", None, bound_child=bound)
    monkeypatch.setenv(CHILD_LEDGER, "{}")
    with pytest.raises(Hold):
        read_child_binding("supervisor", lambda: 0, checks=lambda: checks)
