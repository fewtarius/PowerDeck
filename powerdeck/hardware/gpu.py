"""GPU power/clock control.

AMD:
  power_dpm_force_performance_level: "auto" | "low" | "high" | "balanced"
  pp_dpm_sclk: 0..N DPM states; min/max set via pp_dpm_sclk.
Intel:
  gt_min_freq_mhz / gt_max_freq_mhz
"""

from __future__ import annotations

import glob
import os
import re
from typing import List, Optional, Tuple

from ._sysfs import file_exists, read_sysfs, read_sysfs_int, write_sysfs


MODE_BATTERY = "battery"
MODE_AUTO = "auto"
MODE_PERFORMANCE = "performance"
MODE_RANGE = "range"
MODE_FIXED = "fixed"

DPM_FILE = "/sys/class/drm/card*/device/pp_dpm_sclk"
DPM_LEVEL = "/sys/class/drm/card*/device/power_dpm_force_performance_level"


def _cards(pattern: str) -> List[str]:
    return sorted(glob.glob(pattern))


def get_mode() -> str:
    """Approximate the current GPU mode from sysfs.

    "performance" / "high" -> "performance"; "low" -> "battery";
    otherwise "auto".
    """
    level = read_sysfs(_cards(DPM_LEVEL)[0] if _cards(DPM_LEVEL) else "", "auto")
    if level == "high":
        return MODE_PERFORMANCE
    if level == "low":
        return MODE_BATTERY
    return MODE_AUTO


def set_mode(mode: str) -> bool:
    level = {"battery": "low", "auto": "auto", "performance": "high"}.get(mode)
    if not level:
        return False
    success = False
    for path in _cards(DPM_LEVEL):
        if write_sysfs(path, level):
            success = True
    return success


def _amd_dpm_range() -> Tuple[int, int]:
    freqs: List[int] = []
    for path in _cards(DPM_FILE):
        try:
            with open(path, "r") as f:
                for line in f:
                    m = re.match(r"^(\d+):\s*(\d+)Mhz", line)
                    if m:
                        freqs.append(int(m.group(2)))
        except OSError:
            continue
    if freqs:
        return min(freqs), max(freqs)
    return 400, 1600


def _intel_range() -> Tuple[int, int]:
    mins, maxs = [], []
    for p in _cards("/sys/class/drm/card*/gt_min_freq_mhz"):
        mins.append(read_sysfs_int(p, 0))
    for p in _cards("/sys/class/drm/card*/gt_max_freq_mhz"):
        maxs.append(read_sysfs_int(p, 0))
    if mins and maxs:
        return min(mins), max(maxs)
    return 400, 1600


def get_freq_range() -> Tuple[int, int]:
    """Read the GPU's current frequency range."""
    if _cards(DPM_FILE):
        return _amd_dpm_range()
    return _intel_range()


def set_freq_range(min_mhz: int, max_mhz: int) -> bool:
    """Set the GPU's frequency range. AMD uses pp_dpm_sclk; Intel uses gt_*_freq_mhz.

    For Intel, min and max must differ by at least 50 MHz to avoid a
    silent rejection by the driver.
    """
    if _cards(DPM_FILE):
        success = False
        for path in _cards(DPM_FILE):
            try:
                with open(path, "r") as f:
                    lines = f.readlines()
                if not lines:
                    continue
                last_idx = len(lines) - 1
                first_idx = next(
                    (i for i, ln in enumerate(lines) if str(min_mhz) in ln and "Mhz" in ln),
                    None,
                )
                if first_idx is None:
                    first_idx = 0
                lines[first_idx] = re.sub(
                    r"\*?",
                    "*",
                    lines[first_idx].replace("*", ""),
                    count=1,
                ) if first_idx == last_idx else "*" + lines[first_idx].lstrip("*").lstrip()
                for ln_idx, ln in enumerate(lines):
                    if ln_idx == first_idx:
                        lines[ln_idx] = "*" + ln.lstrip("*").lstrip() if "*" not in ln else ln
                    else:
                        lines[ln_idx] = ln.replace("*", " ", 1).lstrip() + " " if ln_idx == 0 else ln
                with open(path, "w") as f:
                    f.writelines(lines)
                success = True
            except (OSError, ValueError):
                continue
        return success

    if min_mhz >= max_mhz:
        max_mhz = min_mhz + 50
    success = False
    for path in _cards("/sys/class/drm/card*/gt_min_freq_mhz"):
        if write_sysfs(path, str(min_mhz)):
            success = True
    for path in _cards("/sys/class/drm/card*/gt_max_freq_mhz"):
        if write_sysfs(path, str(max_mhz)):
            success = True
    return success


def set_freq_fixed(mhz: int) -> bool:
    return set_freq_range(mhz, mhz + 50)


def gpu_vendor() -> str:
    for path in _cards("/sys/class/drm/card*/device/vendor"):
        raw = read_sysfs(path)
        return {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}.get(raw, "unknown")
    return "unknown"
