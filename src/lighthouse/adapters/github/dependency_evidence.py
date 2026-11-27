"""Exact dependency evidence for one preselected review; never resolves a graph."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from lighthouse.adapters.github.transport import ORIGIN, Held

_DEP = r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}#[1-9][0-9]{0,18}"
_SECTION = re.compile(r"^##[ \t]+Dependencies[ \t]*$", re.MULTILINE)
_REV = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")


@dataclass(frozen=True)
class Resolution:
    """Captured independent evidence, matched afresh before any review effect."""

    dependency: str
    comment: int
    actor: int
    revision: str
    body_sha256: str
    provenance: str


def verify_dependencies(
    body: str, repository: str, issue: int, actors: set[int], evidence: tuple[Resolution, ...],
    read: Callable[[int], dict[str, object]],
) -> None:
    """Hold unless the exact declared set has supported, attributed evidence."""

    body = re.sub(r"<!--.*?(?:-->|\Z)", "", body.replace("\r\n", "\n"), flags=re.DOTALL)
    headings = list(_SECTION.finditer(body))
    if len(headings) != 1 or len(evidence) > 10:
        raise Held("dependency-declaration-unresolved")
    section = re.split(r"^##[ \t]+", body[headings[0].end():], maxsplit=1, flags=re.MULTILINE)[0].strip()
    if section in {"None", "None."} and not evidence:
        return
    link = re.compile(
        rf"- (?P<dep>{_DEP}): \[resolution\]"
        rf"\(https://github\.com/{re.escape(repository)}/issues/{issue}"
        r"#issuecomment-(?P<id>[1-9][0-9]{0,18})\)",
    )
    declared: dict[str, int] = {}
    for line in section.splitlines():
        match = link.fullmatch(line)
        if not match or match["dep"] in declared or int(match["id"]) in declared.values():
            raise Held("dependency-declaration-unresolved")
        declared[match["dep"]] = int(match["id"])
    if not declared or len(declared) != len(evidence) or declared != {
        entry.dependency: entry.comment for entry in evidence
    }:
        raise Held("dependency-evidence-incomplete")
    root = f"{ORIGIN}/repos/{repository}"
    for entry in evidence:
        if (entry.provenance != "unmanaged" or type(entry.actor) is not int or entry.actor not in actors
                or not _REV.fullmatch(entry.revision) or not re.fullmatch(r"[0-9a-f]{64}", entry.body_sha256)):
            raise Held("dependency-provenance-unverified")
        row = read(entry.comment)
        user, text = row.get("user"), row.get("body")
        if (type(row.get("id")) is not int or row["id"] != entry.comment
                or row.get("url") != f"{root}/issues/comments/{entry.comment}"
                or row.get("issue_url") != f"{root}/issues/{issue}"
                or row.get("updated_at") != entry.revision or not isinstance(user, dict)
                or type(user.get("id")) is not int or user["id"] != entry.actor
                or not isinstance(text, str) or sha256(text.encode()).hexdigest() != entry.body_sha256):
            raise Held("dependency-resolution-changed")
        lines = text.replace("\r\n", "\n").splitlines()
        if (len(lines) < 3 or lines[0] != f"Lighthouse-Dependency: {entry.dependency}"
                or lines[1] != "Lighthouse-Resolution: satisfied"
                or not re.fullmatch(r"Reason: \S.*", lines[2])
                or any(line.startswith(("Lighthouse-Dependency:", "Lighthouse-Resolution:")) for line in lines[3:])):
            raise Held("dependency-resolution-unverified")
