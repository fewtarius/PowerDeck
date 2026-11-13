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

from ._env import clean_env


# Files that indicate this device supports the relevant control.
SMT_CONTROL = "/sys/devices/system/cpu/smt/control"
CPU_BOOST_PATH = "/sys/devices/system/cpu/cpufreq/boost"
WIFI_POWERSAVE_PATH = "/sys/module/iwlmvm/parameters/power_save"
PCIE_ASPM_POLICY = "/sys/module/pcie_aspm/parameters/policy"
USB_AUTOSUSPEND_GLOB = "/sys/bus/usb/devices/*/power/control"
ACPI_PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
ACPI_PLATFORM_PROFILE_CHOICES = "/sys/firmware/acpi/platform_profile_choices"
SCALING_DRIVERS_GLOB = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_driver"

AMD_PSTATE_STATUS = "/sys/devices/system/cpu/amd_pstate/status"
CPU_EPP_PREF_PATH = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences"


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
    # Tiered burst ceilings. STAPM is the sustained limit the user picks;
    # fast/slow may burst above it up to these ceilings. None means the
    # processor spec table has no measured values, in which case the
    # sustained value is used for all three.
    tdp_fast_max: Optional[int] = None
    tdp_slow_max: Optional[int] = None
    tdp_burst_delta: Optional[int] = None

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
    caps.native_tdp_available = caps.dev_mem_available and not caps.secure_boot_enabled

    # ryzenadj wins when it is usable. On hardware that also exposes ACPI
    # platform_profile (Emdoor N161L / Strix Halo), the platform profile
    # only drives EC fan and power policy - writing it leaves the SMU APU
    # power limit untouched, so it cannot own the watt slider. Reporting
    # "platform_profile" here previously hid the TDP control from the UI
    # while ryzenadj was fully functional.
    if caps.native_tdp_available:
        caps.active_method = "native_tdp"
        if caps.platform_profile_available:
            caps.reason = (
                "ryzenadj + /dev/mem sets the SMU power limit; "
                "ACPI platform_profile sets EC fan and power policy"
            )
        else:
            caps.reason = "ryzenadj + /dev/mem provides native TDP control"
        return caps

    if caps.platform_profile_available:
        caps.active_method = "platform_profile"
        caps.reason = "ACPI platform_profile provides TDP control"
        return caps

    if caps.secure_boot_enabled:
        caps.reason = "Secure Boot blocks /dev/mem; ryzenadj disabled"
    elif not caps.dev_mem_available:
        caps.reason = "/dev/mem unavailable; ryzenadj disabled"
    return caps


def _count_cpu_cores() -> int:
    """Count the total *logical* CPU count (including offline threads).

    ``os.cpu_count()`` follows the process' CPU affinity and the online
    CPU mask — on systems where secondary threads are offline (e.g. an
    SMT-disabled profile, or hotplug offlining some CPUs), it returns
    the *online* count rather than the hardware-present count.  On a
    Ryzen Z1 Extreme this returns 6 instead of 16, making the core
    slider cap at 5 even with SMT enabled.

    Instead we count the ``cpuN`` directories under /sys/devices/system,
    which reflects the hardware topology regardless of online/offline
    state.
    """
    try:
        count = len(glob.glob(os.path.join("/sys/devices/system/cpu", "cpu[0-9]*")))
        if count > 0:
            return max(1, count)
    except Exception:
        pass
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


def _available_epp_preferences() -> List[str]:
    """Read the full EPP preference list from sysfs at runtime.

    On classic amd-pstate, these files only appear when the pstate mode
    is 'active'.  On amd-pstate-epp they exist in all modes but writes
    are only honored in 'active' mode.
    """
    if not os.path.exists(CPU_EPP_PREF_PATH):
        return []
    return [e for e in _read(CPU_EPP_PREF_PATH, "").split() if e]


def _detect_pstate(current_driver: str) -> PStateCapabilities:
    caps = PStateCapabilities()
    if "amd-pstat" not in current_driver:
        # intel-pstate, acpi-cpufreq — no pstate mode switching.
        return caps

    # Both amd-pstate (classic) and amd-pstate-epp support mode
    # switching via /sys/devices/system/cpu/amd_pstate/status.
    # On kernel 6.18+, classic amd-pstate in "active" mode exposes the
    # per-CPU energy_performance_preference sysfs files, enabling
    # explicit EPP hint writes just like the -epp driver.  The old code
    # hard-coded epp_available=False for classic amd-pstate, hiding the
    # EPP slider even when the kernel fully supports it.
    caps.available = True
    caps.current_mode = _read(AMD_PSTATE_STATUS, "passive")
    caps.available_modes = ["active", "passive", "guided"]
    caps.available_governors = _available_governors()
    caps.mode_switch_supported = _exists(AMD_PSTATE_STATUS)

    # EPP writes are only honored in active mode on both driver
    # variants.  In passive/guided mode the kernel ignores EPP hints
    # (or the files don't even exist on classic amd-pstate).
    caps.epp_available = caps.current_mode == "active"
    if caps.epp_available:
        prefs = _available_epp_preferences()
        caps.epp_preferences = prefs if prefs else [
            "power", "balance_power", "balance_performance", "performance"
        ]

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
        if _read(path) in ("asus_custom_fan_curve", "steamfork_fan", "oxp_ec"):
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


