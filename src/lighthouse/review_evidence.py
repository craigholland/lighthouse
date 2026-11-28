"""Bounded immutable Git evidence for one approved review, not a tool broker."""

import json
import re
from collections.abc import Callable
from hashlib import sha256

_SHA = re.compile(r"[0-9a-f]{40}")
_PART = re.compile(r"[A-Za-z0-9_.-]{1,80}")
_BLOB = re.compile(r"100(?:644|755) blob ([0-9a-f]{40})")


def paths(value: object, *, guidance: bool = False) -> tuple[str, ...]:
    """Allow only explicit canonical tracked text paths; no pathspec syntax."""
    if not isinstance(value, list) or not 1 <= len(value) <= 24:
        raise ValueError("snapshot path limit")
    result = []
    for path in value:
        if not isinstance(path, str) or len(path) > 200 or any(
            not _PART.fullmatch(part) or part.lower() in {".", "..", ".git"}
            or part.endswith(".") for part in path.split("/")
        ):
            raise ValueError("invalid snapshot path")
        result.append(path)
    if len({path.lower() for path in result}) != len(result) or (guidance and "AGENTS.md" not in result):
        raise ValueError("invalid snapshot path set")
    return tuple(sorted(result))


def capture(
    git: Callable[..., bytes], *, repository: str, head: str, base: str,
    changed: tuple[str, ...], context: tuple[str, ...],
) -> str:
    """Return canonical actual diff and approved context from immutable local objects."""
    if not _SHA.fullmatch(head) or not _SHA.fullmatch(base):
        raise ValueError("invalid snapshot revision")
    common = git("merge-base", "--all", base, head).decode().strip()
    if not _SHA.fullmatch(common):
        raise ValueError("snapshot merge base unavailable")
    fixed = ("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--no-color")
    outside = tuple(f":(exclude,literal){path}" for path in changed)
    if (git(*fixed, "--quiet", common, head, "--", ".", *outside) != b"0"
            or any(git(*fixed, "--quiet", common, head, "--", path) != b"1" for path in changed)):
        raise ValueError("snapshot changed paths mismatch")
    budget = 100_000

    def blob(commit: str, path: str, *, optional: bool = False) -> str:
        nonlocal budget
        entry = git("ls-tree", "-z", commit, "--", path).decode()
        if not entry and optional:
            return ""
        meta, sep, name = entry.partition("\t")
        match = _BLOB.fullmatch(meta)
        if not sep or name != path + "\0" or not match:
            raise ValueError("snapshot text path unavailable")
        oid = match[1]
        size_raw = git("cat-file", "-s", oid).strip()
        if not size_raw.isdigit() or len(size_raw) > 6:
            raise ValueError("snapshot blob invalid")
        size = int(size_raw)
        budget -= size
        if budget < 0:
            raise ValueError("snapshot blob budget")
        raw = git("cat-file", "blob", oid)
        if len(raw) != size or b"\0" in raw:
            raise ValueError("snapshot text invalid")
        return raw.decode("utf-8")

    for path in changed:
        blob(common, path, optional=True)
        blob(head, path, optional=True)
    sources = {path: blob(head, path) for path in context}
    patch = git(*fixed, "--text", "--full-index", "--unified=3", common, head, "--", *changed)
    if not patch or len(patch) > 200_000 or b"\0" in patch:
        raise ValueError("snapshot diff budget")
    snapshot = json.dumps(
        {"repository": repository, "base": base, "head": head, "mergeBase": common,
         "diff": patch.decode("utf-8"), "sources": sources},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    if len(snapshot.encode("utf-8")) > 300_000:
        raise ValueError("snapshot context budget")
    return snapshot


def digest(snapshot: str) -> str:
    """Public deterministic digest for matching trusted preparation to runner bytes."""
    return sha256(snapshot.encode("utf-8")).hexdigest()
