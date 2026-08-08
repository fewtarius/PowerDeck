"""
PowerDeck - Generic Battery Charge Management

Provides battery charge limit control for any system that exposes the
standard Linux power_supply sysfs interface:

    /sys/class/power_supply/BAT*/charge_control_end_threshold

This file is part of the kernel power_supply subsystem (drivers/power/supply/)
and is exposed by:

  - ASUS ROG Ally / Ally X (asus-battery)
  - Nimo Axis N161L (Emdoor / "emdoor-charge")
  - Lenovo Legion Go, Legion Go S, Lenovo laptops (ideapad_battery,
    lenovo_battery)
  - Framework laptops (framework_laptop)
  - ThinkPad / ThinkBooks with `ideapad_laptop` or similar drivers
  - Galaxy Book / Samsung laptops
  - Many other modern AMD/Intel handhelds and laptops

This module replaces the prior ROG-Ally-specific charge-control code with a
generic capability-driven implementation. Devices that do not expose the
interface (no BAT* entries with charge_control_end_threshold) report
`available=False` and every setter is a no-op returning False.

PowerDeck ships with the `root` plugin flag, so the writes are always
performed as root and the per-user `os.access(W_OK)` check is bypassed for
the writability probe - we instead probe whether the kernel accepts writes
on this hardware by issuing a real write (followed by an immediate rollback
to the prior value).

Copyright (C) 2026 Fewtarius
License: GPL-3.0
"""

import glob
import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import decky_plugin
    logger = decky_plugin.logger
except ImportError:  # Fallback for unit tests / standalone runs
    import logging
    logger = logging.getLogger("PowerDeck.battery")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler())


# Standard Linux power_supply sysfs path for the charge end threshold.
_CHARGE_END_GLOB = "/sys/class/power_supply/BAT*/charge_control_end_threshold"

# Valid bounds for the charge end threshold. The kernel accepts 0..100 in
# some firmwares and 20..100 in others - ROG Ally firmware rejects
# anything below 20 with EINVAL, so we clamp to 20..100 by default.
DEFAULT_LIMIT_MIN = 20
DEFAULT_LIMIT_MAX = 100


@dataclass
class BatteryCapabilities:
    """Capability snapshot returned by BatteryManager.get_capabilities().

    `available` is True if at least one BAT* entry exposes
    charge_control_end_threshold and is writable as root. The other
    fields describe the discovered paths.
    """

    available: bool = False
    batteries: List[str] = field(default_factory=list)
    paths: Dict[str, str] = field(default_factory=dict)
    min_limit: int = DEFAULT_LIMIT_MIN
    max_limit: int = DEFAULT_LIMIT_MAX


