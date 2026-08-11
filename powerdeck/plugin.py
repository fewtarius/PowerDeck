"""Plugin class.

Single source of truth for runtime state. The frontend gets state via
`get_state()` and writes via `apply_settings(partial)`. Other callables
(set_per_game_profiles_enabled, ROG Ally ops, controller ops, update
ops) are device-specific entry points that don't belong in the
profile merge path.
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

import decky_plugin

from . import capabilities, updates
from .device_controllers import rog_ally
from . import controller_emulation
from .hardware import (
    ac as ac_mod,
    battery as battery_mod,
    cpu as cpu_mod,
    fan as fan_mod,
    gpu as gpu_mod,
    platform_profile as platform_profile_mod,
    pstate as pstate_mod,
    tdp as tdp_mod,
    usb_pcie as usb_pcie_mod,
)
from .state import (
    GAME_DEFAULT_ID,
    PersistentSettings,
    PowerProfile,
    ProfileStore,
    default_profile,
    make_profile_id,
)


def _settings_dir() -> str:
    return decky_plugin.DECKY_PLUGIN_SETTINGS_DIR


class Plugin:
    """Holds in-memory state. One global instance is created at import time."""

    def __init__(self) -> None:
        self.settings_dir = _settings_dir()
        self.profile_store = ProfileStore(self.settings_dir)
        self.persistent = PersistentSettings(self.settings_dir)

        self.capabilities: Optional[capabilities.Capabilities] = None
        self.current_profile_id: str = f"{GAME_DEFAULT_ID}_ac"
        self.current_profile: PowerProfile = PowerProfile()

    # ── lifecycle ────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Initialise capability detection + load the active profile."""

        try:
            self.capabilities = capabilities.detect()
        except Exception:
            decky_plugin.logger.warning("capability detection failed; using defaults")
            self.capabilities = capabilities.Capabilities()

        # First-boot: pick a profile based on AC power. Subsequent boots
        # keep whatever profile was active last (caller persists the
        # choice to disk via PersistentSettings below).
        is_ac = ac_mod.get_ac_power_status()
        game_id = self.persistent.get("last_game_id", GAME_DEFAULT_ID)
        self.current_profile_id = make_profile_id(game_id, is_ac)

        profile = self.profile_store.load(self.current_profile_id)
        if profile is None:
            profile = default_profile(is_ac, self.capabilities.default_tdp,
                                      self.capabilities.min_gpu_freq,
                                      self.capabilities.max_gpu_freq)
            self.profile_store.save(self.current_profile_id, profile)
        self.current_profile = profile

        # Apply persisted advanced settings that aren't a profile field.
        charge = self.persistent.get("battery_charge_limit")
        if self.capabilities.battery_charge_limit_available and charge:
            battery_mod.set_limit(int(charge))

        # Apply persisted ROG Ally settings (these are device-level, not per-profile).
        if self.capabilities.rog_ally:
            mcu = self.persistent.get("rog_ally_mcu_powersave")
            if mcu is not None:
                rog_ally.set_mcu_powersave(bool(mcu))
            fan_modes = self.persistent.get("rog_ally_fan_mode") or {}
            for fan_id, mode in fan_modes.items():
                try:
                    rog_ally.set_fan_mode(int(fan_id), int(mode))
                except Exception:
                    continue

        # Apply the loaded profile to hardware. Without this, the SMU
        # keeps whatever BIOS default (typically 15-28W) until the user
        # touches a slider. The frontend already shows the saved values;
        # this call makes the hardware match.
        self._apply_profile_full(profile)

    def shutdown(self) -> None:
        pass

    # Decky lifecycle aliases - async wrappers around initialize/shutdown.
    async def _main(self) -> None:
        self.initialize()

    async def _unload(self) -> None:
        self.shutdown()

    # ── profile switching ───────────────────────────────────────────

    def switch_active_profile(self, profile_id: str) -> PowerProfile:
        """Switch the active profile id. Loads from disk or creates a default.

        Saves the previous profile back to its own id (with the in-memory
        profile object) before switching, so an in-progress slider drag
        doesn't get clobbered by the load.
        """
        if profile_id == self.current_profile_id:
            return self.current_profile

        # Save what we have before switching
        self.profile_store.save(self.current_profile_id, self.current_profile)

        loaded = self.profile_store.load(profile_id)
        if loaded is None:
            is_ac = profile_id.endswith("_ac")
            game_id = profile_id[: -len("_ac" if is_ac else "_battery")]
            loaded = default_profile(is_ac, self.capabilities.default_tdp if self.capabilities else 15,
                                     self.capabilities.min_gpu_freq if self.capabilities else 400,
                                     self.capabilities.max_gpu_freq if self.capabilities else 1600)
            self.profile_store.save(profile_id, loaded)

        self.current_profile_id = profile_id
        self.current_profile = loaded
        self._apply_profile_full(loaded)
        return loaded

    def _apply_profile_full(self, profile: PowerProfile) -> bool:
        """Apply every field of a profile to hardware. Used by switch_active_profile."""
        # TDP / native path
        self._apply_field("tdp", profile.tdp)
        # CPU
        self._apply_field("cpuBoost", profile.cpuBoost)
        self._apply_field("smt", profile.smt)
        self._apply_field("cpuCores", profile.cpuCores)
        self._apply_field("governor", profile.governor)
        self._apply_field("epp", profile.epp)
        self._apply_field("fanProfile", profile.fanProfile)
        # GPU
        self._apply_field("gpuMode", profile.gpuMode)
        if profile.gpuMode == "range":
            self._apply_field("gpuFreqMin", profile.gpuFreqMin)
            self._apply_field("gpuFreqMax", profile.gpuFreqMax)
        elif profile.gpuMode == "fixed":
            self._apply_field("gpuFreqFixed", profile.gpuFreqFixed)
        # Advanced
        self._apply_field("usbAutosuspend", profile.usbAutosuspend)
        self._apply_field("pcieAspm", profile.pcieAspm)
        self._apply_field("pciRuntimePm", profile.pciRuntimePm)
        self._apply_field("wifiPowerSave", profile.wifiPowerSave)
        # Platform profile / ROG Ally extras
        if profile.platformProfile:
            self._apply_field("platformProfile", profile.platformProfile)
        if profile.thermalPolicy is not None:
            self._apply_field("thermalPolicy", profile.thermalPolicy)
        if profile.pstateMode:
            self._apply_field("pstateMode", profile.pstateMode)
        return True

    # ── per-field writer ────────────────────────────────────────────

    def _apply_field(self, key: str, value: Any) -> bool:
        """Apply a single profile field to hardware. Returns True on success."""
        if value is None:
            return True
        try:
            return self._applier(key)(value)
        except Exception as e:
            decky_plugin.logger.warning(f"apply {key}={value} failed: {e}\n{traceback.format_exc()}")
            return False

    def _applier(self, key: str):
        """Return a callable that writes the field for the matching key."""
        if key == "tdp":
            return self._apply_tdp
        if key == "cpuBoost":
            return cpu_mod.set_boost
        if key == "smt":
            return cpu_mod.set_smt
        if key == "cpuCores":
            return cpu_mod.set_online_cores
        if key == "governor":
            return cpu_mod.set_governor
        if key == "epp":
            return lambda v: cpu_mod.set_epp(v, governor="schedutil")
        if key == "fanProfile":
            return fan_mod.set_profile
        if key == "gpuMode":
            return gpu_mod.set_mode
        if key == "gpuFreqMin":
            return self._apply_gpu_min
        if key == "gpuFreqMax":
            return self._apply_gpu_max
        if key == "gpuFreqFixed":
            return gpu_mod.set_freq_fixed
        if key == "usbAutosuspend":
            return usb_pcie_mod.set_usb_autosuspend
        if key == "pcieAspm":
            return self._apply_pcie_aspm
        if key == "pciRuntimePm":
            return usb_pcie_mod.set_pci_runtime_pm
        if key == "wifiPowerSave":
            return usb_pcie_mod.set_wifi_power_save
        if key == "platformProfile":
            return self._apply_platform_profile
        if key == "thermalPolicy":
            return rog_ally.set_thermal_policy
        if key == "pstateMode":
            return pstate_mod.set_mode
        if key == "chargeLimit":
            return battery_mod.set_limit
        return lambda _v: True

    def _apply_tdp(self, watts: int) -> bool:
        caps = self.capabilities
        if not caps:
            return False
        if caps.power_control.active_method == "platform_profile" and not caps.power_control.native_tdp_available:
            # When ACPI owns TDP, the watt-level slider is software-mapped.
            return self._apply_tdp_soft(int(watts))
        return tdp_mod.set_tdp(int(watts), prefer_native=True)[0]

    def _apply_tdp_soft(self, watts: int) -> bool:
        """Map watts to governor+EPP when no native TDP path exists."""
        if watts <= 8:
            cpu_mod.set_governor("powersave")
            cpu_mod.set_epp("power", governor="powersave")
        elif watts <= 18:
            cpu_mod.set_governor("schedutil")
            cpu_mod.set_epp("balance_power", governor="schedutil")
        else:
            cpu_mod.set_governor("performance")
            cpu_mod.set_epp("performance", governor="performance")
        return True

    def _apply_gpu_min(self, mhz: int) -> bool:
        return gpu_mod.set_freq_range(int(mhz), int(self.current_profile.gpuFreqMax))

    def _apply_gpu_max(self, mhz: int) -> bool:
        return gpu_mod.set_freq_range(int(self.current_profile.gpuFreqMin), int(mhz))

    def _apply_pcie_aspm(self, enabled: bool) -> bool:
        return usb_pcie_mod.set_pcie_aspm_policy("powersave" if enabled else "default")

    def _apply_platform_profile(self, profile: str) -> bool:
        if self.capabilities and self.capabilities.rog_ally and self.capabilities.rog_ally.controls.platform_profiles:
            return rog_ally.set_platform_profile(profile)
        return platform_profile_mod.set_profile(profile)

    # ── callables ───────────────────────────────────────────────────

    async def get_state(self) -> Dict[str, Any]:
        """Snapshot bundle returned to the frontend on open."""
        caps = self.capabilities or capabilities.Capabilities()
        ac = ac_mod.get_ac_power_status()
        return {
            "plugin_version": updates.current_version(),
            "plugin_loader_restart_in_progress": False,
            "device_info": caps.to_dict(),
            "ac_power": ac,
            "per_game_profiles_enabled": self.persistent.get("per_game_profiles_enabled", True),
            "update_status": updates.get_update_status(),
            "defaults": {
                "tdp": caps.default_tdp,
                "gpu_freq_min": caps.min_gpu_freq,
                "gpu_freq_max": caps.max_gpu_freq,
            },
            "capabilities": {
                "governors": cpu_mod.available_governors(),
                "fan_profiles": fan_mod.available_profiles(),
                "tdp_limits": {"min": caps.tdp_min, "max": caps.tdp_max},
                "tdp_control": self._tdp_control_availability(caps),
                "pstate": self._pstate_caps(),
                "battery_charge_limit": battery_mod.get_limit(),
                "usb_autosuspend": usb_pcie_mod.get_usb_autosuspend_status(),
                "pci_runtime_pm": usb_pcie_mod.get_pci_runtime_pm_status(),
                "wifi_power_save": usb_pcie_mod.get_wifi_power_save(),
                "pcie_aspm_policy": usb_pcie_mod.get_pcie_aspm_policy(),
                "controller": controller_emulation.get_status(),
                "rog_ally": (
                    {
                        "device_name": caps.rog_ally.device_name,
                        "available_controls": {
                            k: getattr(caps.rog_ally.controls, k)
                            for k in ("fan_control", "thermal_policy", "mcu_powersave", "power_limits",
                                       "platform_profiles", "battery_charge_limit")
                        },
                    }
                    if caps.rog_ally else None
                ),
                "rog_ally_platform_profile": rog_ally.get_platform_profile(),
                "rog_ally_thermal_policy": rog_ally.get_thermal_policy(),
                "rog_ally_mcu_powersave": rog_ally.get_mcu_powersave(),
                "rog_ally_fan_status": rog_ally.get_fan_status(),
            },
            "current_profile_id": self.current_profile_id,
            "current_profile": self.current_profile.to_dict(),
        }

    async def apply_settings(self, partial: Dict[str, Any]) -> bool:
        """Apply a partial set of fields. May also carry `target_profile_id`
        as a top-level entry to switch the active profile id.

        A hardware-writing failure is logged but does not flip the
        return value when the device lacks the backing sysfs entry -
        the value is still saved to the profile for when the device
        gains the capability. Frontend visibility is gated by
        Capabilities so this is a defensive measure only.
        """
        if not isinstance(partial, dict):
            return False
        target = partial.pop("target_profile_id", None) or self.current_profile_id
        if isinstance(target, str) and target and target != self.current_profile_id:
            self.switch_active_profile(target)

        any_failure = False
        for key, value in partial.items():
            if value is None:
                continue
            setattr(self.current_profile, key, value)
            if key == "chargeLimit":
                self.persistent.set("battery_charge_limit", int(value))
                ok = battery_mod.set_limit(int(value))
                if not ok:
                    any_failure = True
                continue
            if key in self.current_profile.to_dict():
                if not self._apply_field(key, value):
                    any_failure = True
        self.profile_store.save(self.current_profile_id, self.current_profile)
        if any_failure:
            decky_plugin.logger.warning("apply_settings: some fields had no backing sysfs")
        return True

    async def set_per_game_profiles_enabled(self, enabled: bool) -> bool:
        self.persistent.set("per_game_profiles_enabled", bool(enabled))
        if not enabled:
            state = await self.get_state()
            self.current_profile_id = make_profile_id(GAME_DEFAULT_ID, state["ac_power"])
            self.persistent.set("last_game_id", GAME_DEFAULT_ID)
        return True

    async def set_controller_mode(self, mode: str) -> bool:
        return controller_emulation.set_mode(mode)

    async def get_ac_power_status(self) -> bool:
        return ac_mod.get_ac_power_status()

    async def set_rog_ally_platform_profile(self, profile: str) -> bool:
        return await self.apply_settings({"platformProfile": profile})

    async def set_rog_ally_fan_mode(self, fan_id: int, mode: int) -> bool:
        ok = rog_ally.set_fan_mode(int(fan_id), int(mode))
        if ok:
            existing = self.persistent.get("rog_ally_fan_mode", {}) or {}
            existing[str(fan_id)] = int(mode)
            self.persistent.set("rog_ally_fan_mode", existing)
        return ok

    async def set_rog_ally_mcu_powersave(self, enabled: bool) -> bool:
        ok = rog_ally.set_mcu_powersave(bool(enabled))
        if ok:
            self.persistent.set("rog_ally_mcu_powersave", bool(enabled))
        return ok

    async def set_rog_ally_thermal_policy(self, policy: int) -> bool:
        return await self.apply_settings({"thermalPolicy": int(policy)})

    async def set_battery_charge_limit(self, limit: int) -> bool:
        return await self.apply_settings({"chargeLimit": int(limit)})

    # ── updates ─────────────────────────────────────────────────────

    async def get_current_version(self) -> str:
        return updates.current_version()

    async def check_for_updates(self) -> dict:
        return updates.check_for_updates()

    async def stage_update(self, download_url: str, version: str) -> dict:
        return updates.stage_update(download_url, version)

    async def install_staged_update(self) -> dict:
        return updates.install_staged_update()

    async def get_update_status(self) -> dict:
        return updates.get_update_status()

    async def update_plugin(self) -> bool:
        return updates.update_plugin()

    # ── helpers ─────────────────────────────────────────────────────

    def _tdp_control_availability(self, caps: capabilities.Capabilities) -> Dict[str, Any]:
        native = caps.power_control.native_tdp_available
        soft = caps.power_control.active_method == "platform_profile"
        if native:
            available = True
            method = "native_tdp"
            reason = caps.power_control.reason
        elif caps.gpu_vendor == "intel":
            available = True
            method = "intel_rapl"
            reason = "Intel RAPL exposed"
        elif caps.power_control.platform_profile_available:
            available = True
            method = "platform_profile"
            reason = caps.power_control.reason
        else:
            available = False
            method = "soft"
            reason = caps.power_control.reason or "no native TDP path"

        return {
            "available": available,
            "method": method,
            "has_soft_control": soft,
            "reason": reason,
        }

    def _pstate_caps(self) -> Optional[Dict[str, Any]]:
        if not pstate_mod.is_available():
            return None
        caps = self.capabilities
        epp_preferences = (
            caps.pstate.epp_preferences
            if caps and caps.pstate and caps.pstate.epp_preferences
            else cpu_mod.available_epp()
        )
        available_governors = (
            caps.pstate.available_governors
            if caps and caps.pstate and caps.pstate.available_governors
            else cpu_mod.available_governors()
        )
        return {
            "current_mode": pstate_mod.get_mode(),
            "available_modes": ["active", "passive", "guided"],
            "available_governors": available_governors,
            "epp_available": pstate_mod.get_mode() == "active",
            "epp_preferences": epp_preferences,
            "mode_switch_supported": True,
        }
