# AGENTS.md

**Version:** 1.0
**Date:** 2026-07-01
**Purpose:** Technical reference for PowerDeck development

---

## Project Overview

**PowerDeck** is a Decky Loader plugin providing advanced power management for handheld gaming PCs and AMD desktop APUs.

- **Language:** Python 3.8+ (backend plugin), TypeScript/React (frontend UI)
- **Architecture:** Decky Loader plugin with Python backend communicating via Decky's `callable` RPC
- **License:** GPL-3.0
- **Version:** 1.0.55 (single source of truth: `VERSION` file)

---

## Quick Setup

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/fewtarius/PowerDeck.git
cd PowerDeck

# Install frontend dependencies
pnpm install

# Build everything (RyzenAdj + frontend)
./build.sh

# Quick frontend-only build
pnpm build

# Development watch mode
pnpm watch
```

**Prerequisites:**
- `cmake`, `build-essential`, `libpci-dev` for RyzenAdj
- Node.js (latest) + pnpm 10+
- Python 3.8+ with `psutil` (`pip install psutil`)

---

## Architecture

```
Decky Loader Overlay (Steam UI)
         |
         v
┌─────────────────────────────┐
│  Frontend (src/index.tsx)   │  TypeScript/React with Decky UI components
│  - Error boundary           │
│  - Game detection           │
│  - SliderField, ToggleField │
│  - Device-specific UI       │
└──────────┬──────────────────┘
           │ callable<T>() RPC bridge
           v
┌─────────────────────────────┐
│  Backend (main.py)          │  371K Python monolith
│  - Plugin lifecycle         │
│  - Callable handlers        │
│  - Hardware orchestration   │
└──────────┬──────────────────┘
           │ imports
           v
┌─────────────────────────────┐
│  py_modules/                │
│  ├── power_core.py          │  Core types, enums, base classes
│  ├── cpu_manager.py         │  CPU governors, EPP, boost, SMT
│  ├── gpu_manager.py         │  GPU frequency control (amd/intel)
│  ├── profile_manager.py     │  JSON profiles, per-game settings
│  ├── device_manager.py      │  Device detection, capability mapping
│  ├── processor_detection.py │  CPU identification from /proc/cpuinfo
│  ├── unified_processor_db.py│  Processor database (static data)
│  ├── sysfs_power_manager.py │  Sysfs-based power management
│  ├── ac_power_manager.py    │  AC adapter detection
│  ├── plugin_utils.py        │  Update/version utilities
│  ├── plugin_settings.py     │  Settings persistence
│  ├── sleep_wake_manager.py  │  Sleep/wake event handling
│  ├── steamfork_fan_control.py│ SteamFork-specific fan control
│  ├── inputplumber_manager.py│ InputPlumber controller emulation
│  └── devices/               │  Device-specific controllers
│      ├── steam_deck.py      │
│      ├── rog_ally.py        │
│      └── lenovo.py          │
└──────────┬──────────────────┘
           │
           v
┌─────────────────────────────┐
│  Hardware Interfaces        │
│  ├── RyzenAdj (AMD SMU)     │  Git submodule, compiled to binary
│  ├── Intel RAPL (sysfs)     │  /sys/class/powercap/
│  ├── amdgpu sysfs           │  /sys/class/drm/card*/device/
│  ├── cpufreq sysfs          │  /sys/devices/system/cpu/cpufreq/
│  ├── SteamOS Manager DBus   │  com.steampowered.SteamOSManager1
│  └── InputPlumber           │  Controller emulation daemon
└─────────────────────────────┘
```

**Communication Flow:**
1. User interacts with React UI (Steam overlay)
2. Frontend calls `callable<[args], ReturnType>("backend_function_name")`
3. Decky serializes args, calls Python function in `main.py`
4. Backend reads/writes hardware via sysfs, RyzenAdj, or DBus
5. Result serialized back to frontend

---

## Directory Structure

| Path | Purpose |
|------|---------|
| `main.py` | Backend plugin entry point (371K monolith - callable handlers, hardware orchestration) |
| `py_modules/` | Python modules imported by `main.py` |
| `py_modules/devices/` | Device-specific controllers (Steam Deck, ROG Ally, Lenovo Legion) |
| `src/index.tsx` | Frontend entry point (React/TypeScript with Decky UI) |
| `dist/` | Built frontend output (`index.js`, `index.js.map`) |
| `RyzenAdj/` | Git submodule - AMD SMU control utility (C, cmake build) |
| `images/` | Screenshots for README |
| `.github/workflows/release.yml` | CI/CD release pipeline |
| `build.sh` | Full build script (RyzenAdj + frontend + IIFE fix) |
| `install.sh` | One-line install script |
| `update-version.sh` | Sync VERSION file to package.json and plugin.json |
| `VERSION` | Single source of truth for version (e.g., `1.0.55`) |
| `plugin.json` | Decky plugin manifest (name, author, flags, version) |
| `package.json` | Node.js project config (pnpm, dependencies, scripts) |
| `tsconfig.json` | TypeScript compiler config |
| `rollup.config.js` | Rollup build config (uses `@decky/rollup` preset) |
| `decky.pyi` | Decky Python type stubs |
| `powerdeck-info` | Device/processor info blob |
| `scratch/` | Gitignored working documents (analysis, plans) |

---

## Code Style

### Python Conventions

**Imports order:** stdlib -> third-party -> py_modules:
```python
import os
import subprocess
from typing import Dict, List, Optional

