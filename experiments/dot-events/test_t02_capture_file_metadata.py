"""Exercise access-time drift and preserve all stable metadata checks."""

import hashlib
import os
from pathlib import Path
from typing import cast

import pytest
import t02_capture_local_windows as local
import t02_capture_operator as operator
import t02_capture_roles as roles
from t02_capture_file_metadata import changed_stable_fields
from t02_event_types import Hold
from test_t02_capture_roles import _fixture


def _changed(observation: os.stat_result, **updates: int | float | None) -> os.stat_result:
    class ChangedObservation:
        def __getattr__(self, name: str) -> object:
            return updates[name] if name in updates else getattr(observation, name)

    return cast(os.stat_result, ChangedObservation())


def test_only_access_fields_are_ignored(tmp_path: Path) -> None:
    source = tmp_path / "fixture"
    source.write_bytes(b"inert")
    before = source.stat()
    assert not changed_stable_fields(before, _changed(
        before, st_atime=1, st_atime_ns=1,
    ))
    fields = {name for name in dir(os.stat_result) if name.startswith("st_")}
    for field in sorted(fields - {"st_atime", "st_atime_ns"}):
        observed = getattr(before, field)
        candidate = _changed(before, **{field: 1 if observed != 1 else 2})
        assert changed_stable_fields(before, candidate) == (field,)


@pytest.mark.parametrize("stable_change", [False, True])
def test_packet_and_secret_open_descriptor_comparisons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stable_change: bool,
) -> None:
    accepted, _ = _fixture(tmp_path)
    packet_path = tmp_path / "packet"
    packet_path.write_bytes(accepted.packet.canonical)
    (tmp_path / "loopback-bearer").write_bytes(b"q" * 32)
    stat_opened = os.fstat

    def fstat(fd: int) -> os.stat_result:
        observed = stat_opened(fd)
        if stable_change:
            return _changed(observed, st_mtime_ns=observed.st_mtime_ns + 1)
        return _changed(observed, st_atime=1, st_atime_ns=1)

    monkeypatch.setattr(os, "fstat", fstat)
    if stable_change:
        with pytest.raises(Hold, match="read held"):
            operator.read_packet(packet_path)
        with pytest.raises(Hold, match="private input held"):
            roles._read_capture_secret(accepted.packet, "loopback_bearer", lambda: 0, 50)
    else:
        assert operator.read_packet(packet_path) == accepted.packet
        assert roles._read_capture_secret(accepted.packet, "loopback_bearer", lambda: 0, 50) == "q" * 32


@pytest.mark.parametrize("stable_change", [False, True])
def test_digest_path_reobservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stable_change: bool,
) -> None:
    artifact = tmp_path / "inert-artifact"
    data = b"Offline artifact fixture."
    artifact.write_bytes(data)
    real_stat = Path.stat
    reads = 0

    def stat_path(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        nonlocal reads
        original = real_stat(path, follow_symlinks=follow_symlinks)
        if path != artifact or not follow_symlinks:
            return original
        reads += 1
        if reads < 2:
            return original
        if stable_change:
            return _changed(original, st_mtime_ns=original.st_mtime_ns + 1)
        return _changed(original, st_atime=1, st_atime_ns=1)

    monkeypatch.setattr(Path, "stat", stat_path)
    if stable_change:
        with pytest.raises(Hold, match="artifact inspection held"):
            local._digest(artifact, lambda: 0, 50)
    else:
        assert local._digest(artifact, lambda: 0, 50) == hashlib.sha256(data).hexdigest()



def test_cross_view_legacy_ctime_is_tightly_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import t02_capture_file_metadata as metadata

    monkeypatch.setattr(metadata, "platform_name", "nt")
    source = tmp_path / "fixture"
    source.touch()
    before = _changed(source.stat(), st_birthtime=100.0, st_birthtime_ns=100, st_ctime=100.0, st_ctime_ns=100)
    after = _changed(before, st_ctime=101.0, st_ctime_ns=101)
    assert changed_stable_fields(before, after) == ("st_ctime", "st_ctime_ns")
    assert not changed_stable_fields(before, after, path_to_descriptor=True)
    no_birth = _changed(before, st_birthtime=None, st_birthtime_ns=None)
    assert "st_ctime_ns" in changed_stable_fields(no_birth, after, path_to_descriptor=True)
    different_birth = _changed(after, st_birthtime_ns=102)
    assert changed_stable_fields(before, different_birth, path_to_descriptor=True) == ("st_birthtime_ns",)
    bad_path_alias = _changed(before, st_ctime_ns=103)
    assert "st_ctime_ns" in changed_stable_fields(bad_path_alias, after, path_to_descriptor=True)



def test_operator_exposes_only_safe_metadata_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    accepted, _ = _fixture(tmp_path)
    private_path = tmp_path / "private-synthetic-filename"
    private_path.write_bytes(accepted.packet.canonical)
    stat_opened = os.fstat

    def fstat(fd: int) -> os.stat_result:
        observed = stat_opened(fd)
        return _changed(observed, st_mtime_ns=observed.st_mtime_ns + 1)

    monkeypatch.setattr(os, "fstat", fstat)
    assert operator.main(["--status", "--packet", str(private_path)]) == 1
    assert capsys.readouterr().err == "Held: Private capture packet read held at open: st_mtime_ns.\n"