# SMU power table, cached for the process lifetime. Reading it spawns
# ryzenadj (~200ms) and detect() is called from several paths.
_SMU_INFO_CACHE: Optional[Dict[str, float]] = None
_TDP_RANGE_CACHE: Optional[Tuple[int, int, int]] = None


def _ryzenadj_smu_info() -> Dict[str, float]:
    """Read the SMU power table through ryzenadj. Cached.

    Returns a ``{name: watts}`` mapping, empty when the SMU is unreachable
    (no /dev/mem, Secure Boot, Intel, or no ryzenadj binary).
    """
    global _SMU_INFO_CACHE
    if _SMU_INFO_CACHE is not None:
        return _SMU_INFO_CACHE

    info: Dict[str, float] = {}
    _SMU_INFO_CACHE = info
    if not _exists("/dev/mem") or _detect_secure_boot():
        return info

    try:
        from .hardware.tdp import _find_ryzenadj

        path = _find_ryzenadj()
        if not path:
            return info
        out = subprocess.run(
            [path, "-i"], capture_output=True, text=True, timeout=5, env=clean_env()
        )
    except Exception:
        return info

    for line in (out.stdout or "").splitlines():
        m = re.match(r"^\|\s*([A-Z][A-Z0-9 ]+?)\s*\|\s*([0-9.]+)\s*\|", line)
        if not m:
            continue
        try:
            info[m.group(1).strip()] = float(m.group(2))
        except ValueError:
            continue
    _SMU_INFO_CACHE = info
    return info


def _tdp_limits_from_processor_db() -> Tuple[int, int, int]:
    """Return (min, max, default) TDP for the running processor.

    ``max`` is the ceiling the power slider offers. It comes from AMD's
    published cTDP range, because runtime probes cannot answer this: the
    SMU's ``PPT LIMIT APU`` reports the limit the firmware is *currently*
    set to, not what the silicon is rated for. On the Emdoor N161L that
    reads 70W against an AMD-published 45-120W range.

    ``default`` is the value shown when a profile carries no TDP. That is
    the live ``STAPM LIMIT``, so an untouched profile displays what the
    firmware actually shipped with rather than an invented number.

    ``min`` stays low even when the spec table gives a higher cTDP floor.
    Battery profiles are expected to go under the vendor minimum - it is
    proven to work on this hardware and is the point of the slider.

    Intel takes its bound from RAPL. Falls back to 4-25W when nothing is
    readable.
    """
    global _TDP_RANGE_CACHE
    if _TDP_RANGE_CACHE is not None:
        return _TDP_RANGE_CACHE

    tdp_min, tdp_max, default = 4, 25, 15

    rapl_path = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
    if _exists(rapl_path):
        try:
            watts = int(_read(rapl_path, "0")) // 1_000_000
            if watts > 0:
                tdp_min, tdp_max, default = 4, max(watts, 25), min(15, watts)
                _TDP_RANGE_CACHE = (tdp_min, tdp_max, default)
                return _TDP_RANGE_CACHE
        except (ValueError, OSError):
            pass

    # Spec ceiling for this exact part.
    try:
        from .hardware.processor_db import tdp_bounds

        bounds = tdp_bounds()
    except Exception:
        bounds = None
    if bounds and bounds.get("max"):
        tdp_max = max(bounds["max"], tdp_max)
        if bounds.get("default"):
            default = bounds["default"]

    info = _ryzenadj_smu_info()
    current = info.get("STAPM LIMIT")
    if current and current > 0:
        default = int(round(current))
    elif not bounds and tdp_max > 25:
        default = max(25, tdp_max // 2)

    default = max(tdp_min, min(default, tdp_max))
    _TDP_RANGE_CACHE = (tdp_min, tdp_max, default)
    return _TDP_RANGE_CACHE


def _tdp_burst_ceilings() -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Return (fast_max, slow_max, burst_delta) for the running processor.

    Only parts with measured values in the spec table return anything.
    AMD does not publish PPT fast/slow ceilings, so inventing them for
    every CPU would mean writing watts the silicon may refuse.
    """
    try:
        from .hardware.processor_db import find_running

        entry = find_running()
    except Exception:
        return None, None, None
    if not entry:
        return None, None, None

    def _int(key: str) -> Optional[int]:
        value = entry.get(key)
        return value if isinstance(value, int) and value > 0 else None

    return (
        _int("tdp_fast_limit_max"),
        _int("tdp_slow_limit_max"),
        _int("tdp_burst_delta"),
    )


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

    # CPU marketing name. This is what the spec table is keyed on, so the
    # UI and the TDP ceiling must agree on it.
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    caps.cpu_name = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass

    # CPU + SMT + cores
    caps.cpu_core_count = _count_cpu_cores()
    caps.max_cpu_cores = caps.cpu_core_count
    caps.supports_smt = _exists(SMT_CONTROL)
    caps.supports_cpu_boost = _exists(CPU_BOOST_PATH)
    caps.scaling_driver = _read_scaling_driver()

    # TDP limits
    caps.tdp_min, caps.tdp_max, caps.default_tdp = _tdp_limits_from_processor_db()
    caps.tdp_fast_max, caps.tdp_slow_max, caps.tdp_burst_delta = _tdp_burst_ceilings()

    # Fan
    caps.has_fan_control = any(
        _read(p) in ("steamfork_fan", "asus_custom_fan_curve", "oxp_ec")
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
            env=clean_env(),
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