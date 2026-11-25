"""Exercise native fixture marker reads with inert file and clock doubles."""

import time
from pathlib import Path

import pytest
import t02_event_native_fixture as fixture


@pytest.mark.parametrize("name", ["tree.json", "owned.json", "release.json"])
def test_fixed_marker_recovers_under_original_deadline(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def read(path: Path, *, encoding: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("private diagnostic")
        return "fixture marker"

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(fixture, "_ms", iter([0, 10, 11]).__next__)
    assert fixture._wait_file(Path(name), 12) == "fixture marker"
    assert calls == 2


@pytest.mark.parametrize(("mode", "expected"), [
    ("permanent", "owner-release: deadline [(]open-denied[)]"),
    ("late", "owner-release: deadline [(]late-read[)]"),
    ("unexpected", "unknown native fixture marker"),
    ("io", "owner-release: read-error"),
])
def test_marker_failure_is_bounded_and_sanitized(
    mode: str, expected: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read(path: Path, *, encoding: str) -> str:
        if mode == "unexpected":
            pytest.fail("unexpected marker must not be opened")
        if mode == "permanent":
            raise PermissionError("private diagnostic")
        if mode == "io":
            raise OSError("private diagnostic")
        return "late content"

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(fixture, "_ms", iter([0, 10]).__next__)
    with pytest.raises(RuntimeError, match=expected) as error:
        fixture._wait_file(Path("unknown.json" if mode == "unexpected" else "release.json"), 10)
    assert "private" not in str(error.value)