import decky_plugin
import psutil

from cpu_manager import CPUManager
from power_core import PowerProfile, CPUVendor
```

**Class structure:**
```python
class MyManager:
    """Manages [thing] for PowerDeck."""
    
    def __init__(self):
        self.logger = decky_plugin.logger
        # Initialize caches and state
        self._cache = None
    
    def public_method(self, arg: str) -> bool:
        """Public API - returns simple types for callable bridge"""
        ...
    
    def _private_method(self) -> None:
        """Internal implementation detail"""
        ...
```

**Logging:** Use `decky_plugin.logger`:
```python
import decky_plugin

# In main.py, standardized wrappers exist:
info_log("message")      # Always visible when disk logging enabled
debug_log("message")     # Only when POWERDECK_DEBUG=true
error_log("message")     # Always visible when disk logging enabled
debug_error("message")   # Only when POWERDECK_DEBUG=true

# In py_modules, use decky directly:
decky_plugin.logger.info("[PowerDeck] message")
```

**Docstrings:** Triple-quoted at module and method level:
```python
"""
Module purpose - brief description.
"""
```

**Error handling:** Return sentinel values or False, avoid exceptions across the callable bridge:
```python
# Backend callable handlers in main.py:
def some_handler(arg: str) -> bool:
    try:
        result = do_work(arg)
        return result is not None
    except Exception:
        traceback.print_exc()
        return False
```

**Underscore prefixes:** `_method()` for private/internal, no underscore for public API.

**Type hints:** Used throughout (`Optional[str]`, `Dict[str, Any]`, `List[int]`, `Tuple[int, int]`).

**Enums and dataclasses:** Preferred over raw dicts for structured data:
```python
from enum import Enum, IntEnum
from dataclasses import dataclass, field, asdict

class PowerProfile(IntEnum):
    BATTERY_SAVER = 0
    BALANCED = 1
    PERFORMANCE = 2

@dataclass
class CPUProfile:
    governor: Optional[str] = None
    epp: Optional[str] = None
    boost_enabled: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

### TypeScript/React Conventions

**Components:** Functional with hooks:
```tsx
const MyComponent: React.FC<{prop: string}> = ({ prop }) => {
  const [state, setState] = useState<number>(0);
  // ...
  return <PanelSectionRow>...</PanelSectionRow>;
};
```

**Backend calls:** Always use `callable<>()` typed wrappers:
```tsx
const getDeviceInfo = callable<[], any>("get_device_info");
const setGameProfile = callable<[gameId: string, profile: any], boolean>("set_game_profile");
```

**Debug logging:** Use the `debug` object pattern:
```tsx
const debug = {
  log: (message: string, ...args: any[]) => {
    if (DEBUG_ENABLED) console.log(`[PowerDeck] ${message}`, ...args);
  },
  error: (message: string, ...args: any[]) => {
    if (DEBUG_ENABLED) console.error(`[PowerDeck] ERROR: ${message}`, ...args);
  }
};
```

**Decky UI components:** Import from `@decky/ui`:
```tsx
import { ButtonItem, SliderField, ToggleField, PanelSection, PanelSectionRow } from "@decky/ui";
```

**Icons:** Use `react-icons/fa`:
```tsx
import { FaBolt, FaCog, FaRocket } from "react-icons/fa";
```

---

## Module Naming Conventions

| Prefix | Purpose | Examples |
|--------|---------|----------|
| `*_manager.py` | High-level subsystem coordinator | `cpu_manager.py`, `device_manager.py`, `profile_manager.py` |
| `*_detection.py` | Hardware detection and identification | `processor_detection.py` |
| `*_power_*.py` | Power-specific functionality | `ac_power_manager.py`, `sysfs_power_manager.py` |
| `*_settings.py` | Configuration persistence | `plugin_settings.py` |
| `power_core.py` | Core types, enums, base classes | PowerProfile, CPUVendor, TDPMethod |
| `devices/*.py` | Device-specific controllers | `steam_deck.py`, `rog_ally.py`, `lenovo.py` |

**Backend callable naming:** `snake_case` verb_noun pattern:
```
get_device_info, set_tdp, apply_profile, get_game_profile, set_game_profile
```

