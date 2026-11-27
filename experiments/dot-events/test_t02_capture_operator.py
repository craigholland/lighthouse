"""Operator selectors and inert store behavior; never open a real provider."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_operator as operator
from t02_capture_packet import CapturePacket
from t02_event_types import encode
from test_t02_capture_lifecycle import record

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows canonical packet paths")


def packet_at(tmp_path: Path, *, changes: dict[str, object] | None = None) -> tuple[Path, Path]:
    packet_path = tmp_path / "packet.json"
    state_path = tmp_path / "one-use.db"
    raw = record() | {"state": str(state_path)} | (changes or {})
    packet_path.write_bytes(CapturePacket.parse(encode(raw)).canonical)
    return packet_path, state_path


@pytest.mark.parametrize("arguments", [
    ["--execute"], ["--execute", "--packet", r"C:\unopened\private.json", "--owner-comment", "1"],
    ["--execute", "--packet", r"C:\unopened\private.json", "--owner-comment", "2", "--lead-comment", "1"],
    ["--execute", "--packet", r"C:\unopened\private.json", "--owner-comment", "1", "--lead-comment", "02"],
    ["--prepare", "--status"], ["--status", "--packet", r"C:\unopened\private.json", "--owner-comment", "1"],
    ["--dry-run", "--packet", r"C:\unopened\private.json"], ["--exec", "PRIVATE-ARGUMENT"],
    ["--prepare", "--packet", r"C:\unopened\private.json", "--packet", r"C:\unused\second.json"],
])
def test_malformed_selectors_precede_packet_or_composition(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    forbidden = Mock(side_effect=AssertionError("must not reach packet reader or execution"))
    monkeypatch.setattr(operator, "read_packet", forbidden)
    assert operator.main(arguments, execute=forbidden) == 2
    forbidden.assert_not_called()
    captured = capsys.readouterr()
    assert "unopened" not in captured.err and "PRIVATE-ARGUMENT" not in captured.err


def test_default_help_dry_and_complete_real_execute_remain_inert(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    forbidden = Mock(side_effect=AssertionError("must not reach packet reader"))
    monkeypatch.setattr(operator, "read_packet", forbidden)
    assert operator.main([]) == operator.main(["--dry-run"]) == 0
    with pytest.raises(SystemExit) as help_exit:
        operator.main(["--help"])
    assert help_exit.value.code == 0
    assert operator.main(["--execute", "--packet", r"C:\unopened\private.json",
                          "--owner-comment", "1", "--lead-comment", "2"]) == 2
    forbidden.assert_not_called()
    capture = capsys.readouterr()
    assert "Synthetic offline" in capture.out and "execution is disabled" in capture.err


def test_prepare_verifies_read_only_status_never_resets_or_discloses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    packet, state = packet_at(tmp_path)
    assert operator.main(["--status", "--packet", str(packet)]) == 1
    assert not state.exists()
    assert operator.main(["--prepare", "--packet", str(packet)]) == 0
    first = state.read_bytes()
    assert operator.main(["--prepare", "--packet", str(packet)]) == 1
    assert operator.main(["--status", "--packet", str(packet)]) == 0
    assert state.read_bytes() == first
    assert "prepared; candidate disposition: new" in capsys.readouterr().out
    other, _ = packet_at(tmp_path, changes={"operation_id": "foreign-operation"})
    assert operator.main(["--status", "--packet", str(other)]) == 1
    assert state.read_bytes() == first
    state.write_bytes(b"foreign-corrupt SQLite substitute")
    assert operator.main(["--status", "--packet", str(other)]) == 1
    assert state.read_bytes() == b"foreign-corrupt SQLite substitute"
    capture = capsys.readouterr()
    assert "foreign" not in capture.out + capture.err
    assert str(tmp_path) not in capture.out + capture.err


def test_exact_execute_delegates_once_and_does_not_create_a_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    packet, state = packet_at(tmp_path)
    calls: list[tuple[CapturePacket, int, int]] = []

    def deny(bound: CapturePacket, owner: int, lead: int) -> str:
        calls.append((bound, owner, lead))
        return "denied"

    args = ["--execute", "--packet", str(packet), "--owner-comment", "1", "--lead-comment", "2"]
    assert operator.main(args, execute=deny) == 1
    assert calls == [(operator.read_packet(packet), 1, 2)]
    assert not state.exists()
    packet.write_bytes(b"x" * 8193)
    assert operator.main(args, execute=deny) == 1
    assert len(calls) == 1 and not state.exists()
    assert "private capture operation not confirmed" in capsys.readouterr().err


def test_status_reports_only_disposition_not_stored_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    packet, state = packet_at(tmp_path)
    assert operator.main(["--prepare", "--packet", str(packet)]) == 0
    admitted = operator.read_packet(packet)
    store = operator.capture_store(admitted)
    store.claim(lambda: admitted.approval.activation_ms)
    store.capture("https://synthetic.example/opaque-candidate", lambda: admitted.approval.activation_ms)
    store.stop()
    store.finish_cleanup(confirmed=True)
    expected = state.read_bytes()
    assert operator.main(["--status", "--packet", str(packet)]) == 0
    assert state.read_bytes() == expected
    capture = capsys.readouterr()
    assert "stopped; candidate disposition: captured" in capture.out
    assert "synthetic.example" not in capture.out + capture.err
