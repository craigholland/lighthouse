"""Read versioned local TOML as inert, provider-neutral policy data."""

from __future__ import annotations

import json
import ntpath
import re
import tomllib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import cast

_TABLE = dict[str, object]
_MAX_BYTES = 64 * 1024


class ConfigurationError(ValueError):
    """Invalid configuration; messages contain fixed schema labels only."""


@dataclass(frozen=True)
class ServiceSettings:
    """The supported shared safeguards; version 1 cannot disable them."""

    max_active_work: int = 1
    independent_review: bool = True
    human_merge: bool = True


@dataclass(frozen=True)
class Actors:
    """Distinct numeric source-control accounts, not presentation names."""

    owner: int
    lead: int
    implementer: int


@dataclass(frozen=True)
class Labels:
    """Labels corresponding to the fixed intake and priority vocabulary."""

    ready: str = "lighthouse:ready"
    blocked: str = "lighthouse:blocked"
    high: str = "lighthouse:priority:high"
    normal: str = "lighthouse:priority:normal"
    low: str = "lighthouse:priority:low"


@dataclass(frozen=True, repr=False)
class Verification:
    """Repository-relative directory and required commands, never executed here."""

    directory: str
    commands: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class ProjectProfile:
    """One inactive project profile; no client, secret or workspace is opened."""

    project: str
    repository: str
    adapter: str
    integration: str
    release: str
    actors: Actors
    implementation_workspace: PureWindowsPath
    review_workspace: PureWindowsPath
    credential_ref: str
    labels: Labels
    verification: Verification


@dataclass(frozen=True, repr=False)
class Configuration:
    """Validated shared settings and uniquely registered projects."""

    service: ServiceSettings
    projects: tuple[ProjectProfile, ...]


def profile_fingerprint(service: ServiceSettings, profile: ProjectProfile) -> str:
    """Identify the parsed policy captured at admission, not the TOML path or slug."""
    values = asdict(profile)
    values["implementation_workspace"] = profile.implementation_workspace.as_posix()
    values["review_workspace"] = profile.review_workspace.as_posix()
    canonical = json.dumps(
        {"format": "lighthouse-profile-v1", "service": asdict(service), "project": values},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    )
    return sha256(canonical.encode("ascii")).hexdigest()


def _read(path: Path) -> _TABLE:
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) <= _MAX_BYTES:
            return tomllib.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        pass
    raise ConfigurationError("Unable to read versioned TOML.")


def _schema(table: _TABLE, label: str, required: Iterable[str], optional: Iterable[str] = ()) -> None:
    mandatory = set(required)
    if not mandatory <= table.keys() <= mandatory.union(optional):
        raise ConfigurationError(f"Invalid fields in {label}.")


def _table(source: _TABLE, key: str) -> _TABLE:
    value = source[key]
    if not isinstance(value, dict):
        raise ConfigurationError(f"Expected a table for {key}.")
    return cast(_TABLE, value)


def _text(value: object, label: str, pattern: str | None = None) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or (pattern is not None and not re.fullmatch(pattern, value, flags=re.ASCII))
    ):
        raise ConfigurationError(f"Invalid value for {label}.")
    return value


def _version(data: _TABLE) -> None:
    value = data["version"]
    if type(value) is not int or value != 1:
        raise ConfigurationError("Unsupported configuration version.")


def _service(data: _TABLE) -> ServiceSettings:
    _schema(data, "service", ("version",), ("max_active_work", "independent_review", "human_merge"))
    _version(data)
    limit = data.get("max_active_work", 1)
    if (
        type(limit) is not int or limit != 1 or data.get("independent_review", True) is not True
        or data.get("human_merge", True) is not True
    ):
        raise ConfigurationError("Unsupported service safety policy.")
    return ServiceSettings()


def _actors(data: _TABLE) -> Actors:
    _schema(data, "actors", ("owner", "lead", "implementer"))
    owner, lead, implementer = (data[key] for key in ("owner", "lead", "implementer"))
    if (
        type(owner) is not int or type(lead) is not int or type(implementer) is not int
        or min(owner, lead, implementer) <= 0 or len({owner, lead, implementer}) != 3
    ):
        raise ConfigurationError("Expected three distinct positive numeric actors.")
    return Actors(owner, lead, implementer)


