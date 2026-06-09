"""Windows path helpers for Control Tower filesystem validation."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat


_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")
_ANY_DRIVE_SEGMENT_RE = re.compile(r"(^|[\\/])[A-Za-z]:")


def is_windows_platform() -> bool:
    return os.name == "nt"


def is_unc_path(raw_path: str) -> bool:
    return raw_path.startswith("\\\\") or raw_path.startswith("//")


def has_drive_qualified_prefix(raw_path: str) -> bool:
    return bool(_DRIVE_PREFIX_RE.match(raw_path))


def has_cross_drive_segment(raw_path: str) -> bool:
    return bool(_ANY_DRIVE_SEGMENT_RE.search(raw_path))


def normalize_key_case(path_fragment: str) -> str:
    return path_fragment.casefold() if is_windows_platform() else path_fragment


def is_windows_reparse_point(path: Path) -> bool:
    if not is_windows_platform():
        return False
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def is_unsafe_windows_reparse_point(path: Path) -> bool:
    return is_windows_reparse_point(path) and not path.is_symlink()
