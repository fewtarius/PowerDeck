"""CPU control: governor, EPP, CPU boost, SMT, online cores.

All writers fan out to /sys/devices/system/cpu/cpu*/cpufreq/scaling_*.
On amd-pstate-epp active mode, EPP writes are only honored when the
governor exposes the full EPP hint set (powersave/schedutil/etc.).
Writing EPP=power while governor=performance silently coerces to
performance, wasting power; we route through a governor swap in that
case (see set_epp).
"""

from __future__ import annotations

import glob
import os
from typing import List, Optional

from ._sysfs import read_sysfs, write_sysfs


CPU_ROOT = "/sys/devices/system/cpu"


def _cpu_paths(pattern: str) -> list[str]:
    return sorted(glob.glob(os.path.join(CPU_ROOT, pattern)))


def available_governors() -> List[str]:
    governors: set = set()
    for path in _cpu_paths("cpu*/cpufreq/scaling_available_governors"):
        for gov in read_sysfs(path, "").split():
            governors.add(gov)
    return sorted(governors)


def get_governor() -> Optional[str]:
    return read_sysfs(os.path.join(CPU_ROOT, "cpu0/cpufreq/scaling_governor")) or None


def set_governor(governor: str) -> bool:
    if governor not in available_governors():
        return False
    success = False
    for path in _cpu_paths("cpu*/cpufreq/scaling_governor"):
        if write_sysfs(path, governor):
            success = True
    return success


def get_epp() -> Optional[str]:
    path = os.path.join(CPU_ROOT, "cpu0/cpufreq/energy_performance_preference")
    if not os.path.exists(path):
        return None
    return read_sysfs(path) or None


def available_epp() -> List[str]:
    path = os.path.join(CPU_ROOT, "cpu0/cpufreq/energy_performance_available_preferences")
    if not os.path.exists(path):
        return []
    return [e for e in read_sysfs(path, "").split() if e]


def set_epp(epp: str, governor: Optional[str] = None) -> bool:
    """Set EPP on all CPUs. If a swap is needed (governor=performance,
    EPP!=performance), switch to the supplied governor first and
    restore after the EPP write.
    """
    cur_gov = get_governor()
    needs_swap = cur_gov == "performance" and epp != "performance"
    restore_governor: Optional[str] = None
    if needs_swap and governor:
        restore_governor = "performance" if governor == "performance" else None
        set_governor(governor)
    elif needs_swap:
        set_governor("schedutil")

    success = False
    pattern = os.path.join(CPU_ROOT, "cpu*/cpufreq/energy_performance_preference")
    for path in sorted(glob.glob(pattern)):
        if write_sysfs(path, epp):
            success = True

    if restore_governor:
        set_governor(restore_governor)
    return success


def get_boost() -> Optional[bool]:
    path = "/sys/devices/system/cpu/cpufreq/boost"
    if not os.path.exists(path):
        return None
    raw = read_sysfs(path)
    if raw in ("1", "on"):
        return True
    if raw in ("0", "off"):
        return False
    try:
        return bool(int(raw))
    except ValueError:
        return None


def set_boost(enabled: bool) -> bool:
    path = "/sys/devices/system/cpu/cpufreq/boost"
    if not os.path.exists(path):
        return False
    return write_sysfs(path, "1" if enabled else "0")


def get_smt() -> Optional[bool]:
    path = os.path.join(CPU_ROOT, "smt/control")
    if not os.path.exists(path):
        return None
    raw = read_sysfs(path)
    if raw in ("on", "onplus"):
        return True
    if raw == "off":
        return False
    return None


def set_smt(enabled: bool) -> bool:
    path = os.path.join(CPU_ROOT, "smt/control")
    if not os.path.exists(path):
        return False
    return write_sysfs(path, "on" if enabled else "off")


def get_online_cores() -> int:
    count = 0
    for path in _cpu_paths("cpu*/online"):
        try:
            if int(read_sysfs(path, "0")):
                count += 1
        except ValueError:
            count += 1
    return count


def set_online_cores(n: int) -> bool:
    """Take n cores online (the rest offline). 1 <= n <= available."""
    paths = sorted(
        glob.glob(os.path.join(CPU_ROOT, "cpu[0-9]*/online")),
        key=lambda p: int(p.split("/cpu")[-1].split("/")[0]),
    )
    if not paths:
        return False
    n = max(1, min(n, len(paths)))
    success = False
    for idx, path in enumerate(paths):
        target = "1" if idx < n else "0"
        if write_sysfs(path, target):
            success = True
    return success
