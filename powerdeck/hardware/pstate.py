"""AMD p-state driver mode control (active / passive / guided)."""

from __future__ import annotations

import os

from ._sysfs import read_sysfs, write_sysfs


PSTATE_STATUS = "/sys/devices/system/cpu/amd_pstate/status"
VALID_MODES = ["active", "passive", "guided"]


def is_available() -> bool:
    return os.path.exists(PSTATE_STATUS)


def get_mode() -> str:
    if not is_available():
        return "passive"
    raw = read_sysfs(PSTATE_STATUS, "passive")
    return raw if raw in VALID_MODES else "passive"


def set_mode(mode: str) -> bool:
    if mode not in VALID_MODES:
        return False
    return write_sysfs(PSTATE_STATUS, mode)
