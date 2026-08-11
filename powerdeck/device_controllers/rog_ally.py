"""ROG Ally specific ops: platform profile, mcu_powersave, fan mode, thermal policy.

Distilled from the 942-line monolithic controller in the previous
implementation. Each function maps to a single asus-wmi / sysfs call
and returns bool. The frontend passes through plain key=value pairs.
"""

from __future__ import annotations

import glob
import os
from typing import Optional

import decky_plugin

from powerdeck import hardware


def _hwmon_by_name(name: str) -> Optional[str]:
    for p in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
        try:
            with open(p, "r") as f:
                if f.read().strip() == name:
                    return os.path.dirname(p)
        except OSError:
            continue
    return None


def get_fan_status() -> Optional[dict]:
    base = _hwmon_by_name("asus_custom_fan_curve")
    if not base:
        return None
    cpu_speed = None
    gpu_speed = None
    try:
        cpu_speed = open(os.path.join(base, "fan1_input")).read().strip()
    except OSError:
        pass
    try:
        gpu_speed = open(os.path.join(base, "fan2_input")).read().strip()
    except OSError:
        pass
    return {
        "cpu_fan": {"speed": int(cpu_speed) if cpu_speed else None, "mode": 2, "label": "cpu_fan"},
        "gpu_fan": {"speed": int(gpu_speed) if gpu_speed else None, "mode": 0, "label": "gpu_fan"},
    }


def set_fan_mode(fan_id: int, mode: int) -> bool:
    base = _hwmon_by_name("asus_custom_fan_curve")
    if not base:
        return False
    try:
        path = os.path.join(base, f"pwm{fan_id}_enable")
        with open(path, "w") as f:
            f.write(str(mode))
        return True
    except OSError:
        return False


def get_mcu_powersave() -> Optional[bool]:
    for path in (
        "/sys/devices/platform/asus-nb-wmi/mcu_powersave",
        "/sys/module/asus_wmi/parameters/mcu_powersave",
    ):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            return raw == "1"
        except OSError:
            continue
    return None


def set_mcu_powersave(enable: bool) -> bool:
    for path in (
        "/sys/devices/platform/asus-nb-wmi/mcu_powersave",
        "/sys/module/asus_wmi/parameters/mcu_powersave",
    ):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "w") as f:
                f.write("1" if enable else "0")
            return True
        except OSError:
            continue
    return False


def get_thermal_policy() -> Optional[int]:
    path = "/sys/devices/virtual/wmi/ugpio/throttle_thermal_policy"
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def set_thermal_policy(policy: int) -> bool:
    path = "/sys/devices/virtual/wmi/ugpio/throttle_thermal_policy"
    if not os.path.exists(path):
        return False
    try:
        with open(path, "w") as f:
            f.write(str(policy))
        return True
    except OSError:
        return False


def get_platform_profile() -> Optional[str]:
    return hardware.platform_profile.get_profile()


def set_platform_profile(profile: str) -> bool:
    return hardware.platform_profile.set_profile(profile)


def get_battery_charge_limit() -> Optional[int]:
    return hardware.battery.get_limit()


def set_battery_charge_limit(limit: int) -> bool:
    return hardware.battery.set_limit(limit)
