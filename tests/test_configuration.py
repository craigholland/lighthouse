"""Exercise the offline TOML boundary using only synthetic data."""

from pathlib import Path, PureWindowsPath

import pytest

from lighthouse.configuration import ConfigurationError, load_configuration

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "config/examples/service.toml").read_text(encoding="utf-8")
ALPHA = (ROOT / "profiles/examples/alpha.toml").read_text(encoding="utf-8")
BETA = (ROOT / "profiles/examples/beta.toml").read_text(encoding="utf-8")


def save(directory: Path, name: str, data: str) -> Path:
    path = directory / name
    path.write_text(data, encoding="utf-8")
    return path


def test_examples_share_one_configuration_boundary() -> None:
    result = load_configuration(
        ROOT / "config/examples/service.toml",
        (ROOT / "profiles/examples/alpha.toml", ROOT / "profiles/examples/beta.toml"),
    )
    assert result.service.max_active_work == 1
    assert result.service.independent_review and result.service.human_merge
    alpha, beta = result.projects
    assert (alpha.project, beta.project) == ("alpha", "beta")
    assert alpha.repository == "example-org/alpha"
    assert alpha.adapter == "github"
    assert alpha.integration == "development" and beta.release == "main"
    assert (alpha.actors.owner, alpha.actors.lead, alpha.actors.implementer) == (101, 102, 103)
    assert beta.labels.normal == "lighthouse:priority:normal"
    assert alpha.implementation_workspace == PureWindowsPath("X:/synthetic/alpha/implementation")
    assert alpha.credential_ref == "ref:alpha-scm"
    assert alpha.verification.commands == ("python -m pytest -q tests",)
    assert "ref:alpha" not in repr(alpha) and "synthetic" not in repr(result)


@pytest.mark.parametrize(("before", "after"), [
    ("version = 1", "version = 2"),
    ("version = 1", "version = true"),
    ("active = false", "active = true"),
    ("active = false", 'extra = "private-diagnostic-sentinel"'),
    ('adapter = "github"', 'adapter = "other"'),
    ("lead = 102", "lead = 101"),
    ("lead = 102", "lead = true"),
    ('ref:alpha-scm', 'private-diagnostic-sentinel'),
    ('commands = ["python -m pytest -q tests"]', "commands = []"),
    ('commands = ["python -m pytest -q tests"]', ""),
    ('directory = "."', 'directory = "../outside"'),
    ("X:/synthetic/alpha/review", "x:/Synthetic/ALPHA/temp/../implementation"),
    ("X:/synthetic/alpha/review", "x:/synthetic/alpha/implementation/nested"),
    ("X:/synthetic/alpha/review", "X:synthetic/alpha/review"),
    ("X:/synthetic/alpha/review", "X:/synthetic/alpha/review."),
])
def test_invalid_profile_never_echoes_values(tmp_path: Path, before: str, after: str) -> None:
    service = save(tmp_path, "service", SERVICE)
    profile = save(tmp_path, "project", ALPHA.replace(before, after))
    with pytest.raises(ConfigurationError) as failure:
        load_configuration(service, (profile,))
    assert "private-diagnostic-sentinel" not in str(failure.value)
    assert str(tmp_path) not in str(failure.value)


@pytest.mark.parametrize("change", (
    "max_active_work = 2", "max_active_work = true", "independent_review = false",
    "human_merge = false", "automatic_merge = true",
))
def test_unapproved_service_policy_is_rejected(tmp_path: Path, change: str) -> None:
    key = change.split(" ", 1)[0]
    body = chr(10).join(line for line in SERVICE.splitlines() if not line.startswith(key + " "))
    service = save(tmp_path, "service", body + chr(10) + change)
    with pytest.raises(ConfigurationError):
        load_configuration(service, ())


@pytest.mark.parametrize(("before", "after"), [
    ('project = "beta"', 'project = "alpha"'),
    ("example-org/beta", "Example-Org/ALPHA"),
    ("X:/synthetic/beta/review", "x:/synthetic/alpha/implementation/sub"),
])
def test_duplicate_or_overlapping_registration(tmp_path: Path, before: str, after: str) -> None:
    service = save(tmp_path, "service", SERVICE)
    alpha = save(tmp_path, "alpha", ALPHA)
    beta = save(tmp_path, "beta", BETA.replace(before, after))
    with pytest.raises(ConfigurationError):
        load_configuration(service, (alpha, beta))


def test_toml_and_file_errors_do_not_disclose_context(tmp_path: Path) -> None:
    bad = save(tmp_path, "private-diagnostic-sentinel", '[private-diagnostic-sentinel')
    for candidate in (bad, tmp_path / "missing-private-diagnostic-sentinel"):
        with pytest.raises(ConfigurationError, match=r"^Unable to read versioned TOML[.]$"):
            load_configuration(candidate, ())


def test_commands_remain_data_and_workspaces_are_not_created(tmp_path: Path) -> None:
    service = save(tmp_path, "service", "version = 1")
    command = "echo inert-not-executed > marker"
    profile = save(tmp_path, "project", ALPHA.replace("python -m pytest -q tests", command))
    result = load_configuration(service, (profile,))
    assert result.projects[0].verification.commands == (command,)
    assert not (tmp_path / "marker").exists()


def test_custom_label_and_branch_mappings(tmp_path: Path) -> None:
    service = save(tmp_path, "service", SERVICE)
    extra = chr(10).join(("", "[labels]", 'ready = "sample:ready"', "[branches]", 'integration = "next"'))
    result = load_configuration(service, (save(tmp_path, "project", ALPHA + extra),))
    profile = result.projects[0]
    assert profile.labels.ready == "sample:ready" and profile.labels.blocked == "lighthouse:blocked"
    assert profile.integration == "next" and profile.release == "main"
