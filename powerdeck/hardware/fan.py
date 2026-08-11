"""Fan profile control.

Two known backends:
  - SteamFork custom-fan driver (steamfork_fan)
  - ASUS custom-fan curve (asus_custom_fan_curve)

The "profile" string maps to a thermal-policy toggle / curve:
  auto       - kernel auto, no manual override
  quiet      - minimum noise, lower duty limits
  moderate   - default balanced
  aggressive - high duty limits, fast response
"""

from __future__ import annotations

import glob
import os
from typing import List, Optional

from ._sysfs import file_exists, read_sysfs, write_sysfs


PROFILES = ["auto", "quiet", "moderate", "aggressive"]
PROFILE_TO_INDEX = {"quiet": 1, "moderate": 2, "aggressive": 3, "auto": 0}


def available_profiles() -> List[str]:
    has_steamfork = any(
        read_sysfs(p) == "steamfork_fan" for p in glob.glob("/sys/class/hwmon/hwmon*/name")
    )
    has_asus = any(
        read_sysfs(p) == "asus_custom_fan_curve" for p in glob.glob("/sys/class/hwmon/hwmon*/name")
    )
    if has_steamfork or has_asus:
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


def set_profile(profile: str) -> bool:
    if profile not in PROFILE_TO_INDEX:
        return False

    steamfork = _curve_hwmon("steamfork_fan")
    if steamfork:
        enable_path = os.path.join(steamfork, "pwm1_enable")
        if profile == "auto":
            return write_sysfs(enable_path, "2")
        return write_sysfs(enable_path, "1")

    asus = _curve_hwmon("asus_custom_fan_curve")
    if asus:
        enable_path = os.path.join(asus, "pwm1_enable")
        if profile == "auto":
            return write_sysfs(enable_path, "1")
        return write_sysfs(enable_path, "0")

    return False


def get_profile() -> str:
    for name, no_override_value in (("steamfork_fan", "2"), ("asus_custom_fan_curve", "1")):
        base = _curve_hwmon(name)
        if not base:
            continue
        raw = read_sysfs(os.path.join(base, "pwm1_enable"))
        if raw == no_override_value:
            return "auto"
        return "moderate"
    return "auto"


def is_available() -> bool:
    return any(
        read_sysfs(p) in ("steamfork_fan", "asus_custom_fan_curve")
        for p in glob.glob("/sys/class/hwmon/hwmon*/name")
    )
