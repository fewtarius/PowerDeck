"""
Hardware capability detection for PowerDeck.

Returns a single `Capabilities` dataclass that captures everything the
plugin and UI need to make decisions: CPU core count, TDP min/max,
scaling driver, available governors, fan control availability, GPU
range, battery charge-limit availability, power-control method
(platform_profile / native_tdp / none) and its reasons.

Detection is synchronous on purpose - callers serialise the dict to
JSON for the frontend. Awaiting here would serialise the
<coroutine ...> blob, which previously caused "loading forever" bugs.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple


# Files that indicate this device supports the relevant control.
SMT_CONTROL = "/sys/devices/system/cpu/smt/control"
CPU_BOOST_PATH = "/sys/devices/system/cpu/cpufreq/boost"
WIFI_POWERSAVE_PATH = "/sys/module/iwlmvm/parameters/power_save"
PCIE_ASPM_POLICY = "/sys/module/pcie_aspm/parameters/policy"
USB_AUTOSUSPEND_GLOB = "/sys/bus/usb/devices/*/power/control"
ACPI_PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
ACPI_PLATFORM_PROFILE_CHOICES = "/sys/firmware/acpi/platform_profile_choices"
SCALING_DRIVERS_GLOB = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_driver"


@dataclass
class PowerControlCapabilities:
    platform_profile_available: bool = False
    platform_profile_choices: List[str] = field(default_factory=list)
    native_tdp_available: bool = False
    secure_boot_enabled: bool = False
    dev_mem_available: bool = False
    active_method: str = "none"  # "platform_profile" | "native_tdp" | "none"
    reason: str = "not yet detected"


@dataclass
class PStateCapabilities:
    available: bool = False
    current_mode: str = "passive"
    available_modes: List[str] = field(default_factory=lambda: ["active", "passive", "guided"])
    available_governors: List[str] = field(default_factory=lambda: ["powersave", "performance"])
    epp_available: bool = False
    epp_preferences: List[str] = field(default_factory=lambda: ["performance"])
    mode_switch_supported: bool = False


@dataclass
class RogAllyControls:
    fan_control: bool = False
    thermal_policy: bool = False
    mcu_powersave: bool = False
    power_limits: bool = False
    platform_profiles: bool = False
    battery_charge_limit: bool = False


@dataclass
class RogAllyDevice:
    device_name: str = ""
    controls: RogAllyControls = field(default_factory=RogAllyControls)


@dataclass
class Capabilities:
    device_name: str = "Unknown Device"
    cpu_name: str = ""
    cpu_vendor: str = "unknown"
    cpu_family: str = ""
    cpu_series: str = ""
    form_factor: str = "unknown"

    cpu_core_count: int = 8
    max_cpu_cores: int = 8

    tdp_min: int = 4
    tdp_max: int = 25
    default_tdp: int = 15

    has_fan_control: bool = False
    supports_cpu_boost: bool = False
    supports_smt: bool = False
    supports_gpu_control: bool = False
    min_gpu_freq: int = 400
    max_gpu_freq: int = 1600
    gpu_vendor: str = "unknown"
    is_jelos: bool = False

    scaling_driver: str = ""

    supports_wifi_power_save: bool = False
    supports_usb_power_mgmt: bool = False
    supports_pcie_aspm: bool = False

    battery_charge_limit_available: bool = False

    rog_ally: Optional[RogAllyDevice] = None

    power_control: PowerControlCapabilities = field(default_factory=PowerControlCapabilities)
    pstate: PStateCapabilities = field(default_factory=PStateCapabilities)

    steamos_manager_available: bool = False

    def to_dict(self) -> Dict:
        out = asdict(self)
        out["powerControl"] = out.pop("power_control")
        return out


# ── helpers ─────────────────────────────────────────────────────────────


def _read(path: str, default: str = "") -> str:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return default


def _read_int(path: str, default: int = 0) -> int:
    try:
        return int(_read(path, str(default)))
    except ValueError:
        return default


def _exists(path: str) -> bool:
    return os.path.exists(path)


def _detect_secure_boot() -> bool:
    try:
        path = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
        if not _exists(path):
            return False
        with open(path, "rb") as f:
            data = f.read()
        return len(data) >= 5 and data[4] == 1
    except Exception:
        return False


def _detect_dev_mem() -> bool:
    try:
        if not _exists("/dev/mem"):
            return False
        fd = os.open("/dev/mem", os.O_RDONLY)
        try:
            os.close(fd)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _detect_acpi_platform_profile() -> Tuple[bool, List[str]]:
    if not _exists(ACPI_PLATFORM_PROFILE) or not _exists(ACPI_PLATFORM_PROFILE_CHOICES):
        return False, []
    raw = _read(ACPI_PLATFORM_PROFILE_CHOICES, "")
    choices = [c for c in raw.split() if c]
    return bool(choices), choices


def _detect_power_control_method() -> PowerControlCapabilities:
    caps = PowerControlCapabilities()
    caps.platform_profile_available, caps.platform_profile_choices = _detect_acpi_platform_profile()
    caps.secure_boot_enabled = _detect_secure_boot()
    caps.dev_mem_available = _detect_dev_mem()

    if caps.platform_profile_available:
        caps.active_method = "platform_profile"
        caps.reason = "ACPI platform_profile provides TDP control"
        caps.native_tdp_available = caps.dev_mem_available and not caps.secure_boot_enabled
        return caps

    if not caps.secure_boot_enabled and caps.dev_mem_available:
        caps.active_method = "native_tdp"
        caps.reason = "ryzenadj + /dev/mem provides native TDP control"
        caps.native_tdp_available = True
        return caps

    if caps.secure_boot_enabled:
        caps.reason = "Secure Boot blocks /dev/mem; ryzenadj disabled"
    elif not caps.dev_mem_available:
        caps.reason = "/dev/mem unavailable; ryzenadj disabled"
    return caps


def _count_cpu_cores() -> int:
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:
        return 1


def _read_scaling_driver() -> str:
    paths = sorted(glob.glob(SCALING_DRIVERS_GLOB))
    for p in paths:
        d = _read(p)
        if d:
            return d
    return ""


def _detect_pstate(current_driver: str) -> PStateCapabilities:
    caps = PStateCapabilities()
    if current_driver != "amd-pstate-epp":
        # Only amd-pstate-epp supports mode switching. Other drivers
        # (intel-pstate, acpi-cpufreq) report a fixed scheduler.
        if "amd-pstate" in current_driver:
            caps.available = True
            caps.current_mode = "passive"
            caps.epp_available = False
        return caps

    caps.available = True
    caps.current_mode = _read("/sys/devices/system/cpu/amd_pstate/status", "passive")
    caps.available_modes = ["active", "passive", "guided"]
    caps.available_governors = _available_governors()
    caps.epp_available = caps.current_mode == "active"
    caps.epp_preferences = (
        ["power", "balance_power", "balance_performance", "performance"]
        if caps.epp_available
        else ["performance"]
    )
    caps.mode_switch_supported = _exists("/sys/devices/system/cpu/amd_pstate/status")
    return caps


def _available_governors() -> List[str]:
    governors: set = set()
    for path in sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_available_governors")):
        for gov in _read(path, "").split():
            governors.add(gov)
    return sorted(governors)


def _available_fan_profiles() -> List[str]:
    paths = [
        "/sys/class/hwmon/hwmon*/name",
    ]
    out: set = set()
    for path in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
        if _read(path) in ("asus_custom_fan_curve", "steamfork_fan"):
            out.add("auto")
            out.add("quiet")
            out.add("moderate")
            out.add("aggressive")
            break
    return sorted(out) or ["auto", "quiet", "moderate", "aggressive"]


def _detect_amd() -> bool:
    try:
        with open("/proc/cpuinfo", "r") as f:
            return "AuthenticAMD" in f.read()
    except OSError:
        return False


def _detect_jelos() -> bool:
    return os.path.exists("/etc/jelos-release") or os.path.exists("/usr/bin/jelos")


def _gpu_vendor() -> str:
    paths = sorted(glob.glob("/sys/class/drm/card*/device/vendor"))
    if not paths:
        return "unknown"
    vid = _read(paths[0])
    return {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}.get(vid, "unknown")


def _gpu_freq_range() -> Tuple[int, int]:
    vendor = _gpu_vendor()
    if vendor == "amd":
        path_glob = "/sys/class/drm/card*/device/pp_dpm_sclk"
        freqs: List[int] = []
        for path in sorted(glob.glob(path_glob)):
            try:
                with open(path, "r") as f:
                    for line in f:
                        m = re.match(r"^(\d+):\s*(\d+)Mhz", line)
                        if m:
                            freqs.append(int(m.group(2)))
            except OSError:
                pass
        if freqs:
            return min(freqs), max(freqs)

    if vendor == "intel":
        try:
            mins = sorted(glob.glob("/sys/class/drm/card*/gt_min_freq_mhz"))
            maxs = sorted(glob.glob("/sys/class/drm/card*/gt_max_freq_mhz"))
            min_v = min((_read_int(p) for p in mins), default=400)
            max_v = max((_read_int(p) for p in maxs), default=1600)
            return min_v, max_v
        except Exception:
            pass

    return 400, 1600


def _tdp_limits_from_processor_db() -> Tuple[int, int, int]:
    """Look up TDP defaults for the running processor. Returns (min, max, default).

    Tries the RyzenAdj-enumerated SMU values via /sys/class/hwmon. Returns
    conservative defaults (4W-25W, 15W default) on failure.
    """
    try:
        # Read package power limits (uW) from RAPL if available.
        rapl_path = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
        if _exists(rapl_path):
            with open(rapl_path, "r") as f:
                watts = int(f.read().strip()) // 1_000_000
            return 4, max(watts, 25), min(15, watts)
    except Exception:
        pass
    return 4, 25, 15


def _battery_charge_limit_available() -> bool:
    for path in glob.glob("/sys/class/power_supply/BAT*/charge_control_end_threshold"):
        if _exists(path):
            return True
    return False


def _is_rog_ally() -> Optional[RogAllyDevice]:
    """Detect ROG Ally / Ally X via DMI product name. Returns None otherwise."""
    vendor = ""
    product = ""
    try:
        vendor = _read("/sys/class/dmi/id/sys_vendor")
        product = _read("/sys/class/dmi/id/product_name")
    except Exception:
        pass
    is_ally = "ASUS" in vendor and ("RC71" in product or "RC72" in product)
    if not is_ally:
        return None
    controls = RogAllyControls(
        platform_profiles=_exists(ACPI_PLATFORM_PROFILE),
        power_limits=_exists("/sys/class/hwmon/hwmon*/name") and any(
            _read(p) in ("asus_wmi", "asus_nb_wmi") for p in glob.glob("/sys/class/hwmon/hwmon*/name")
        ),
        fan_control=any(
            _read(p) == "asus_custom_fan_curve" for p in glob.glob("/sys/class/hwmon/hwmon*/name")
        ),
        thermal_policy=_exists("/sys/devices/virtual/wmi/ugpio/throttle_thermal_policy"),
        mcu_powersave=_exists("/sys/devices/platform/asus-nb-wmi/mcu_powersave") or _exists(
            "/sys/module/asus_wmi/parameters/mcu_powersave"
        ),
        battery_charge_limit=_battery_charge_limit_available(),
    )
    return RogAllyDevice(
        device_name=f"{vendor} {product}".strip(),
        controls=controls,
    )


def _supports_pcie_aspm() -> bool:
    return _exists(PCIE_ASPM_POLICY)


def _supports_wifi_powersave() -> bool:
    if _exists(WIFI_POWERSAVE_PATH):
        return True
    for path in glob.glob("/sys/module/iwlmvm/parameters/power_save"):
        return True
    for path in glob.glob("/sys/module/iwlwifi/parameters/power_save"):
        return True
    return False


def _supports_usb_power_mgmt() -> bool:
    for ctrl in glob.glob(USB_AUTOSUSPEND_GLOB):
        return True
    return False


def detect() -> Capabilities:
    """Run all detection. Synchronous - returns a populated Capabilities object."""
    caps = Capabilities()

    # DMI
    try:
        sys_vendor = _read("/sys/class/dmi/id/sys_vendor")
        product = _read("/sys/class/dmi/id/product_name")
        caps.device_name = f"{sys_vendor} {product}".strip() or "Unknown Device"
        caps.cpu_vendor = "amd" if _detect_amd() else "intel"
    except Exception:
        pass

    # CPU + SMT + cores
    caps.cpu_core_count = _count_cpu_cores()
    caps.max_cpu_cores = caps.cpu_core_count
    caps.supports_smt = _exists(SMT_CONTROL)
    caps.supports_cpu_boost = _exists(CPU_BOOST_PATH)
    caps.scaling_driver = _read_scaling_driver()

    # TDP limits
    caps.tdp_min, caps.tdp_max, caps.default_tdp = _tdp_limits_from_processor_db()

    # Fan
    caps.has_fan_control = any(
        _read(p) in ("steamfork_fan", "asus_custom_fan_curve")
        for p in glob.glob("/sys/class/hwmon/hwmon*/name")
    )

    # GPU
    caps.gpu_vendor = _gpu_vendor()
    caps.min_gpu_freq, caps.max_gpu_freq = _gpu_freq_range()
    caps.supports_gpu_control = caps.gpu_vendor in ("amd", "intel")

    # Misc
    caps.is_jelos = _detect_jelos()
    caps.supports_wifi_power_save = _supports_wifi_powersave()
    caps.supports_usb_power_mgmt = _supports_usb_power_mgmt()
    caps.supports_pcie_aspm = _supports_pcie_aspm()
    caps.battery_charge_limit_available = _battery_charge_limit_available()

    # Power control path + pstate
    caps.power_control = _detect_power_control_method()
    caps.pstate = _detect_pstate(caps.scaling_driver)

    # ROG Ally
    caps.rog_ally = _is_rog_ally()

    # SteamOS Manager DBus presence (heuristic via dbus-send)
    try:
        out = subprocess.run(
            [
                "dbus-send",
                "--system",
                "--dest=org.freedesktop.DBus",
                "--type=method_call",
                "--print-reply",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus.NameHasOwner",
                "string:com.steampowered.SteamOSManager1",
            ],
            capture_output=True,
            timeout=2,
        )
        caps.steamos_manager_available = b"true" in out.stdout
    except Exception:
        caps.steamos_manager_available = False

    return caps


def available_governors() -> List[str]:
    return _available_governors()


def available_fan_profiles() -> List[str]:
    return _available_fan_profiles()


def tdp_limits() -> Tuple[int, int]:
    """Return (min, max) TDP for the current device. Used by per-field writers."""
    caps = detect()
    return caps.tdp_min, caps.tdp_max
