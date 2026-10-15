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
import threading
from typing import List, Optional

from ._sysfs import read_sysfs, write_sysfs


CPU_ROOT = "/sys/devices/system/cpu"

# Module-level lock so the background game-monitor thread and the async
# callable handlers never race on a multi-step sysfs transaction (e.g.
# governor swap + freq cap in set_boost).
_sysfs_lock = threading.Lock()


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
    with _sysfs_lock:
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
    with _sysfs_lock:
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


def _get_scaling_max_freq_khz() -> Optional[int]:
    """Read scaling_max_freq from cpu0."""
    raw = read_sysfs(os.path.join(CPU_ROOT, "cpu0/cpufreq/scaling_max_freq"))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _get_cpuinfo_max_freq_khz() -> Optional[int]:
    """Read the hardware-reported max frequency from cpu0."""
    raw = read_sysfs(os.path.join(CPU_ROOT, "cpu0/cpufreq/cpuinfo_max_freq"))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _amd_pstate_lowest_nonlinear_freq_khz() -> Optional[int]:
    """Read amd_pstate_lowest_nonlinear_freq from cpu0.

    This is the most efficient operating point the hardware reports
    (e.g. ~1.1 GHz on Phoenix/Zen 4). Capping scaling_max_freq here
    when boost is disabled prevents the CPU from idling at high
    frequencies under load.
    """
    path = os.path.join(CPU_ROOT, "cpu0/cpufreq/amd_pstate_lowest_nonlinear_freq")
    raw = read_sysfs(path, "")
    try:
        val = int(raw)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _set_scaling_max_freq(max_freq_khz: int) -> bool:
    """Write scaling_max_freq for all online CPUs that expose it."""
    success = False
    for path in _cpu_paths("cpu*/cpufreq/scaling_max_freq"):
        if write_sysfs(path, str(max_freq_khz)):
            success = True
    return success


def set_boost(enabled: bool) -> bool:
    """Set CPU boost enabled/disabled.

    When disabling boost on amd-pstate (passive or guided mode), also
    cap ``scaling_max_freq`` to ``amd_pstate_lowest_nonlinear_freq`` if
    the kernel exposes it (most efficient point, ~1.1 GHz on Zen 4).
    Without this cap the CPU can still clock up to the full boost max
    (e.g. 3.3 GHz on a 7840U) even with boost=0, because ``boost=0``
    only prevents exceeding ``scaling_max_freq`` — it does not lower
    the cap. This is the single biggest source of idle / light-load
    power waste on modern AMD handhelds.

    When re-enabling boost, restore ``scaling_max_freq`` back to
    ``cpuinfo_max_freq`` (the hardware boost ceiling).
    """
    with _sysfs_lock:
        path = "/sys/devices/system/cpu/cpufreq/boost"
        if not os.path.exists(path):
            # No global boost sysfs — nothing to do.
            return False

        write_sysfs(path, "1" if enabled else "0")

        if not enabled:
            # Cap frequency to the most efficient operating point.
            cap = _amd_pstate_lowest_nonlinear_freq_khz()
            if cap is not None:
                _set_scaling_max_freq(cap)
            return True
        else:
            # Restore the full hardware max.
            hw_max = _get_cpuinfo_max_freq_khz()
            if hw_max is not None:
                _set_scaling_max_freq(hw_max)
            return True


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
