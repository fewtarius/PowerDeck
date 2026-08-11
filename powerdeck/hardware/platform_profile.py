"""ACPI platform_profile sysfs.

Read/write /sys/firmware/acpi/platform_profile with the kernel's
choices list at /sys/firmware/acpi/platform_profile_choices. Used by
the Platform Profile UI section.
"""

from __future__ import annotations

import os
from typing import List, Tuple, Optional

from ._sysfs import file_exists, read_sysfs, write_sysfs


PROFILE_PATH = "/sys/firmware/acpi/platform_profile"
CHOICES_PATH = "/sys/firmware/acpi/platform_profile_choices"


def is_available() -> bool:
    return file_exists(PROFILE_PATH) and file_exists(CHOICES_PATH)


def choices() -> List[str]:
    if not file_exists(CHOICES_PATH):
        return []
    return [c for c in read_sysfs(CHOICES_PATH, "").split() if c]


def get_profile() -> Optional[str]:
    if not file_exists(PROFILE_PATH):
        return None
    return read_sysfs(PROFILE_PATH) or None


def set_profile(profile: str) -> bool:
    if not file_exists(PROFILE_PATH):
        return False
    valid = choices()
    if valid and profile not in valid:
        return False
    return write_sysfs(PROFILE_PATH, profile)
