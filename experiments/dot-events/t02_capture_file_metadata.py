"""Compare fixed private-file observations without treating access as mutation."""

from os import name as platform_name
from os import stat_result
from stat import S_IXGRP, S_IXOTH, S_IXUSR

from t02_event_types import Hold

# Preserve all fields the running platform exposes, including nanosecond
# timestamps, file identity, Windows attributes, and the reparse tag.
_STABLE_FIELDS = tuple(
    name for name in dir(stat_result)
    if name.startswith("st_") and name not in {"st_atime", "st_atime_ns"}
)


def changed_stable_fields(
    before: stat_result, after: stat_result, *, path_to_descriptor: bool = False,
    executable_suffix: bool = False,
) -> tuple[str, ...]:
    """Report field names only, accounting for Windows' legacy path ctime."""
    compare = _STABLE_FIELDS
    if (
        path_to_descriptor and platform_name == "nt"
        and getattr(before, "st_birthtime_ns", None) is not None
        and before.st_ctime_ns == getattr(before, "st_birthtime_ns", None)
        and before.st_ctime == getattr(before, "st_birthtime", None)
    ):
        # Windows path stat may report legacy creation time in ctime,
        # while descriptor fstat reports change time. Cross-bind both
        # views by actual birthtime/identity, then check ctime within each.
        compare = tuple(field for field in compare if field not in {"st_ctime", "st_ctime_ns"})
    execute = S_IXUSR | S_IXGRP | S_IXOTH
    if (path_to_descriptor and executable_suffix and platform_name == "nt"
        and before.st_mode & execute == execute and before.st_mode ^ after.st_mode == execute):
        # Windows path stat can synthesize these three bits from the .exe
        # name. All non-execute mode bits and same-view checks remain exact.
        compare = tuple(field for field in compare if field != "st_mode")
    return tuple(field for field in compare if getattr(before, field) != getattr(after, field))


class CaptureMetadataHold(Hold):
    """Fixed internal phase and field labels, safe for operator output."""


def require_stable_metadata(
    before: stat_result, after: stat_result, phase: str, *, path_to_descriptor: bool = False,
    executable_suffix: bool = False,
) -> None:
    """Hold with just a fixed local phase and approved metadata field labels."""
    fields = changed_stable_fields(
        before, after, path_to_descriptor=path_to_descriptor, executable_suffix=executable_suffix,
    )
    if fields:
        raise CaptureMetadataHold(f"{phase}: {', '.join(fields)}")
