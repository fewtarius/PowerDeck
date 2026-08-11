"""AC power detection.

Reads /sys/class/power_supply/AC*/online and synthesises a single boolean.
Falls back to battery status (Charging/Discharging) when no AC adapter
path is present (handhelds that never see a charger, some embedded boards).
"""

from __future__ import annotations

import glob
import os

from ._sysfs import read_sysfs


def _ac_paths() -> list[str]:
    """Return /sys paths that report AC power state.

    Linux uses AC*, ACAD*, ADP*, etc. depending on the kernel driver.
    The contents of `type` would be the right key, but reading type
    for every power_supply then checking online is more work than the
    glob. We accept any of: AC*, ACAD*, ADP*.
    """
    candidates: list[str] = []
    for prefix in ("AC", "ACAD", "ADP"):
        candidates.extend(sorted(glob.glob(f"/sys/class/power_supply/{prefix}*/online")))
    return candidates

def _battery_status_paths() -> list[str]:
    return sorted(glob.glob("/sys/class/power_supply/BAT*/status"))


def get_ac_power_status() -> bool:
    """Return True when the system is on AC power."""
    for path in _ac_paths():
        raw = read_sysfs(path, "0")
        try:
            if int(raw) == 1:
                return True
        except ValueError:
            continue

    for path in _battery_status_paths():
        status = read_sysfs(path, "").lower()
        if status in ("charging", "full", "not charging"):
            return True

    return False