---

## Testing

**No formal test suite exists.** Testing is done via:
- Manual testing on hardware (Steam Deck, AYANEO Flip, ROG Ally)
- `journalctl -u plugin_loader` for backend logs
- Decky Loader overlay for frontend testing
- `ryzenadj -i` to verify SMU TDP writes

**Before committing:**
```bash
# Verify Python syntax
python3 -m py_compile main.py
python3 -m py_compile py_modules/*.py

# Build frontend
pnpm build

# Verify dist/index.js exists
test -f dist/index.js

# Full build (including RyzenAdj)
./build.sh
```

---

## Commit Format

```
type(scope): brief description

Problem: What was broken/incomplete
Solution: How you fixed it
Testing: How you verified the fix
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

**Common scopes:** `tdp`, `cpu`, `gpu`, `profile`, `rog-ally`, `steam-deck`, `strix-halo`, `ui`, `build`, `update`

**Example:**
```
fix(strix-halo): skip --apu-skin-temp on Strix Halo

Problem: ryzenadj exited rc=255 when --apu-skin-temp was passed on
Strix Halo APUs (no skin temp sensor), ignoring valid STAPM writes

Solution: Detect Strix Halo family and omit --apu-skin-temp flag

Testing: Verified on Beelink GTR9 PRO (Ryzen AI MAX+ 395) -
TDP slider works, no rc=255 errors in journalctl
```

**Pre-Commit Checklist:**
- Python syntax check passes on changed files
- `pnpm build` succeeds
- `dist/index.js` exists after build
- Commit message explains WHAT and WHY
- No `TODO`/`FIXME` comments (finish the work)

---

## Development Tools

**Common Commands:**
```bash
# Build everything
./build.sh

# Frontend only
pnpm build

# Watch mode (frontend auto-rebuild)
pnpm watch

# Install on device
./install.sh

# View backend logs
sudo journalctl -u plugin_loader -f

# Filter PowerDeck logs
sudo journalctl -u plugin_loader | grep PowerDeck

# Test RyzenAdj TDP
sudo ./RyzenAdj/build/ryzenadj -a 15000 -b 15000 -c 15000
sudo ./RyzenAdj/build/ryzenadj -i  # Read current

# Check CPU governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Check GPU frequency
cat /sys/class/drm/card0/device/pp_dpm_fclk

# Version management
./update-version.sh      # Sync VERSION -> package.json, plugin.json
cat VERSION              # Single source of truth
```

**Deployment (manual):**
```bash
# Build the plugin zip (requires decky CLI)
decky plugin build .

# Copy to device
scp out/PowerDeck.zip deck@steamdeck:~/homebrew/plugins/
ssh deck@steamdeck "cd ~/homebrew/plugins && unzip -o PowerDeck.zip -d PowerDeck"
ssh deck@steamdeck "sudo systemctl restart plugin_loader"
```

---

## Common Patterns

### Adding a New Backend Callable

1. Add the handler function in `main.py`:
```python
# Called via callable<[arg1: str, arg2: int], bool>("my_new_function")
async def my_new_function(arg1: str, arg2: int) -> bool:
    try:
        result = do_something(arg1, arg2)
        return result is not None
    except Exception:
        traceback.print_exc()
        return False
```
2. In `src/index.tsx`, declare the typed wrapper:
```tsx
const myNewFunction = callable<[arg1: string, arg2: number], boolean>("my_new_function");
```
3. Use it in your React component:
```tsx
const result = await myNewFunction("hello", 42);
```

### Adding a New Device Controller

1. Create `py_modules/devices/new_device.py`:
```python
class NewDeviceController:
    def __init__(self):
        self.logger = decky_plugin.logger
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "tdp_min": 5, "tdp_max": 30,
            "supports_gpu_control": True,
            # ...
        }
    
    def set_tdp(self, watts: int) -> bool:
        # Device-specific TDP logic
        ...

def get_new_device_controller():
    return NewDeviceController()
```
2. Import in `main.py` with try/except:
```python
try:
    from devices.new_device import get_new_device_controller
    NEW_DEVICE_AVAILABLE = True
except ImportError:
    NEW_DEVICE_AVAILABLE = False
