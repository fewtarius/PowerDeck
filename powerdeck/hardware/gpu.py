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
OD_CLK_VOLTAGE = "/sys/class/drm/card*/device/pp_od_clk_voltage"


def _cards(pattern: str) -> List[str]:
    return sorted(glob.glob(pattern))


def get_mode() -> str:
    """Approximate the current GPU mode from sysfs.

    "performance" / "high" -> "performance"; "low" -> "battery";
    "manual" -> "range"; otherwise "auto".
    """
    level = read_sysfs(_cards(DPM_LEVEL)[0] if _cards(DPM_LEVEL) else "", "auto")
    if level == "high":
        return MODE_PERFORMANCE
    if level == "low":
        return MODE_BATTERY
    if level == "manual":
        return MODE_RANGE
    return MODE_AUTO


def set_mode(mode: str) -> bool:
    level_map = {
        "battery": "low",
        "auto": "auto",
        "performance": "high",
        "range": "manual",
        "fixed": "manual",
    }
    level = level_map.get(mode)
    if not level:
        return False
    paths = _cards(DPM_LEVEL)
    if not paths:
        # Intel: no power_dpm_force_performance_level sysfs.  On Intel
        # GPUs, "range" and "fixed" are controlled entirely via
        # gt_min_freq_mhz / gt_max_freq_mhz, so accept any mode and
        # succeed (the frequency files carry the actual control).
        return True
    success = False
    for path in paths:
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


def _amd_dpm_levels(path: str) -> List[Tuple[int, int]]:
    """Parse pp_dpm_sclk file: returns list of (index, freq_mhz).

    File format: "0: 800Mhz *\n1: 1100Mhz \n2: 2700Mhz \n"
    The asterisk marks the currently-active level.
    """
    levels: List[Tuple[int, int]] = []
    try:
        with open(path, "r") as f:
            for line in f:
                m = re.match(r"^(\d+):\s*(\d+)Mhz", line)
                if m:
                    levels.append((int(m.group(1)), int(m.group(2))))
    except OSError:
        pass
    return levels


def _amd_read_od_range(path: str) -> Tuple[int, int]:
    """Read the SCLK OD_RANGE from pp_od_clk_voltage.

    Format line: "SCLK:     800Mhz       2700Mhz"
    Returns (min_mhz, max_mhz), falling back to DPM-derived range.
    """
    try:
        with open(path, "r") as f:
            content = f.read()
        for line in content.split("\n"):
            if "SCLK:" in line:
                parts = line.replace("SCLK:", "").strip().split()
                freqs = []
                for p in parts:
                    if "Mhz" in p:
                        m = re.search(r"(\d+)", p)
                        if m:
                            freqs.append(int(m.group(1)))
                if len(freqs) >= 2:
                    return freqs[0], freqs[1]
    except OSError:
        pass
    return _amd_dpm_range()


def _amd_set_range_od(min_mhz: int, max_mhz: int) -> bool:
    """Set the GPU clock frequency range on AMD via pp_od_clk_voltage.

    The amdgpu driver exposes per-GPU overdrive clock control via the
    pp_od_clk_voltage sysfs file.  The protocol is:
      1. Write "manual" to power_dpm_force_performance_level
      2. Write "r" to pp_od_clk_voltage (reset to defaults)
      3. Write "s 0 <min_mhz>"  (set minimum SCLK level)
      4. Write "s 1 <max_mhz>"  (set maximum SCLK level)
      5. Write "c" to pp_od_clk_voltage (commit)

    This works on all AMD GPUs (Renoir, Cezanne, Phoenix, Phoenix1 /
    Strix Halo, etc.) and is the interface that the old monolith used.
    The pp_dpm_sclk index-write approach only works on a subset of
    asics and returns EINVAL on many APUs (e.g. Phoenix1), which is why
    GPU freq sliders silently failed to update.
    """
    level_paths = _cards(DPM_LEVEL)
    od_paths = _cards(OD_CLK_VOLTAGE)
    if not level_paths or not od_paths:
        return _amd_set_range_dpm(min_mhz, max_mhz)

    # Clamp to the hardware-supported SCLK range
    min_hw, max_hw = _amd_read_od_range(od_paths[0])
    min_mhz = max(min_hw, min(min_mhz, max_hw))
    max_mhz = max(min_hw, min(max_mhz, max_hw))

    # Step 1: switch to manual mode so OD writes are honored
    for lp in level_paths:
        write_sysfs(lp, "manual")

    success = False
    for od_path in od_paths:
        try:
            # Step 2: reset to defaults
            with open(od_path, "w") as f:
                f.write("r")
            # Step 3: set minimum SCLK
            with open(od_path, "w") as f:
                f.write(f"s 0 {min_mhz}")
            # Step 4: set maximum SCLK
            with open(od_path, "w") as f:
                f.write(f"s 1 {max_mhz}")
            # Step 5: commit
            with open(od_path, "w") as f:
                f.write("c")
            success = True
        except OSError:
            continue
    return success


def _amd_set_range_dpm(min_mhz: int, max_mhz: int) -> bool:
    """Fallback: set GPU clock range via pp_dpm_sclk index writes.

    Per the kernel docs (Documentation/gpu/amdgpu/thermal.rst), to
    change the clock range on pp_dpm_sclk you must:
      1. Write "manual" to power_dpm_force_performance_level
      2. Write space-separated DPM indices to pp_dpm_sclk
         (e.g. "2 3 4" enables levels 2-4, making level 2 the min
         and level 4 the max).

    NOTE: This method returns EINVAL on some APUs (e.g. Phoenix1 /
    Strix Halo), so pp_od_clk_voltage is preferred.  This is only
    reached when OD_CLK_VOLTAGE sysfs is unavailable.
    """
    level_paths = _cards(DPM_LEVEL)
    dpm_paths = _cards(DPM_FILE)
    if not level_paths or not dpm_paths:
        return False

    # Step 1: switch to manual mode so pp_dpm_sclk writes are honored.
    for lp in level_paths:
        write_sysfs(lp, "manual")

    success = False
    for path in dpm_paths:
        levels = _amd_dpm_levels(path)
        if not levels:
            continue
        # Find the index with the lowest frequency >= min_mhz (the floor)
        # and the index with the highest frequency <= max_mhz (the ceiling).
        min_idx = levels[0][0]
        max_idx = levels[-1][0]
        for idx, freq in levels:
            if freq <= min_mhz:
                min_idx = idx
            if freq >= max_mhz:
                max_idx = idx
                break
        # Ensure min_idx <= max_idx
        lo, hi = sorted((min_idx, max_idx))
        # Build the space-separated index list (inclusive range)
        indices = " ".join(str(i) for i in range(lo, hi + 1))
        if write_sysfs(path, indices):
            success = True
    return success


def set_freq_range(min_mhz: int, max_mhz: int) -> bool:
    """Set the GPU's frequency range. AMD uses pp_od_clk_voltage; Intel uses gt_*_freq_mhz.

    For Intel, min and max must differ by at least 50 MHz to avoid a
    silent rejection by the driver.
    """
    if _cards(OD_CLK_VOLTAGE):
        return _amd_set_range_od(min_mhz, max_mhz)
    if _cards(DPM_FILE):
        return _amd_set_range_dpm(min_mhz, max_mhz)

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