def _workspace(value: object) -> PureWindowsPath:
    raw = _text(value, "workspace")
    separator = '\\'
    drive, tail = ntpath.splitdrive(raw.replace("/", separator))
    if not re.fullmatch("[A-Za-z]:", drive) or not tail.startswith(separator):
        raise ConfigurationError("Workspace must be a drive-absolute Windows path.")
    if any(
        (part not in (".", "..") and part.endswith((" ", ".")))
        or any(c in part for c in ':*?"<>|')
        for part in tail.split(separator)
    ):
        raise ConfigurationError("Workspace contains an unsupported path segment.")
    path = PureWindowsPath(ntpath.normpath(raw))
    if path == PureWindowsPath(path.anchor):
        raise ConfigurationError("Workspace cannot be a drive root.")
    return path


def _branches(data: _TABLE) -> tuple[str, str]:
    _schema(data, "branches", (), ("integration", "release"))
    pattern = r"[A-Za-z0-9_][A-Za-z0-9_./-]*"
    integration = _text(data.get("integration", "development"), "integration branch", pattern)
    release = _text(data.get("release", "main"), "release branch", pattern)
    if integration.casefold() == release.casefold() or any(
        ".." in branch or any(
            not part or part.startswith(".") or part.endswith((".", ".lock")) for part in branch.split("/")
        ) for branch in (integration, release)
    ):
        raise ConfigurationError("Expected distinct valid branch names.")
    return integration, release


def _labels(data: _TABLE) -> Labels:
    keys = ("ready", "blocked", "high", "normal", "low")
    _schema(data, "labels", (), keys)
    defaults = Labels()
    names = tuple(_text(data.get(key, getattr(defaults, key)), "label") for key in keys)
    if len(set(map(str.casefold, names))) != len(keys):
        raise ConfigurationError("Label mappings must be distinct.")
    return Labels(*names)


def _verification(data: _TABLE) -> Verification:
    _schema(data, "verification", ("directory", "commands"))
    directory = _text(data["directory"], "verification directory")
    path = PureWindowsPath(directory)
    if path.anchor or ".." in path.parts or ":" in directory:
        raise ConfigurationError("Verification directory must be repository-relative.")
    commands = data["commands"]
    if not isinstance(commands, list) or not commands:
        raise ConfigurationError("At least one verification command is required.")
    return Verification(directory, tuple(_text(command, "verification command") for command in commands))


def _profile(data: _TABLE) -> ProjectProfile:
    _schema(data, "project", (
        "version", "project", "repository", "adapter", "actors", "workspaces", "credential_ref", "verification",
    ), ("branches", "labels", "active"))
    _version(data)
    if data["adapter"] != "github" or data.get("active", False) is not False:
        raise ConfigurationError("Unsupported adapter or activation policy.")
    project = _text(data["project"], "project", r"[a-z0-9][a-z0-9-]*")
    repository = _text(data["repository"], "repository", r"[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*")
    integration, release = _branches(_table(data, "branches") if "branches" in data else {})
    workspaces = _table(data, "workspaces")
    _schema(workspaces, "workspaces", ("implementation", "review"))
    return ProjectProfile(
        project, repository, "github", integration, release, _actors(_table(data, "actors")),
        _workspace(workspaces["implementation"]), _workspace(workspaces["review"]),
        _text(data["credential_ref"], "credential reference", r"ref:[A-Za-z][A-Za-z0-9_.-]{0,63}"),
        _labels(_table(data, "labels") if "labels" in data else {}),
        _verification(_table(data, "verification")),
    )


def load_configuration(service: Path, projects: Iterable[Path]) -> Configuration:
    """Read only explicit TOML files, then validate registrations and isolation."""
    settings = _service(_read(service))
    profiles: list[ProjectProfile] = []
    project_ids: set[str] = set()
    repositories: set[str] = set()
    workspaces: list[PureWindowsPath] = []
    for path in projects:
        profile = _profile(_read(path))
        repo = profile.repository.casefold()
        if profile.project in project_ids or repo in repositories:
            raise ConfigurationError("Duplicate project or repository registration.")
        project_ids.add(profile.project)
        repositories.add(repo)
        for workspace in (profile.implementation_workspace, profile.review_workspace):
            if any(workspace.is_relative_to(other) or other.is_relative_to(workspace) for other in workspaces):
                raise ConfigurationError("Project workspaces overlap.")
            workspaces.append(workspace)
        profiles.append(profile)
    return Configuration(settings, tuple(profiles))
