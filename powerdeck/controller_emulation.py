"""InputPlumber controller-mode integration.

Talks to InputPlumber via the `inputplumber` CLI (preferred) to read
the current target device and set a new one. Returns the available
modes + current mode for the frontend.

Per-game persistence is handled here: when the user picks a controller
mode in a game, save it so subsequent launches of that game apply it
automatically.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from typing import List, Optional, Tuple

import decky_plugin  # noqa: F401 - this module always runs inside Decky


# The canonical list of InputPlumber target devices. The frontend
# lets the user pick one of these; "default" is a UI-only label that
# resolves to whatever the device's InputPlumber YAML ships as its
# default target (e.g. AYANEO Flip KB / OneXPlayer F1Pro default to
# xbox-elite; Steam Deck LCD/OLED default to deck-uhid).
SUPPORTED_MODES = [
    "default",
    "xbox-elite",
    "xbox-series",
    "ds5",
    "ds5-edge",
    "deck-uhid",
    "unified-gamepad",
]

# Mapping from inputplumber target id -> human-friendly name.
HUMAN_TARGET = {
    "xbox-elite": "Xbox Elite",
    "xbox-series": "Xbox Series",
    "ds5": "DualSense",
    "ds5-edge": "DualSense Edge",
    "deck-uhid": "Steam Deck",
    "unified-gamepad": "Unified Gamepad",
    "xb360": "Xbox 360",
    "hori-steam": "Hori Steam",
    "8bitdo-u2": "8BitDo Ultimate",
}


def _read_dmi() -> Tuple[str, str]:
    """Read sys_vendor and product_name from /sys/class/dmi/id."""
    def _read(field: str) -> str:
        try:
            with open(f"/sys/class/dmi/id/{field}", "r") as f:
                return f.read().strip()
        except Exception:
            return ""
    return _read("sys_vendor"), _read("product_name")


def device_key() -> str:
    """Map the running device to a key in the inputplumber YAML
    shipped config. Returns an empty string if the device is unknown."""
    vendor, product = _read_dmi()
    if vendor == "AYANEO":
        if product.startswith("FLIP KB"):
            return "ayaneo_flip"
        if product.startswith("FLIP DS"):
            return "ayaneo_flip_1s"
        slug = product.lower().replace(" ", "_").replace("-", "_")
        known = [
            "ayaneo_2", "ayaneo_2s", "ayaneo_3", "ayaneo_2021",
            "ayaneo_air", "ayaneo_air_1s", "ayaneo_air_plus",
            "ayaneo_air_plus_mendo", "ayaneo_kun", "ayaneo_next",
            "ayaneo_slide",
        ]
        for k in known:
            if slug.startswith(k):
                return k
    elif vendor == "ONE-NETBOOK":
        return "onexplayer_onexfly_pro"
    elif vendor == "Valve":
        if "OLED" in product.upper():
            return "deck_oled"
        return "deck_lcd"
    return ""


def _yaml_default_target(device_id: str) -> Optional[str]:
    """Read /usr/share/inputplumber/devices/<id>.yaml and pull out
    the first entry in `target_devices:`. Returns None if no file."""
    path = f"/usr/share/inputplumber/devices/50-{device_id}.yaml"
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            text = f.read()
    except Exception:
        return None
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("target_devices:"):
            in_block = True
            continue
        if in_block:
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if line.startswith(" ") or line.startswith("\t") or line.startswith("-"):
                # still in the block
                m = re.search(r"-\s*([A-Za-z0-9_-]+)", stripped)
                if m:
                    return m.group(1)
                continue
            # left the block
            return None
    return None


def default_target_for_device() -> str:
    """Return the InputPlumber target device this machine ships with."""
    key = device_key()
    if not key:
        return "xbox-elite"
    yaml_default = _yaml_default_target(key)
    if yaml_default:
        return yaml_default
    # Old / one-off product names that don't have a YAML in this
    # distro. Best-effort fallback.
    if key.startswith("ayaneo") or key.startswith("onexplayer") or key.startswith("aokzoe"):
        return "xbox-elite"
    return "xbox-elite"


def available_modes() -> List[str]:
    """Return the canonical mode list. A subset is exposed in the UI."""
    return SUPPORTED_MODES


def _list_targets() -> List[str]:
    """Run `inputplumber device 0 targets list` and return the target IDs."""
    try:
        out = subprocess.run(
            ["inputplumber", "device", "0", "targets", "list"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if out.returncode != 0:
        return []

    # Parse the UTF-8 table. Data rows look like:
    #   │ xbox-series │ Microsoft Xbox Series S|X Controller │
    # Skip title rows (Target Devices / Id / Name) and the rule rows
    # ──┬── / ──┼── / ──┴── / ╭── / ╰──.
    targets = []
    for line in out.stdout.splitlines():
        if not line.startswith("│"):
            continue
        parts = [p.strip() for p in line.strip("│").split("│")]
        if not parts or not parts[0]:
            continue
        first = parts[0]
        if first in ("Id", "Target Devices"):
            continue
        # looks like a real data row
        targets.append(first)
    return targets


def _set_targets(targets: List[str]) -> bool:
    """Run `inputplumber device 0 targets set <targets...>`."""
    try:
        out = subprocess.run(
            ["inputplumber", "device", "0", "targets", "set", *targets],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def _current_target() -> Optional[str]:
    """Return the current target device id (or None if not set)."""
    targets = _list_targets()
    return targets[0] if targets else None


def get_status() -> dict:
    """Return a small dict used by the frontend: {available, current_mode, dbus_mode, modes, default_target}."""
    actual = _current_target()
    if actual is None:
        # inputplumber isn't managing our device or isn't running.
        # Fall back to the device's shipped default so the UI doesn't
        # lie about the active mode.
        actual = default_target_for_device()
    return {
        "available": True,
        "current_mode": actual,
        "dbus_mode": False,
        "modes": available_modes(),
        "default_target": default_target_for_device(),
    }


def set_mode(mode: str) -> bool:
    """Set the InputPlumber target device. `default` resolves to the
    device's shipped default target, so the user can revert."""
    if mode not in SUPPORTED_MODES:
        return False
    if mode == "default":
        target = default_target_for_device()
    else:
        target = mode
    return _set_targets([target])


def get_profile_for_game(profile_id: str, settings_dir: str) -> Optional[dict]:
    base = os.path.join(settings_dir, "inputplumber")
    path = os.path.join(base, f"{profile_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def save_profile_for_game(profile_id: str, settings: dict, settings_dir: str) -> bool:
    base = os.path.join(settings_dir, "inputplumber")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{profile_id}.json")
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def apply_profile_for_game(profile_id: str, settings_dir: str) -> bool:
    settings = get_profile_for_game(profile_id, settings_dir)
    if not settings:
        return False
    mode = settings.get("controller_mode")
    if mode:
        return set_mode(mode)
    return False