```

### Profile System

Profiles are JSON files in `~/.config/powerdeck/profiles/`:
```
~/.config/powerdeck/profiles/
├── default_ac.json       # Base AC profile
├── default_battery.json  # Base battery profile
├── {appid}_ac.json       # Per-game AC profile
└── {appid}_battery.json  # Per-game battery profile
```

Profile structure (via `PowerProfileData` dataclass):
```json
{
  "name": "Game Name",
  "tdp": 15,
  "cpu": {
    "governor": "schedutil",
    "epp": "balance_power",
    "boost_enabled": true,
    "smt_enabled": true
  },
  "gpu": {
    "mode": "balance",
    "min_frequency": 200,
    "max_frequency": 2200
  }
}
```

### Sysfs Paths (Key Interfaces)

| Resource | Path |
|----------|------|
| CPU governor | `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` |
| CPU EPP | `/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference` |
| CPU boost | `/sys/devices/system/cpu/cpufreq/boost` |
| SMT control | `/sys/devices/system/cpu/smt/control` |
| CPU online | `/sys/devices/system/cpu/cpu*/online` |
| GPU frequency (AMD) | `/sys/class/drm/card*/device/pp_dpm_sclk` |
| GPU perf level (AMD) | `/sys/class/drm/card*/device/power_dpm_force_performance_level` |
| GPU freq min/max (Intel) | `/sys/class/drm/card*/gt_min_freq_mhz`, `gt_max_freq_mhz` |
| RAPL (Intel) | `/sys/class/powercap/intel-rapl*/` |
| PCIe ASPM | `/sys/module/pcie_aspm/parameters/policy` |
| USB autosuspend | `/sys/bus/usb/devices/*/power/control` |
| AC adapter | `/sys/class/power_supply/*/online` |

### DBus Integration

```python
# SteamOS Manager (if available)
STEAMOS_MANAGER_DBUS_NAME = "com.steampowered.SteamOSManager1"
STEAMOS_MANAGER_DBUS_PATH = "/com/steampowered/SteamOSManager1"
STEAMOS_MANAGER_DBUS_IFACE = "com.steampowered.SteamOSManager1.RootManager"

# ExternalManager1 for claiming power/fan subsystems
EXTERNAL_MANAGER_DBUS_IFACE = "com.steampowered.SteamOSManager1.ExternalManager1"
```

**Pattern:** Always check boolean return from DBus calls. Fall back to direct sysfs if DBus returns False (SteamOS Holo/JELOS builds may not register all methods).

---

## Documentation

### What Needs Documentation

| Change Type | Required Documentation |
|-------------|------------------------|
| New feature | Update README.md features section |
| New device support | Add to README.md compatibility tables |
| API change (callable) | Update AGENTS.md common patterns |
| Build process change | Update build.sh comments + AGENTS.md |
| User-facing UI change | Update README.md screenshots/features |

### Documentation Files

| File | Purpose |
|------|---------|
| `README.md` | Project overview, features, compatibility, install |
| `AGENTS.md` | This file - technical reference |
| `.clio/instructions.md` | Project methodology (Unbroken Method) |
| `scratch/` | Gitignored working documents |

---

## Anti-Patterns (What NOT To Do)

| Anti-Pattern | Why It's Wrong | What To Do |
|--------------|----------------|------------|
| Assume DBus call succeeded | SteamOS Holo/JELOS may not register all methods | Check boolean return, fall back to sysfs |
| Hardcode TDP limits | Different devices have different ranges | Read from device capabilities |
| Skip `--apu-skin-temp` check on AMD | Strix Halo has no skin temp sensor | Detect family, conditionally omit flag |
| Pass complex objects across callable bridge | Serialization can fail | Return simple types (bool, int, str, dict) |
| Use bare `except:` | Swallows useful error info | Use `except Exception:` and log traceback |
| Add new py_module without sys.path setup | Installed plugin flattens directories | Ensure `main.py` sys.path handling covers new module locations |
| Change VERSION file directly without sync | Package/plugin versions get out of sync | Run `./update-version.sh` |
| Create files in `.clio/` manually | CLIO manages its own directory | Let CLIO handle `.clio/` internals |
| Leave DEBUG_ENABLED=true in production | Verbose logging impacts performance | Set to false before release build |

---

## Quick Reference

**Build:**
```bash
./build.sh              # Full build (RyzenAdj + frontend)
pnpm build              # Frontend only
pnpm watch              # Watch mode
```

**Version:**
```bash
cat VERSION             # Current version (single source of truth)
./update-version.sh     # Sync VERSION -> package.json + plugin.json
```

**Syntax Check:**
```bash
python3 -m py_compile main.py
python3 -m py_compile py_modules/*.py
```

**Deploy:**
```bash
./install.sh            # One-line install on device
```

**Debug:**
```bash
sudo journalctl -u plugin_loader -f                          # All logs
sudo journalctl -u plugin_loader | grep PowerDeck            # Plugin logs
sudo journalctl -u plugin_loader | grep ERROR                # Errors only
POWERDECK_DEBUG=true POWERDECK_DISK_LOGGING=true             # Enable verbose logging
```

**Hardware Verification:**
```bash
./RyzenAdj/build/ryzenadj -i                                 # Read SMU TDP
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor    # CPU governor
cat /sys/class/drm/card0/device/pp_dpm_sclk                  # GPU clocks
```

---

*For project methodology and workflow, see .clio/instructions.md*
