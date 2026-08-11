"""
State management:
  - PowerProfile dataclass - one per (game_id, is_ac) pair
  - PersistentSettings - JSON-backed plugin settings (per_game_enabled, plugin_version data)
  - ProfileStore - on-disk persistence under <settings_dir>/profiles/
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


GAME_DEFAULT_ID = "00000000"


def make_profile_id(game_id: str, is_ac: bool) -> str:
    safe = "".join(c for c in game_id if c.isalnum() or c in ("-", "_")) or GAME_DEFAULT_ID
    return f"{safe}_{'ac' if is_ac else 'battery'}"


@dataclass
class PowerProfile:
    tdp: int = 15
    cpuBoost: bool = True
    cpuCores: int = 8
    governor: str = "schedutil"
    fanProfile: str = "moderate"
    smt: bool = True
    epp: str = "balance_performance"
    gpuMode: str = "auto"
    gpuFreqMin: int = 400
    gpuFreqMax: int = 1600
    gpuFreqFixed: int = 1000
    wifiPowerSave: bool = False
    usbAutosuspend: bool = False
    pcieAspm: bool = False
    pciRuntimePm: bool = False
    platformProfile: Optional[str] = None
    thermalPolicy: Optional[int] = None
    pstateMode: Optional[str] = None
    lastUpdated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def default_profile(is_ac: bool, default_tdp: int = 15, gpu_min: int = 400, gpu_max: int = 1600) -> PowerProfile:
    """Return a sensible default profile. AC = balanced, battery = power-biased.

    schedutil+balance_performance on AC; schedutil+balance_power on battery.
    governor=performance only exposes EPP=performance under amd-pstate-epp
    and silently wastes power on most APUs.
    """
    if is_ac:
        return PowerProfile(
            tdp=default_tdp,
            cpuCores=8,
            governor="schedutil",
            fanProfile="moderate",
            smt=True,
            epp="balance_performance",
            gpuMode="auto",
            gpuFreqMin=gpu_min,
            gpuFreqMax=gpu_max,
            gpuFreqFixed=(gpu_min + gpu_max) // 2,
        )
    return PowerProfile(
        tdp=default_tdp,
        cpuCores=8,
        governor="schedutil",
        fanProfile="quiet",
        smt=True,
        epp="balance_power",
        gpuMode="battery",
        gpuFreqMin=gpu_min,
        gpuFreqMax=max(gpu_min + 100, int(gpu_max * 0.8)),
        gpuFreqFixed=max(gpu_min + 50, int((gpu_min + gpu_max) * 0.4)),
    )


class ProfileStore:
    """JSON-on-disk persistence for profiles and plugin settings.

    Layout:
      <settings_dir>/
        settings.json                 - plugin-level settings (per_game_profiles_enabled ...)
        profiles/<profile_id>.json    - one profile per (game, ac/battery) pair
        inputplumber/<profile_id>.json - InputPlumber per-game mode (legacy)
    """

    def __init__(self, settings_dir: str):
        self.settings_dir = settings_dir
        self.profile_dir = os.path.join(settings_dir, "profiles")
        self.inputplumber_dir = os.path.join(settings_dir, "inputplumber")
        os.makedirs(self.profile_dir, exist_ok=True)
        os.makedirs(self.inputplumber_dir, exist_ok=True)

    def _path(self, profile_id: str) -> str:
        return os.path.join(self.profile_dir, f"{profile_id}.json")

    def load(self, profile_id: str) -> Optional[PowerProfile]:
        try:
            with open(self._path(profile_id), "r") as f:
                raw = json.load(f)
            return PowerProfile(**{k: v for k, v in raw.items() if k in PowerProfile.__dataclass_fields__})
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def save(self, profile_id: str, profile: PowerProfile) -> bool:
        try:
            os.makedirs(self.profile_dir, exist_ok=True)
            tmp = self._path(profile_id) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(profile.to_dict(), f, indent=2)
            os.replace(tmp, self._path(profile_id))
            return True
        except Exception:
            return False

    def list_profiles(self) -> list[str]:
        try:
            return sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(self.profile_dir)
                if f.endswith(".json")
            )
        except OSError:
            return []


class PersistentSettings:
    """JSON-backed plugin-level settings (the keys are stable across versions)."""

    DEFAULTS: Dict[str, Any] = {
        "per_game_profiles_enabled": True,
        "rog_ally_native_tdp_enabled": False,
        "inputplumber_default_mode": "default",
        "battery_charge_limit": 100,
        "rog_ally_mcu_powersave": None,
        "rog_ally_fan_mode": None,
    }

    def __init__(self, settings_dir: str):
        self.path = os.path.join(settings_dir, "settings.json")
        self._data: Dict[str, Any] = dict(self.DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r") as f:
                raw = json.load(f)
            for key, value in raw.items():
                if key in self.DEFAULTS:
                    self._data[key] = value
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key in self.DEFAULTS:
            self._data[key] = value
        else:
            self._data[key] = value
        self.save()
