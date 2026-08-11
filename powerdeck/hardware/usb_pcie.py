"""USB autosuspend, PCIe ASPM, PCI runtime PM, and WiFi power save.

Each control toggles a kernel sysfs/file. Toggles that reverse to
"OS default" simply write the inactive value.
"""

from __future__ import annotations

import glob
import os
from typing import Dict, Optional

from ._sysfs import file_exists, read_sysfs, write_sysfs


USB_POWER_GLOB = "/sys/bus/usb/devices/*/power/control"
PCI_POWER_GLOB = "/sys/bus/pci/devices/*/power/control"
WIFI_POWERSAVE = "/sys/module/iwlmvm/parameters/power_save"
PCIE_ASPM_POLICY = "/sys/module/pcie_aspm/parameters/policy"
AUTOSUSPEND_DELAY = "/sys/bus/usb/devices/*/power/autosuspend_delay_ms"
AUTOSUSPEND_DELAY_DEFAULT = 30000  # 30 seconds - balances resume latency vs power


def usb_available() -> bool:
    return any(glob.glob(USB_POWER_GLOB))


def pci_available() -> bool:
    return any(glob.glob(PCI_POWER_GLOB))


def wifi_available() -> bool:
    return file_exists(WIFI_POWERSAVE) or any(glob.glob("/sys/module/iwl*/parameters/power_save"))


def pcie_aspm_available() -> bool:
    return file_exists(PCIE_ASPM_POLICY)


# ── USB autosuspend ────────────────────────────────────────────────────


def get_usb_autosuspend_status() -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for path in glob.glob(USB_POWER_GLOB):
        device = os.path.basename(os.path.dirname(os.path.dirname(path)))
        out[device] = read_sysfs(path) == "auto"
    return out


def set_usb_autosuspend(enable: bool) -> bool:
    success = False
    for control_path in sorted(glob.glob(USB_POWER_GLOB)):
        value = "auto" if enable else "on"
        if write_sysfs(control_path, value):
            success = True
    if enable:
        for delay_path in sorted(glob.glob(AUTOSUSPEND_DELAY)):
            write_sysfs(delay_path, str(AUTOSUSPEND_DELAY_DEFAULT))
    return success


# ── PCIe ASPM ──────────────────────────────────────────────────────────


def get_pcie_aspm_policy() -> Optional[str]:
    if not file_exists(PCIE_ASPM_POLICY):
        return None
    return read_sysfs(PCIE_ASPM_POLICY, "default")


def set_pcie_aspm_policy(policy: str) -> bool:
    if not file_exists(PCIE_ASPM_POLICY):
        return False
    return write_sysfs(PCIE_ASPM_POLICY, policy)


# ── PCI runtime PM ────────────────────────────────────────────────────


def get_pci_runtime_pm_status() -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for path in glob.glob(PCI_POWER_GLOB):
        device = os.path.basename(os.path.dirname(os.path.dirname(path)))
        out[device] = read_sysfs(path) == "auto"
    return out


def set_pci_runtime_pm(enable: bool) -> bool:
    value = "auto" if enable else "on"
    success = False
    for path in sorted(glob.glob(PCI_POWER_GLOB)):
        if write_sysfs(path, value):
            success = True
    return success


# ── WiFi power save ────────────────────────────────────────────────────


def get_wifi_power_save() -> Optional[bool]:
    if not wifi_available():
        return None
    paths = sorted(glob.glob("/sys/module/iwl*/parameters/power_save"))
    if not paths:
        return None
    return read_sysfs(paths[0]) == "1"


def set_wifi_power_save(enable: bool) -> bool:
    if not wifi_available():
        return False
    value = "1" if enable else "0"
    success = False
    for path in sorted(glob.glob("/sys/module/iwl*/parameters/power_save")):
        if write_sysfs(path, value):
            success = True
    return success
