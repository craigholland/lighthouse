"""Dependency evidence is validated locally from synthetic selected resources."""

from dataclasses import replace
from hashlib import sha256

import pytest

from lighthouse.adapters.github.dependency_evidence import (
    Resolution,
    verify_dependencies,
)
from lighthouse.adapters.github.transport import Held, Scope

REPO = "example/project"
ROOT = f"https://api.github.com/repos/{REPO}"
DEP = "example/other#13"
LINK = f"- {DEP}: [resolution](https://github.com/{REPO}/issues/4#issuecomment-77)"
TEXT = f"Lighthouse-Dependency: {DEP}\nLighthouse-Resolution: satisfied\nReason: accepted standalone delivery"
AT = "2026-11-26T05:00:00Z"
CAPTURE = Resolution(DEP, 77, 12, AT, sha256(TEXT.encode()).hexdigest(), "unmanaged")
ROW = {"id": 77, "url": f"{ROOT}/issues/comments/77", "issue_url": f"{ROOT}/issues/4",
       "body": TEXT, "user": {"id": 12}, "updated_at": AT}


def check(body, evidence, read):
    return verify_dependencies(f"## Dependencies\n{body}\n## Next\nNo effects", REPO, 4, {11, 12}, evidence, read)


def test_no_dependency_requires_explicit_none_and_no_reads():
    def forbidden(_):
        pytest.fail("unexpected comment read")
    check("None.", (), forbidden)
    for ambiguous in ("", "<!-- None -->", "None\n- another item", LINK):
        with pytest.raises(Held):
            check(ambiguous, (), forbidden)


def test_attributed_resolution_does_not_depend_on_issue_closure():
    def read(number):
        assert number == 77
        return ROW
    check(LINK, (CAPTURE,), read)


@pytest.mark.parametrize(("change", "message"), [
    ({"user": {"id": 13}}, "changed"), ({"issue_url": f"{ROOT}/issues/5"}, "changed"),
    ({"updated_at": "2026-11-27T05:00:00Z"}, "changed"), ({"body": TEXT + " edited"}, "changed"),
    ({"id": 78}, "changed"), ({}, "changed"),
])
def test_fresh_comment_must_match_the_original_capture(change, message):
    with pytest.raises(Held, match=message):
        check(LINK, (CAPTURE,), lambda _: ROW | change if change else {})


def test_no_downgrade_or_omitted_dependency():
    with pytest.raises(Held, match="provenance"):
        check(LINK, (replace(CAPTURE, provenance="managed"),), lambda _: ROW)
    other = LINK.replace(DEP, "example/another#19").replace("77", "78")
    with pytest.raises(Held, match="incomplete"):
        check(f"{LINK}\n{other}", (CAPTURE,), lambda _: ROW)
    wrong = TEXT.replace(DEP, "example/another#19")
    with pytest.raises(Held, match="unverified"):
        check(LINK, (replace(CAPTURE, body_sha256=sha256(wrong.encode()).hexdigest()),),
              lambda _: ROW | {"body": wrong})


def test_transport_is_exact_comment_get_allowlist():
    scope = Scope(REPO, 12, "ready", frozenset({77}))
    assert scope.target(f"{ROOT}/issues/comments/77") == f"/repos/{REPO}/issues/comments/77"
    for bad in (f"{ROOT}/issues/comments/78", f"{ROOT}/issues/comments/77?x=1"):
        with pytest.raises(Held):
            scope.target(bad)
