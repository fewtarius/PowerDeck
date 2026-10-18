"""Fan profile control.

Three known backends:
  - SteamFork custom-fan driver (steamfork_fan) — hwmon pwm1_enable
  - ASUS custom-fan curve (asus_custom_fan_curve) — hwmon pwm1_enable
  - JELOS / AYANEO oxp-platform fan (oxp_ec) — hwmon pwm1_enable,
    managed by the jelos-fancontrol daemon which reads
    cooling.profile via jelos-get-setting / jelos-set-setting.

The "profile" string maps to a thermal-policy toggle / curve:
  auto       - kernel auto, no manual override
  quiet      - minimum noise, lower duty limits
  moderate   - default balanced
  aggressive - high duty limits, fast response
"""

from __future__ import annotations

import glob
import os
import subprocess
from typing import List, Optional

from ._sysfs import file_exists, read_sysfs, write_sysfs


PROFILES = ["auto", "quiet", "moderate", "aggressive"]
PROFILE_TO_INDEX = {"quiet": 1, "moderate": 2, "aggressive": 3, "auto": 0}

# Hwmon driver names that expose a pwm1/pwm1_enable pair usable for
# fan-profile control.
FAN_HWMONS = ("steamfork_fan", "asus_custom_fan_curve", "oxp_ec")


def available_profiles() -> List[str]:
    for name in FAN_HWMONS:
        for p in glob.glob("/sys/class/hwmon/hwmon*/name"):
            if read_sysfs(p) == name:
                return PROFILES
    return PROFILES


def _curve_hwmon(name: str) -> Optional[str]:
    for p in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
        if read_sysfs(p) == name:
            return os.path.dirname(p)
    return None


def _find_curve_paths(name: str) -> List[str]:
    base = _curve_hwmon(name)
    if not base:
        return []
    return [os.path.join(base, attr) for attr in ("pwm1_min", "pwm1_max", "pwm1_enable")]


def _has_jelos_fan() -> bool:
    """True when the JELOS fancontrol tooling and oxp_ec hwmon are both present."""
    if not _curve_hwmon("oxp_ec"):
        return False
    # The jelos-fancontrol / jelos-set-setting binaries are the
    # userspace entry point for profile management on JELOS.
    return os.path.exists("/usr/bin/jelos-fancontrol")


def _set_jelos_profile(profile: str) -> bool:
    """Set a cooling profile on JELOS via jelos-set-setting + service pulse.

    The jelos-fancontrol daemon reads cooling.profile at startup (and on
    SIGHUP), so we update the setting and then send SIGHUP to the running
    service so it picks up the new curve immediately.
    """
    if not _has_jelos_fan():
        # Fall back to raw pwm1_enable toggle on the oxp_ec hwmon.
        oxp = _curve_hwmon("oxp_ec")
        if not oxp:
            return False
        enable_path = os.path.join(oxp, "pwm1_enable")
        if profile == "auto":
            return write_sysfs(enable_path, "0")
        return write_sysfs(enable_path, "1")

    try:
        subprocess.run(
            ["jelos-set-setting", "cooling.profile", profile],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        pass

    # Send SIGHUP to the daemon so it re-reads the new profile and
    # reapplies the corresponding PWM curve.
    try:
        subprocess.run(
            ["systemctl", "kill", "-s", "SIGHUP", "jelos-fancontrol"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        # If systemctl isn't available, try killing by name.
        try:
            subprocess.run(["pkill", "-HUP", "jelos-fancontrol"],
                           capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    return True


def _get_jelos_profile() -> str:
    """Read the current JELOS cooling profile via jelos-get-setting."""
    try:
        result = subprocess.run(
            ["jelos-get-setting", "cooling.profile"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            profile = result.stdout.strip()
            if profile in PROFILES:
                return profile
    except Exception:
        pass
    return "moderate"


def set_profile(profile: str) -> bool:
    if profile not in PROFILE_TO_INDEX:
        return False

    # JELOS path: delegate to the jelos-fancontrol daemon which manages
    # PWM curves based on the cooling.profile setting.
    if _has_jelos_fan():
        return _set_jelos_profile(profile)

    steamfork = _curve_hwmon("steamfork_fan")
    if steamfork:
        enable_path = os.path.join(steamfork, "pwm1_enable")
        if profile == "auto":
            return write_sysfs(enable_path, "2")
        return write_sysfs(enable_path, "1")

    # oxp_ec / AYANEO handhelds (non-JELOS SteamFork): pwm1_enable
    # 0 = automatic (daemon off), 1 = manual (daemon on).
    oxp = _curve_hwmon("oxp_ec")
    if oxp:
        enable_path = os.path.join(oxp, "pwm1_enable")
        if profile == "auto":
            return write_sysfs(enable_path, "0")
        return write_sysfs(enable_path, "1")

    asus = _curve_hwmon("asus_custom_fan_curve")
    if asus:
        enable_path = os.path.join(asus, "pwm1_enable")
        if profile == "auto":
            return write_sysfs(enable_path, "1")
        return write_sysfs(enable_path, "0")

    return False


def get_profile() -> str:
    # JELOS: read the actual cooling profile from jelos-get-setting
    if _has_jelos_fan():
        return _get_jelos_profile()

    for name, no_override_value in (("steamfork_fan", "2"), ("asus_custom_fan_curve", "1")):
        base = _curve_hwmon(name)
        if not base:
            continue
        raw = read_sysfs(os.path.join(base, "pwm1_enable"))
        if raw == no_override_value:
            return "auto"
        return "moderate"

    # oxp_ec (non-JELOS SteamFork / AYANEO): pwm1_enable 0 = auto
    oxp = _curve_hwmon("oxp_ec")
    if oxp:
        raw = read_sysfs(os.path.join(oxp, "pwm1_enable"))
        if raw == "0":
            return "auto"
        return "moderate"

    return "auto"


def is_available() -> bool:
    return any(
        read_sysfs(p) in FAN_HWMONS
        for p in glob.glob("/sys/class/hwmon/hwmon*/name")
    )
