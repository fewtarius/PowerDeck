"""Plugin class.

Single source of truth for runtime state. The frontend gets state via
`get_state()` and writes via `apply_settings(partial)`. Other callables
(set_per_game_profiles_enabled, ROG Ally ops, controller ops, update
ops) are device-specific entry points that don't belong in the
profile merge path.
"""

from __future__ import annotations

import re
import signal
import subprocess
import threading
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

        # Backend game monitor state
        self._game_monitor_thread: Optional[threading.Thread] = None
        self._game_monitor_stop = threading.Event()
        self._last_detected_game_id: Optional[str] = None
        self._last_ac_power_state: Optional[bool] = None
        # Guard profile state against concurrent access from the monitor
        # thread and the asyncio callable handlers (get_state, apply_settings).
        # RLock allows re-entrant acquisition (e.g. apply_settings -> switch_active_profile).
        self._profile_lock = threading.RLock()

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

        # Seed the last-known game/AC state so the monitor's first tick can
        # detect a transition instead of immediately re-applying the current
        # profile. Only seed the game id when per-game profiles are enabled.
        self._last_ac_power_state = is_ac
        if self.persistent.get("per_game_profiles_enabled", True):
            self._last_detected_game_id = self.persistent.get(
                "last_game_id", GAME_DEFAULT_ID
            )
        else:
            self._last_detected_game_id = GAME_DEFAULT_ID

    def shutdown(self) -> None:
        pass

    # Decky lifecycle aliases - async wrappers around initialize/shutdown.
    async def _main(self) -> None:
        self.initialize()
        # Start the backend game monitor so profiles are applied even
        # when the Decky overlay is not open. The old monolith had this;
        # the rewrite dropped it, causing profiles to never switch on
        # game launch unless the user opened the settings UI.
        # Uses a dedicated daemon thread (not asyncio) so the poll loop
        # survives even if there are no RPC calls to keep the asyncio
        # event loop active.
        self._game_monitor_stop.clear()
        self._game_monitor_thread = threading.Thread(
            target=self._game_monitor, daemon=True, name="GameMonitor"
        )
        self._game_monitor_thread.start()
        decky_plugin.logger.info("Backend game monitor thread started")

    async def _unload(self) -> None:
        self._game_monitor_stop.set()
        if self._game_monitor_thread is not None:
            # Wait up to 3× the poll interval for a clean exit so
            # Decky doesn't SIGKILL us on every shutdown.
            self._game_monitor_thread.join(timeout=5)
        self._game_monitor_thread = None
        self.shutdown()

    # ── backend game monitor ────────────────────────────────────────────

    GAME_POLL_INTERVAL_S = 5

    def _detect_running_game_appid(self) -> str:
        """Scan the process table for a launched Steam game.

        Looks for ``SteamLaunch AppId=NNNNNN`` in ``ps aux`` output.
        Returns ``"00000000"`` when no game is running or detection fails.
        """
        try:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=3
            )
        except Exception:
            return GAME_DEFAULT_ID
        match = re.search(r"SteamLaunch AppId=(\d+)", result.stdout)
        if not match:
            return GAME_DEFAULT_ID
        raw = match.group(1)
        # AppId 0/1 means desktop / system, treat as no game.
        return GAME_DEFAULT_ID if raw in ("0", "1") else raw

    def _game_monitor(self) -> None:
        """Poll for running Steam games + AC power changes and apply
        the matching profile.

        This replaces the legacy ``game_monitor()`` coroutine that was
        removed in the rewrite. Without it, per-game profiles are only
        applied when the Decky overlay is open (the frontend polling
        loop in SettingsProvider.tsx), so launching a game and playing
        without opening the overlay leaves the hardware at whatever
        default state it was in -- typically a much higher TDP, causing
        excess power draw on battery.

        Runs in a daemon thread so it survives even when the asyncio
        event loop is idle (no RPC calls to keep it awake).
        """
        decky_plugin.logger.info("Backend game monitor thread running")
        while not self._game_monitor_stop.is_set():
            if self._game_monitor_stop.wait(timeout=self.GAME_POLL_INTERVAL_S):
                break
            try:
                game_id = self._detect_running_game_appid()
                ac = ac_mod.get_ac_power_status()
                per_game = self.persistent.get("per_game_profiles_enabled", True)

                effective_game_id = game_id if per_game else GAME_DEFAULT_ID

                game_changed = effective_game_id != self._last_detected_game_id
                ac_changed = (
                    self._last_ac_power_state is not None
                    and ac != self._last_ac_power_state
                )

                if not game_changed and not ac_changed:
                    continue

                if game_changed:
                    decky_plugin.logger.info(
                        f"Game monitor: game changed "
                        f"{self._last_detected_game_id!r} -> {effective_game_id!r}"
                    )
                if ac_changed:
                    prev = self._last_ac_power_state
                    decky_plugin.logger.info(
                        f"Game monitor: AC power changed "
                        f"{'AC' if prev else 'Battery'} -> "
                        f"{'AC' if ac else 'Battery'}"
                    )

                self._last_detected_game_id = effective_game_id
                self._last_ac_power_state = ac

                # Persist the last game id so initialize() can resume
                # the right profile after a plugin restart.
                self.persistent.set("last_game_id", effective_game_id)

                profile_id = make_profile_id(effective_game_id, ac)
                self.switch_active_profile(profile_id)
            except Exception as exc:
                decky_plugin.logger.warning(
                    f"Game monitor poll error (non-fatal): {exc}"
                )
        decky_plugin.logger.info("Backend game monitor thread stopped")

    # ── profile switching ───────────────────────────────────────────

    def switch_active_profile(self, profile_id: str) -> PowerProfile:
        """Switch the active profile id. Loads from disk or creates a default.

        Saves the previous profile back to its own id (with the in-memory
        profile object) before switching, so an in-progress slider drag
        doesn't get clobbered by the load.
        """
        with self._profile_lock:
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
            profile_to_apply = loaded

        # Apply outside the lock to avoid holding it during slow hardware I/O.
        self._apply_profile_full(profile_to_apply)
        return profile_to_apply

    def _apply_profile_full(self, profile: PowerProfile) -> bool:
        """Apply every field of a profile to hardware. Used by switch_active_profile."""
        # P-State mode must be applied FIRST — on classic amd-pstate,
        # EPP sysfs files only exist in active mode.  Applying EPP before
        # the mode switch causes the EPP write to silently fail.
        if profile.pstateMode:
            self._apply_field("pstateMode", profile.pstateMode)
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
            return cpu_mod.set_epp  # auto-selects best governor for swap
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
        native = caps.power_control.native_tdp_available
        platform = caps.power_control.platform_profile_available
        if platform and not native:
            # ACPI platform_profile owns the watt level; map watts to
            # governor/EPP so the soft slider has a real effect.
            return self._apply_tdp_soft(int(watts))
        if native:
            return tdp_mod.set_tdp(int(watts), prefer_native=True)[0]
        if caps.gpu_vendor == "intel":
            # Intel exposes RAPL on platform_profile-less devices.
            return tdp_mod.set_tdp(int(watts), prefer_native=False)[0]
        # No native TDP path at all (Secure Boot + no ACPI + no RAPL):
        # fall back to the governor/EPP soft mapping. This is the case
        # _tdp_control_availability labels method="soft".
        return self._apply_tdp_soft(int(watts))

    def _apply_tdp_soft(self, watts: int) -> bool:
        """Map watts to governor+EPP when no native TDP path exists."""
        swap_gov = cpu_mod._best_epp_governor() or "schedutil"
        if watts <= 8:
            cpu_mod.set_governor("powersave" if "powersave" in cpu_mod.available_governors() else swap_gov)
            cpu_mod.set_epp("power", governor=cpu_mod._best_epp_governor())
        elif watts <= 18:
            cpu_mod.set_governor(swap_gov)
            cpu_mod.set_epp("balance_power", governor=cpu_mod._best_epp_governor())
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

        A hardware-writing failure is logged, the rejected field is NOT
        persisted (so the saved profile keeps matching what the hardware
        actually accepted), and the call returns False so the frontend
        can revert its optimistic view. Returning True unconditionally
        here previously let failed writes (e.g. Secure Boot blocking
        ryzenadj) be saved as "applied", leaving the slider thumb and the
        hardware reading out of sync until the next reload.
        """
        if not isinstance(partial, dict):
            return False
        target = partial.pop("target_profile_id", None) or self.current_profile_id
        # Snapshot identity + profile reference under the lock to avoid
        # races with the monitor thread's switch_active_profile.
        with self._profile_lock:
            if isinstance(target, str) and target and target != self.current_profile_id:
                self.switch_active_profile(target)
            profile_id = self.current_profile_id
            profile_data = self.current_profile

        any_failure = False
        # Cache the set of known profile fields once (to_dict is cheap but
        # avoids re-serializing per field). Charge-limit is device-level
        # (not a profile field) and is persisted separately.
        profile_fields = set(profile_data.to_dict().keys())
        for key, value in partial.items():
            if value is None:
                continue
            if key == "chargeLimit":
                self.persistent.set("battery_charge_limit", int(value))
                ok = battery_mod.set_limit(int(value))
                if not ok:
                    any_failure = True
                continue
            if key not in profile_fields:
                # Unknown field - ignore defensively (don't write to disk).
                continue
            # Write hardware FIRST. Only commit the value to the in-memory
            # profile (+ later to disk) when the write actually succeeded,
            # so a rejected value can't overwrite a good one.
            if not self._apply_field(key, value):
                any_failure = True
                decky_plugin.logger.warning(
                    f"apply_settings: {key}={value} not applied (no backing sysfs)"
                )
                continue
            setattr(profile_data, key, value)
        self.profile_store.save(profile_id, profile_data)
        if any_failure:
            decky_plugin.logger.warning("apply_settings: some fields were not applied")
        return not any_failure

    async def set_per_game_profiles_enabled(self, enabled: bool) -> bool:
        self.persistent.set("per_game_profiles_enabled", bool(enabled))
        if not enabled:
            state = await self.get_state()
            self.current_profile_id = make_profile_id(GAME_DEFAULT_ID, state["ac_power"])
            self.persistent.set("last_game_id", GAME_DEFAULT_ID)
            # Apply the base profile so hardware immediately reflects
            # the non-per-game setting without waiting for the monitor.
            self.switch_active_profile(self.current_profile_id)
            # Update monitor seed so it doesn't immediately re-switch.
            self._last_detected_game_id = GAME_DEFAULT_ID
        elif self._last_detected_game_id == GAME_DEFAULT_ID:
            # Re-enabling per-game: seed from the persisted last game so
            # the monitor applies the right profile on its next tick if one
            # is running.
            self._last_detected_game_id = self.persistent.get(
                "last_game_id", GAME_DEFAULT_ID
            )
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
        # Branch order mirrors the active-method detection in
        # capabilities._detect_power_control_method so the availability
        # dict the frontend reads stays in lockstep with _apply_tdp.
        native = caps.power_control.native_tdp_available
        platform = caps.power_control.platform_profile_available

        if native:
            available = True
            method = "native_tdp"
            reason = caps.power_control.reason
            has_soft = False
        elif caps.gpu_vendor == "intel":
            available = True
            method = "intel_rapl"
            reason = "Intel RAPL exposed"
            has_soft = False
        elif platform:
            # ACPI platform_profile owns the watt-level slider, so the
            # software soft-fallback must NOT be advertised (the
            # PlatformProfileSection owns this surface instead).
            available = True
            method = "platform_profile"
            reason = caps.power_control.reason
            has_soft = False
        else:
            # No native path, no ACPI, no Intel RAPL: the only thing we
            # can do is map watts -> governor/EPP via _apply_tdp_soft.
            # has_soft_control MUST be True here so the frontend's
            # `!available && has_soft_control` gate actually renders the
            # soft slider. (Previously this was `soft = active_method ==
            # "platform_profile"`, which reported False here and True in
            # the branch above where it must be False -- exactly inverted.)
            available = False
            method = "soft"
            reason = caps.power_control.reason or "no native TDP path"
            has_soft = True

        return {
            "available": available,
            "method": method,
            "has_soft_control": has_soft,
            "reason": reason,
        }

    def _pstate_caps(self) -> Optional[Dict[str, Any]]:
        if not pstate_mod.is_available():
            return None
        caps = self.capabilities
        current_mode = pstate_mod.get_mode()
        # EPP is honored in active mode on both amd-pstate and amd-pstate-epp.
        # Use runtime detection (reads sysfs now) rather than the static caps
        # detected at init, so mode switches via the UI are reflected
        # immediately without waiting for a restart.
        epp_available = current_mode == "active"
        if epp_available:
            runtime_prefs = cpu_mod.available_epp()
            epp_preferences = runtime_prefs if runtime_prefs else (
                caps.pstate.epp_preferences
                if caps and caps.pstate and caps.pstate.epp_preferences
                else ["power", "balance_power", "balance_performance", "performance"]
            )
        else:
            epp_preferences = []
        available_governors = (
            caps.pstate.available_governors
            if caps and caps.pstate and caps.pstate.available_governors
            else cpu_mod.available_governors()
        )
        return {
            "current_mode": current_mode,
            "available_modes": ["active", "passive", "guided"],
            "available_governors": available_governors,
            "epp_available": epp_available,
            "epp_preferences": epp_preferences,
            "mode_switch_supported": True,
        }
