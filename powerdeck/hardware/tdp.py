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

from .._env import clean_env
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

    Passing ``--apu-skin-temp`` to ryzenadj on these parts exits 255 with
    "set_apu_skin_temp_limit is not supported on this family" and aborts
    the whole run, so every other limit in the same invocation is lost.

    /proc/cpuinfo reports the marketing name ("AMD RYZEN AI MAX+ 395"),
    never the codename, so matching on "Strix Halo" alone silently fails
    and re-introduces the 255. Match the product family too.
    """
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read().upper()
        if "STRIX HALO" in cpuinfo:
            return True
        if "AI MAX" in cpuinfo or "GORGON HALO" in cpuinfo:
            return True
    except OSError:
        pass
    return False


def tiered_limits(
    watts: int,
    *,
    fast_max: Optional[int] = None,
    slow_max: Optional[int] = None,
    burst_delta: Optional[int] = None,
) -> Tuple[int, int, int]:
    """Split a sustained wattage into (stapm, fast, slow) in watts.

    STAPM is what the chip is allowed to hold indefinitely. Fast and slow
    are the short and medium PPT windows, which are allowed to burst
    above STAPM so a brief load does not get pre-emptively throttled to
    the sustained figure.

      fast = min(stapm + burst_delta, fast_max)
      slow = min(stapm * 1.25,          slow_max)

    Without measured ceilings for the part, all three collapse to the
    sustained value - guessing headroom would mean writing watts the
    silicon may reject.

    ``slow`` may come out below ``stapm`` when the part's measured slow
    ceiling is lower than the requested sustained figure - the 395 tops
    out at 120W cTDP but measures a 100W slow ceiling, so a 120W request
    is 120W burst and 100W sustained. Do not floor it to ``stapm``; that
    would silently promise sustained watts the part cannot hold.
    """
    stapm = max(1, int(watts))
    if not burst_delta and not fast_max and not slow_max:
        return stapm, stapm, stapm

    delta = burst_delta if burst_delta and burst_delta > 0 else 25
    fast = stapm + delta
    if fast_max:
        fast = min(fast, fast_max)
    fast = max(fast, stapm)

    slow = int(stapm * 1.25)
    if slow_max:
        slow = min(slow, slow_max)

    return stapm, fast, slow


def set_tdp_native(
    watts: int,
    *,
    omit_skin_temp: Optional[bool] = None,
    fast_limit: Optional[int] = None,
    sustained_limit: Optional[int] = None,
    stapm_limit: Optional[int] = None,
    apu_slow_limit: Optional[int] = None,
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
        f"--tctl-temp={int(os.environ.get('POWERDECK_TCTL_TEMP', 95))}",
    ]
    # PPT LIMIT APU is the package-wide window. Leave it alone unless the
    # caller asks, because it also gates the iGPU on an APU.
    if apu_slow_limit is not None:
        cmd.append(f"--apu-slow-limit={apu_slow_limit}")
    if not omit_skin_temp:
        # ryzenadj's flag is --apu-skin-temp and takes degrees C (not mW).
        # Older PowerDeck revisions passed a milliwatt-scaled value to a
        # --apu-skin-temp-limit flag that the binary doesn't accept; the
        # result was a non-zero return code and the rest of the limits
        # silently failed to apply.
        cmd.append(f"--apu-skin-temp={int(os.environ.get('POWERDECK_SKIN_TEMP', 95))}")

    def _run(args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            capture_output=True,
            timeout=5,
            env=clean_env(),
            text=True,
            check=False,
        )

    try:
        result = _run(cmd)
        if result.returncode == 0:
            return True
        # A family that rejects --apu-skin-temp aborts the entire run, so
        # the STAPM/PPT writes in the same invocation are lost. Detection
        # is name-based and new silicon ships faster than this file is
        # updated, so retry once without the flag before giving up.
        output = f"{result.stdout or ''}{result.stderr or ''}"
        # ryzenadj spells the failure "set_apu_skin_temp_limit" (underscores)
        # while the flag is --apu-skin-temp (hyphens). Match either.
        if "skin_temp" in output or "skin-temp" in output:
            retry = [arg for arg in cmd if not arg.startswith("--apu-skin-temp")]
            return _run(retry).returncode == 0
        return False
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def set_tdp_sysfs(watts: int) -> bool:
    """Emulate TDP via powercap/RAPL on Intel. Returns True on success."""
    path = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
    if not file_exists(path):
        return False
    uw = int(watts * 1_000_000)
    return write_sysfs(path, str(uw))


def set_tdp(
    watts: int,
    *,
    prefer_native: bool = True,
    fast_max: Optional[int] = None,
    slow_max: Optional[int] = None,
    burst_delta: Optional[int] = None,
) -> Tuple[bool, str]:
    """Single TDP set. Returns (ok, method).

    method is one of: "ryzenadj", "sysfs", "soft_fallback".

    ``watts`` is the sustained limit; fast/slow burst above it using the
    part's measured ceilings when the spec table has them.
    """
    if prefer_native:
        stapm, fast, slow = tiered_limits(
            watts, fast_max=fast_max, slow_max=slow_max, burst_delta=burst_delta
        )
        ok = set_tdp_native(
            watts,
            stapm_limit=stapm * 1000,
            fast_limit=fast * 1000,
            sustained_limit=slow * 1000,
            # PPT LIMIT APU gates the whole package including the iGPU, so
            # it has to be high enough that the burst ceiling is reachable.
            apu_slow_limit=fast * 1000,
        )
        if ok:
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
        result = subprocess.run([path, "-i"], capture_output=True, timeout=5, text=True,
                               env=clean_env())
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
