"""TDP control.

Two paths:
  - Native via ryzenadj: writes STAPM/fast/slow directly to AMD SMU
    through /dev/mem. Used when Secure Boot is off and /dev/mem is
    readable, OR when platform_profile is unavailable.
  - Sysfs-backed: emulates TDP via governor/EPP swaps when no native
    path exists. Returns False so the UI falls back to a soft control
    banner.

On Strix Halo (and other Zen 5 parts without skin-temp sensors),
ryzenadj's --apu-skin-temp flag exits 255; we omit it.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

from ._sysfs import file_exists, read_sysfs, write_sysfs


RYZENADJ_LOCATIONS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "RyzenAdj", "build", "ryzenadj"),
    "/usr/bin/ryzenadj",
    "/usr/local/bin/ryzenadj",
    os.path.expanduser("~/homebrew/plugins/PowerDeck/RyzenAdj/build/ryzenadj"),
]


def _find_ryzenadj() -> Optional[str]:
    cached = getattr(_find_ryzenadj, "_cached", None)
    if cached:
        return cached
    for path in RYZENADJ_LOCATIONS:
        if os.path.exists(path) and os.access(path, os.X_OK):
            _find_ryzenadj._cached = path
            return path
    found = shutil.which("ryzenadj")
    _find_ryzenadj._cached = found
    return found


def is_strix_halo() -> bool:
    """Heuristic: AMD Strix Halo (Ryzen AI MAX) lacks a skin-temp sensor.

    The actual detection comes from CPU family/model; we use a wider
    matcher because the precise family IDs vary across kernel versions.
    Fall back to True if /proc/cpuinfo mentions "Strix Halo" anywhere.
    """
    try:
        with open("/proc/cpuinfo", "r") as f:
            if "Strix Halo" in f.read():
                return True
    except OSError:
        pass
    return False


def set_tdp_native(
    watts: int,
    *,
    omit_skin_temp: Optional[bool] = None,
    fast_limit: Optional[int] = None,
    sustained_limit: Optional[int] = None,
    stapm_limit: Optional[int] = None,
) -> bool:
    """Write STAPM/fast/slow via ryzenadj. Returns True on success.

    `watts` is the value passed to STAPM, fast, and slow (in mW).
    `omit_skin_temp` defaults to True on Strix Halo (no skin sensor).
    """
    path = _find_ryzenadj()
    if not path:
        return False
    if omit_skin_temp is None:
        omit_skin_temp = is_strix_halo()

    mw = int(watts * 1000)
    if fast_limit is None:
        fast_limit = mw
    if sustained_limit is None:
        sustained_limit = mw
    if stapm_limit is None:
        stapm_limit = mw

    cmd = [
        path,
        f"--stapm-limit={stapm_limit}",
        f"--fast-limit={fast_limit}",
        f"--slow-limit={sustained_limit}",
    ]
    if not omit_skin_temp:
        # ryzenadj's flag is --apu-skin-temp and takes degrees C (not mW).
        # Older PowerDeck revisions passed a milliwatt-scaled value to a
        # --apu-skin-temp-limit flag that the binary doesn't accept; the
        # result was a non-zero return code and the rest of the limits
        # silently failed to apply.
        cmd.append(f"--apu-skin-temp={int(os.environ.get('POWERDECK_SKIN_TEMP', 70))}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=5,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def set_tdp_sysfs(watts: int) -> bool:
    """Emulate TDP via powercap/RAPL on Intel. Returns True on success."""
    path = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
    if not file_exists(path):
        return False
    uw = int(watts * 1_000_000)
    return write_sysfs(path, str(uw))


def set_tdp(watts: int, *, prefer_native: bool = True) -> Tuple[bool, str]:
    """Single TDP set. Returns (ok, method).

    method is one of: "ryzenadj", "sysfs", "soft_fallback".
    """
    if prefer_native:
        if set_tdp_native(watts):
            return True, "ryzenadj"
    if set_tdp_sysfs(watts):
        return True, "sysfs"
    return False, "soft_fallback"


def get_tdp_native() -> Optional[int]:
    """Return current STAPM limit in watts by parsing ryzenadj -i output."""
    path = _find_ryzenadj()
    if not path:
        return None
    try:
        result = subprocess.run([path, "-i"], capture_output=True, timeout=5, text=True)
        for line in result.stdout.splitlines():
            if "STAPM LIMIT" in line.upper():
                parts = line.split()
                for i, p in enumerate(parts):
                    if "LIMIT" in p.upper() and i + 1 < len(parts):
                        try:
                            return int(parts[i + 1]) // 1000
                        except ValueError:
                            continue
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    return None