class BatteryManager:
    """Generic battery charge limit manager.

    Auto-detects all /sys/class/power_supply/BAT* entries at construction
    time and probes writability as root. Read/write methods operate on
    the first writable battery unless an explicit battery name is
    passed (e.g. "BAT0").

    Usage:

        mgr = BatteryManager()
        if mgr.is_available():
            mgr.set_charge_limit(80)
            print(mgr.get_charge_limit())   # 80
    """

    def __init__(self) -> None:
        self._paths: Dict[str, str] = {}
        self._writable: Dict[str, bool] = {}

        # Discover all BAT* directories that expose the end threshold.
        self._batteries: List[str] = []
        for charge_end in sorted(glob.glob(_CHARGE_END_GLOB)):
            bat_dir = os.path.dirname(charge_end)  # /sys/class/power_supply/BAT0
            bat_name = os.path.basename(bat_dir)
            self._batteries.append(bat_name)
            self._paths[bat_name] = charge_end
            self._writable[bat_name] = self._probe_writable(charge_end)

        if self._batteries:
            logger.info(
                f"BatteryManager: discovered {len(self._batteries)} battery(ies): "
                f"{self._batteries}, "
                f"writable={[b for b, w in self._writable.items() if w]}"
            )

    # ── Capability API ────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True if at least one battery exposes a writable charge_control_end_threshold."""
        return any(self._writable.values())

    def get_capabilities(self) -> BatteryCapabilities:
        caps = BatteryCapabilities(
            available=self.is_available(),
            batteries=list(self._batteries),
            paths=dict(self._paths),
            min_limit=DEFAULT_LIMIT_MIN,
            max_limit=DEFAULT_LIMIT_MAX,
        )
        return caps

    # ── Charge limit (end threshold) ─────────────────────────────────

    def set_charge_limit(self, limit: int, battery: Optional[str] = None) -> bool:
        """Set charge end threshold (percent). Returns False on failure.

        Values outside [DEFAULT_LIMIT_MIN, DEFAULT_LIMIT_MAX] are rejected
        client-side to avoid the kernel rejecting the write with EINVAL
        (some firmware clamps the minimum to 20).
        """
        if not DEFAULT_LIMIT_MIN <= limit <= DEFAULT_LIMIT_MAX:
            logger.error(
                f"BatteryManager: invalid charge limit {limit}% "
                f"(must be {DEFAULT_LIMIT_MIN}-{DEFAULT_LIMIT_MAX}%)"
            )
            return False

        path = self._resolve_path(battery)
        if path is None:
            logger.warning(
                f"BatteryManager.set_charge_limit({limit}): no writable "
                f"charge_control_end_threshold found"
            )
            return False

        success = self._write_sysfs(path, str(limit))
        if success:
            logger.info(
                f"BatteryManager: charge end threshold set to {limit}% "
                f"({os.path.basename(os.path.dirname(path))})"
            )
        return success

    def get_charge_limit(self, battery: Optional[str] = None) -> Optional[int]:
        """Read current charge end threshold.

        Some firmware returns 0 when "no limit is set" - we map that to 100
        to match the user-visible "full charge" semantics.
        """
        path = self._resolve_path(battery, require_writable=False)
        if path is None:
            return None

        raw = self._read_sysfs(path)
        if raw is None:
            return None
        try:
            val = int(raw)
        except ValueError:
            logger.warning(f"BatteryManager: unparseable charge limit '{raw}' at {path}")
            return None
        return 100 if val == 0 else val

    # ── Internals ──────────────────────────────────────────────────────

    def _resolve_path(self, battery: Optional[str], require_writable: bool = True) -> Optional[str]:
        if not self._paths:
            return None

        if battery is not None:
            path = self._paths.get(battery)
            if path is None:
                return None
            if require_writable and not self._writable.get(battery, False):
                return None
            return path

        # Pick the first writable entry; if none are writable, fall back
        # to the first entry (a read may still succeed even if writes are
        # blocked, which the caller can handle via the read API).
        for name, path in self._paths.items():
            if self._writable.get(name, False):
                return path
        if not require_writable:
            return next(iter(self._paths.values()), None)
        return None

    def _probe_writable(self, path: str) -> bool:
        """Determine whether the sysfs file accepts writes as root.

        We perform a real read-then-write-then-restore roundtrip so the
        probe reflects actual hardware/firmware behaviour, not just file
        permissions. PowerDeck runs as root (`flags: ["root"]` in
        plugin.json), so lack of user write permission is not a barrier.
        """
        if not os.path.exists(path):
            return False

        original = self._read_sysfs(path)
        if original is None:
            return False

        # Try writing the same value back (no-op semantically). If the
        # kernel rejects it, the hardware doesn't actually support writes
        # for this firmware build.
        if not self._write_sysfs(path, original):
            logger.debug(
                f"BatteryManager: {path} reports writability probe failure"
            )
            return False

        # Restore in case the write changed something - it shouldn't, but
        # be safe.
        return self._write_sysfs(path, original)

    @staticmethod
    def _read_sysfs(path: str) -> Optional[str]:
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except OSError as e:
            logger.debug(f"BatteryManager: read failed for {path}: {e}")
            return None

    @staticmethod
    def _write_sysfs(path: str, value: str) -> bool:
        """Write value to sysfs path as root.

        Falls back to `tee` if a direct write raises PermissionError
        (rare under Decky's plugin_loader since plugin runs as root, but
        kept for robustness on JELOS / Holo SteamOS where namespace
        quirks can strip capabilities).
        """
        try:
            with open(path, "w") as f:
                f.write(value)
            return True
        except PermissionError:
            try:
                result = subprocess.run(
                    ["tee", path],
                    input=value.encode(),
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                return result.returncode == 0
            except (FileNotFoundError, subprocess.SubprocessError) as e:
                logger.error(f"BatteryManager: tee fallback failed for {path}: {e}")
                return False
        except OSError as e:
            logger.error(f"BatteryManager: write failed for {path}={value}: {e}")
            return False


# Module-level singleton (lazy)
_battery_manager: Optional[BatteryManager] = None


def get_battery_manager() -> BatteryManager:
    """Return the singleton BatteryManager instance."""
    global _battery_manager
    if _battery_manager is None:
        _battery_manager = BatteryManager()
    return _battery_manager