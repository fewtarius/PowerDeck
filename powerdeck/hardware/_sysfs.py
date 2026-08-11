"""Shared sysfs helpers."""

from __future__ import annotations

import os
from typing import Optional


def read_sysfs(path: str, default: str = "") -> str:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return default


def read_sysfs_int(path: str, default: int = 0) -> int:
    try:
        return int(read_sysfs(path, str(default)))
    except ValueError:
        return default


def write_sysfs(path: str, value: str) -> bool:
    """Write a string to a sysfs file. Returns True on success.

    /sys files only accept the bare value (no quotes, no trailing newline);
    some ACPI/platform-profile files reject unsolicited writes. Permission
    errors are converted to False; the caller decides whether to log.
    """
    if not value:
        return False
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except (OSError, ValueError):
        return False


def file_exists(path: str) -> bool:
    return os.path.exists(path)
