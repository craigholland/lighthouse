"""One fixed private capture-only installation profile; no activation or installer side effects."""

from __future__ import annotations

import os
import platform
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from t02_capture_file_metadata import require_stable_metadata
from t02_capture_local_windows import _canonical
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_event_types import Hold, decode, encode

if TYPE_CHECKING:
    from t02_capture_native_composition import InstalledCapture
    from t02_capture_trusted import Role, TrustedInheritedCapabilities

_LIMIT = 8192
_SCOPE = "lighthouse-t02-callback-capture-only"
_SOURCE = "craigholland/lighthouse"
_ROLES = ("coordinator", "supervisor", "listener")
_NAME = ".lighthouse-t02-capture-v1.json"


@dataclass(frozen=True, repr=False)
class CaptureInstallation:
    host: str
    checkout: Path
    release: str
    git: Path
    git_sha256: str
    python: Path
    python_sha256: str
    archive: Path
    archive_sha256: str
    runtime: Path
    runtime_sha256: str

    @classmethod
    def parse(cls, wire: bytes, checkout: Path, host: str) -> CaptureInstallation:
        data = decode(wire, _LIMIT)
        fixed = {
            "version": 1, "scope": _SCOPE, "repository": _SOURCE, "roles": list(_ROLES),
            "checkout": str(checkout), "host": host,
        }
        if (type(data.get("version")) is not int or any(data.get(k) != v for k, v in fixed.items())
            or not checkout.is_absolute() or not host or not host.isascii() or len(host) > 255):
            raise Hold("capture installation target held")
        fields = ("release", "git", "git_sha256", "python", "python_sha256",
                  "archive", "archive_sha256", "runtime", "runtime_sha256")
        if set(data) != {"version", "scope", "repository", "roles", "checkout", "host", *fields}:
            raise Hold("capture installation fields held")

        def text(key: str) -> str:
            value = data[key]
            if not isinstance(value, str) or not value or not value.isascii() or len(value) > 1024:
                raise Hold("capture installation value held")
            return value

        def path(key: str, name: str | None = None) -> Path:
            value = text(key)
            selected = Path(value)
            if (not selected.is_absolute() or str(selected) != value or ".." in selected.parts
                or (name is not None and selected.name.casefold() != name)):
                raise Hold("capture installation path held")
            return selected

        def digest(key: str, width: int) -> str:
            value = text(key)
            if re.fullmatch("[0-9a-f]{" + str(width) + "}", value) is None:
                raise Hold("capture installation digest held")
            return value

        result = cls(
            host, checkout, digest("release", 40), path("git", "git.exe"), digest("git_sha256", 64),
            path("python", "python.exe"), digest("python_sha256", 64), path("archive"),
            digest("archive_sha256", 64), path("runtime"), digest("runtime_sha256", 64),
        )
        if len({result.git, result.python, result.archive, result.runtime}) != 4:
            raise Hold("capture installation files must be distinct")
        return result

    def matches(self, packet: CapturePacket) -> bool:
        fields = decode(packet.canonical, MAX_PACKET_BYTES)
        return (
            packet.approval.head == self.release and fields.get("host") == self.host
            and fields.get("repository") == _SOURCE and fields.get("checkout") == str(self.checkout)
            and fields.get("runtime_archive") == str(self.archive)
            and fields.get("runtime_archive_sha256") == self.archive_sha256
            and fields.get("runtime_executable") == str(self.runtime)
            and fields.get("runtime_executable_sha256") == self.runtime_sha256
        )


def profile_location(checkout: Path) -> Path:
    """Derive a fixed sibling destination; never accept a caller-selected profile."""
    if not checkout.is_absolute() or checkout.parent == checkout:
        raise Hold("capture installation checkout held")
    return checkout.parent / _NAME


def installation_plan(wire: bytes, checkout: Path, host: str) -> tuple[Path, bytes]:
    """Validate an offline installation proposal without writing or enabling it."""
    CaptureInstallation.parse(wire, checkout, host)
    return profile_location(checkout), encode(decode(wire, _LIMIT))


def disable_plan(checkout: Path) -> tuple[Path, Path]:
    """Plan only: move the exact declared profile aside without changing an active run."""
    active = profile_location(checkout)
    return active, active.with_name(active.name + ".disabled")


def _read_profile(path: Path) -> bytes:
    _canonical(path, directory=False)
    before = path.stat()
    if not 0 < before.st_size <= _LIMIT:
        raise Hold("capture installation size held")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        require_stable_metadata(before, opened, "capture installation open held", path_to_descriptor=True)
        wire = stream.read(_LIMIT + 1)
        require_stable_metadata(opened, os.fstat(stream.fileno()), "capture installation read held")
    require_stable_metadata(before, path.stat(), "capture installation path held")
    if len(wire) != before.st_size or _canonical(path, directory=False) != str(path):
        raise Hold("capture installation changed")
    return wire


def assemble_installation(
    profile: CaptureInstallation, executable: Path, role: Role | None,
    *, bound_child: Callable[[Role, Callable[[], int]], tuple[TrustedInheritedCapabilities, str]],
    clocks: tuple[Callable[[], int], Callable[[], int]] | None = None,
) -> InstalledCapture:
    """Compose the fixed per-role factory from only an already validated profile."""
    from t02_capture_native_composition import (
        InstalledCapture,
        ReviewedHost,
        mono,
        wall,
    )
    from t02_capture_windows_ownership import WindowsCaptureOwnership

    if executable != profile.python or _canonical(profile.python, directory=False) != str(profile.python):
        raise Hold("capture installation interpreter held")
    host = ReviewedHost(profile.host, profile.checkout, profile.git, profile.git_sha256,
                        profile.python, profile.python_sha256, profile.matches)
    if role is None:
        return InstalledCapture(host, None)
    tick, time = clocks or (mono, wall)
    ledger, _ = bound_child(role, tick)
    if ledger.role != role or ledger.descriptor.head != profile.release:
        raise Hold("capture installation child release held")
    return InstalledCapture(host, WindowsCaptureOwnership(profile.python, time, tick, ledger))


def select_installation(role: Role | None = None) -> InstalledCapture | None:
    """Resolve only on explicitly guarded execution, never import or help."""
    if sys.platform != "win32":
        return None
    from t02_capture_bootstrap import ENVIRONMENT_KEY
    from t02_capture_trusted import CHILD_LEDGER, read_child_binding

    if role is not None and (not os.environ.get(ENVIRONMENT_KEY) or not os.environ.get(CHILD_LEDGER)):
        return None
    try:
        checkout = Path(__file__).resolve(strict=True).parents[2]
        profile = CaptureInstallation.parse(_read_profile(profile_location(checkout)), checkout, platform.node())
        return assemble_installation(profile, Path(sys.executable), role, bound_child=read_child_binding)
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        return None
