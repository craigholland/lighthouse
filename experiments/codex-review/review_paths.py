"""Conservative path handling for model-produced PR review text."""

import html
import re
from pathlib import Path
from urllib.parse import unquote

_ABSOLUTE = re.compile(
    r"(?i)\bfile\s*:|(?<![\w/.\\])(?<!https:)(?<!http:)"
    r"(?:[a-z]:(?:[/\\]|[a-z_][^\s/\\<>]*[/\\])|[/\\]{2}|[/\\](?=[^\s/\\])|~[/\\]|\$(?:home|env:\w+)[/\\]"
    r"|%[a-z_][a-z_0-9]*%[/\\])"
)
_TRAVERSAL = re.compile(r"(?<![\w.])\.\.(?=[/\\])")


class ReviewPathError(ValueError):
    """Review text contains an unsafe path; do not include the text in errors."""


def require_relative_paths(text: str) -> None:
    """Reject machine paths, including common URI and HTML encodings."""
    candidate = text
    for _ in range(4):
        if _ABSOLUTE.search(candidate) or _TRAVERSAL.search(candidate):
            raise ReviewPathError("Review contains an unapproved machine path.")
        decoded = unquote(html.unescape(candidate))
        if decoded == candidate:
            return
        candidate = decoded
    raise ReviewPathError("Review contains an ambiguously encoded path.")


def sanitize_review_paths(text: str, checkout: Path) -> str:
    """Convert paths in the approved checkout to repository-relative references."""
    root = str(checkout).replace("\\", "/").rstrip("/")
    parts = root.split("/")
    separator = r"[/\\]+"
    if root.startswith("/") and not root.startswith("//"):
        prefix = separator + separator.join(re.escape(part) for part in parts[1:])
    elif root.startswith("//"):
        prefix = r"[/\\]{2,}" + separator.join(re.escape(part) for part in parts[2:])
    else:
        prefix = separator.join(re.escape(part) for part in parts)
    approved = re.compile(
        rf"(?<![\w:/.\\]){prefix}"
        rf"(?:{separator}(?P<relative>[^\s\`'\"<>()\[\]{{}}]+)"
        rf"|(?=$|[\s\`'\"<>()\[\]{{}},;]))",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        relative = match.group("relative")
        return re.sub(separator, "/", relative) if relative else "."

    sanitized = approved.sub(replace, text)
    require_relative_paths(sanitized)
    return sanitized
