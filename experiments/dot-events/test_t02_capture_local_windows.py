"""Offline security and binding checks for the dormant Windows Git observer."""

import io
import subprocess
from pathlib import Path

import pytest
from t02_capture_local_windows import _project_git, verify_checkout
from t02_event_types import Hold

HEAD = "a" * 40
PIN = "0" * 64
ORIGIN = "https://github.com/craigholland/lighthouse.git"


class Fixture:
    """Supply only synthetic host, artifact and Git facts."""

    def __init__(self, root: Path) -> None:
        self.checkout = root / "checkout"
        self.checkout.mkdir()
        self.git = root / "git.exe"
        self.now = 101
        self.host = "fixture-host"
        self.digest = PIN
        self.calls: list[tuple[str, ...]] = []
        self.status = b""
        self.config = b"remote.origin.url\n" + ORIGIN.encode() + b"\0"
        self.entry = b"100644 " + HEAD.encode() + b" 0\tREADME.md\0"
        self.flags = b"H README.md\0"
        self.final = HEAD.encode() + b"\n"
        self.expire = False

    def runner(self, argv: tuple[str, ...], *, cwd: Path, env: dict[str, str],
               timeout: float) -> bytes:
        assert argv[0] == str(self.git)
        assert cwd == self.checkout
        assert set(env) <= {
            "SYSTEMROOT", "WINDIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
            "GIT_ATTR_NOSYSTEM", "GIT_OPTIONAL_LOCKS", "GIT_NO_REPLACE_OBJECTS",
            "GIT_TERMINAL_PROMPT", "GIT_DIR", "GIT_WORK_TREE", "GIT_NO_LAZY_FETCH",
        }
        assert "core.fsmonitor=false" in argv and "core.hooksPath=NUL" in argv
        assert 0 < timeout <= 0.8
        args = argv[9:]
        self.calls.append(args)
        if args[0] == "config":
            assert args == ("config", "--local", "--no-includes", "--null", "--list")
            if self.expire:
                self.now = 901
            return self.config
        if args == ("rev-parse", "--verify", "HEAD^{commit}"):
            return self.final if self.calls.count(args) > 1 else HEAD.encode() + b"\n"
        if args == ("ls-files", "--stage", "-z"):
            return self.entry
        if args == ("ls-files", "-v", "-z"):
            return self.flags
        if args == ("status", "--porcelain=v1", "-z", "--untracked-files=no",
                    "--ignore-submodules=all"):
            return self.status
        raise AssertionError("unexpected Git invocation")

    def project(self) -> tuple[str, str, bool]:
        return verify_checkout(
            self.checkout, HEAD, expected_checkout=self.checkout, expected_host="fixture-host",
            expected_origin=ORIGIN, git_executable=self.git, git_sha256=PIN,
            deadline_ms=901, clock=lambda: self.now, host_name=lambda: self.host,
            canonical=lambda path, directory: str(path), digest=lambda *_: self.digest,
            runner=self.runner,
        )


def test_exact_projection_and_dirty_tracked_result(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    assert fixture.project() == ("craigholland/lighthouse", HEAD, True)
    fixture.calls.clear()
    fixture.status = b" M README.md\0"
    assert fixture.project() == ("craigholland/lighthouse", HEAD, False)


@pytest.mark.parametrize(("field", "value"), [
    ("host", "wrong-host"), ("digest", "1" * 64),
    ("config", b"remote.origin.url\nhttps://github.com/wrong/project.git\0"),
    ("config", b"remote.origin.url\n" + ORIGIN.encode() + b"\0filter.external.clean\nno\0"),
    ("config", b"remote.origin.url\n" + ORIGIN.encode() + b"\0include.path\nother\0"),
    ("entry", b"160000 " + HEAD.encode() + b" 0\tfake-submodule\0"),
    ("entry", b"120000 " + HEAD.encode() + b" 0\tfake-link\0"),
    ("entry", b"100644 " + HEAD.encode() + b" 0\t../outside\0"),
    ("flags", b"h README.md\0"), ("flags", b"S README.md\0"),
    ("final", b"b" * 40 + b"\n"), ("expire", True),
])
def test_fail_closed_synthetic_boundaries(tmp_path: Path, field: str, value: object) -> None:
    fixture = Fixture(tmp_path)
    setattr(fixture, field, value)
    with pytest.raises(Hold):
        fixture.project()
    if field in {"host", "digest"}:
        assert not fixture.calls
    if field in {"config", "expire"}:
        assert len(fixture.calls) == 1
    if field in {"entry", "flags"}:
        assert not any(args[0] == "status" for args in fixture.calls)


def test_runner_times_out_and_terminates_only_owned_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(b"bounded synthetic reply")
            self.killed = False
            self.waits: list[float] = []

        def wait(self, *, timeout: float) -> int:
            self.waits.append(timeout)
            raise subprocess.TimeoutExpired("synthetic", timeout)

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

    process = Process()

    def spawn(argv: tuple[str, ...], **kwargs: object) -> Process:
        assert argv == ("fixture-git.exe", "status")
        assert kwargs["shell"] is False
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(Hold, match="shutdown unconfirmed"):
        _project_git(("fixture-git.exe", "status"), cwd=tmp_path, env={}, timeout=0.01)
    assert process.killed and len(process.waits) == 2
    assert all(0 <= wait <= 0.01 for wait in process.waits)
