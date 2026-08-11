"""Battery charge limit.

Reads /sys/class/power_supply/BAT*/charge_control_end_threshold. Writes
the same sysfs file. Works on any device exposing the standard kernel
interface (ROG Ally, Nimo Axis, Legion Go, Framework laptops, ThinkPads,
Galaxy Books, etc.).
"""

from __future__ import annotations

import glob
import os
from typing import Optional

from ._sysfs import file_exists, read_sysfs_int, write_sysfs


def available_batteries() -> list[str]:
    return sorted(glob.glob("/sys/class/power_supply/BAT*"))


def is_available() -> bool:
    return any(file_exists(os.path.join(b, "charge_control_end_threshold")) for b in available_batteries())


def get_limit() -> Optional[int]:
    for base in available_batteries():
        path = os.path.join(base, "charge_control_end_threshold")
        if file_exists(path):
            return read_sysfs_int(path, 100)
    return None


def set_limit(percent: int) -> bool:
    if not 20 <= percent <= 100:
        return False
    success = False
    for base in available_batteries():
        path = os.path.join(base, "charge_control_end_threshold")
        if file_exists(path) and write_sysfs(path, str(percent)):
            success = True
    return success
