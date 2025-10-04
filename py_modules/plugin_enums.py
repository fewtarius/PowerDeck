"""
PowerDeck Enumerations
Core enums for the PowerDeck plugin
"""
from enum import Enum, IntEnum, auto


class CPUVendor(Enum):
    """CPU Vendor types"""
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"


class DeviceType(Enum):
    """Supported handheld device types"""
    STEAM_DECK = "steam_deck"
    ROG_ALLY = "rog_ally"
    ROG_ALLY_X = "rog_ally_x"
    LEGION_GO = "legion_go"
    GENERIC_AMD = "generic_amd"
    GENERIC_INTEL = "generic_intel"
    UNKNOWN = "unknown"


class TDPMethod(Enum):
    """TDP control methods"""
    RYZENADJ = "ryzenadj"
    INTEL_RAPL = "intel_rapl"
    SYSFS = "sysfs"
    UNSUPPORTED = "unsupported"


class PowerProfile(IntEnum):
    """Standard power profiles"""
    BATTERY_SAVER = 0
    BALANCED = 1
    PERFORMANCE = 2
    GAMING = 3


class CPUGovernor(Enum):
    """CPU governor options"""
    PERFORMANCE = "performance"
    POWERSAVE = "powersave"
    ONDEMAND = "ondemand"
    CONSERVATIVE = "conservative"
    SCHEDUTIL = "schedutil"
    USERSPACE = "userspace"


class CPUEnergyPerformancePreference(Enum):
    """Energy Performance Preference options"""
    PERFORMANCE = "performance"
    BALANCE_PERFORMANCE = "balance_performance"
    DEFAULT = "default"
    BALANCE_POWER = "balance_power"
    POWER = "power"


class GPUMode(Enum):
    """GPU operating modes for modern PowerDeck"""
    AUTO = "auto"
    INTEGRATED_ONLY = "integrated"
    DEDICATED_ONLY = "dedicated"
    HYBRID = "hybrid"
    # Legacy compatibility modes
    BATTERY = "battery"
    BALANCE = "balance"
    RANGE = "range"
    FIXED = "fixed"


class GPUFrequencyControl(Enum):
    """GPU frequency control types"""
    MIN = "minGpuFrequency"
    MAX = "maxGpuFrequency"
    FIXED = "fixedGpuFrequency"


class LogLevel(IntEnum):
    """Logging levels for PowerDeck"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4


class PluginEvent(Enum):
    """Plugin lifecycle events"""
    INIT = "init"
    GAME_START = "game_start"
    GAME_STOP = "game_stop"
    SUSPEND = "suspend"
    RESUME = "resume"
    PROFILE_APPLIED = "profile_applied"
    SETTING_CHANGED = "setting_changed"


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class DeviceError(Exception):
    """Custom exception for device-specific errors"""
    pass


class PowerControlError(Exception):
    """Custom exception for power control errors"""
    pass


# Legacy aliases for backward compatibility
class GpuModes(GPUMode):
    """Legacy GPU modes - use GPUMode instead"""
    pass


class GpuRange(GPUFrequencyControl):
    """Legacy GPU range - use GPUFrequencyControl instead"""
    pass
