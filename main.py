import decky
import asyncio
import os
import sys
import json
import psutil
import subprocess
import shutil
import time
from typing import Dict, Any, Optional, List, Tuple

# Add py_modules directory to Python path for dynamic imports
py_modules_path = os.path.join(os.path.dirname(__file__), 'py_modules')
if py_modules_path not in sys.path:
    sys.path.insert(0, py_modules_path)

# Debug configuration
DEBUG_ENABLED = os.environ.get('POWERDECK_DEBUG', 'false').lower() == 'true'
DISK_LOGGING_ENABLED = os.environ.get('POWERDECK_DISK_LOGGING', 'false').lower() == 'true'

# Version management
def get_plugin_version() -> str:
    """Get plugin version from VERSION file or plugin.json fallback"""
    try:
        # First try to read from VERSION file (single source of truth)
        version_file_path = os.path.join(os.path.dirname(__file__), "VERSION")
        if os.path.exists(version_file_path):
            with open(version_file_path, 'r') as f:
                version = f.read().strip()
                if version:
                    return version
        
        # Fallback to plugin.json
        plugin_json_path = os.path.join(os.path.dirname(__file__), "plugin.json")
        if os.path.exists(plugin_json_path):
            with open(plugin_json_path, 'r') as f:
                plugin_data = json.load(f)
                return plugin_data.get("version", "unknown")
        
        return "unknown"  # Fallback when VERSION file and plugin.json both fail
    except Exception as e:
        decky.logger.error(f"Failed to get plugin version: {e}")
        return "unknown"  # Ultimate fallback version 

# Standardized logging functions
def debug_log(message: str, *args, **kwargs):
    """Log debug messages only when debug mode is enabled"""
    if DEBUG_ENABLED and DISK_LOGGING_ENABLED:
        decky.logger.info(f"[DEBUG] {message}", *args, **kwargs)

def debug_error(message: str, *args, **kwargs):
    """Log error messages only when debug mode is enabled"""
    if DEBUG_ENABLED and DISK_LOGGING_ENABLED:
        decky.logger.error(f"[DEBUG] {message}", *args, **kwargs)

def info_log(message: str, *args, **kwargs):
    """Log important info messages (always visible)"""
    if DISK_LOGGING_ENABLED:
        decky.logger.info(f"[PowerDeck] {message}", *args, **kwargs)

def error_log(message: str, *args, **kwargs):
    """Log error messages (always visible)"""
    if DISK_LOGGING_ENABLED:
        decky.logger.error(f"[PowerDeck] {message}", *args, **kwargs)

# Add py_modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), "py_modules"))

# Import device-specific controllers
try:
    from devices.rog_ally import get_rog_ally_controller
    ROG_ALLY_AVAILABLE = True
except ImportError:
    ROG_ALLY_AVAILABLE = False
    debug_log("ROG Ally support not available")

try:
    from devices.lenovo import get_legion_controller
    LEGION_AVAILABLE = True
except ImportError:
    LEGION_AVAILABLE = False
    debug_log("Legion support not available")

try:
    from devices.steam_deck import get_steam_deck_controller
    STEAM_DECK_AVAILABLE = True
except ImportError:
    STEAM_DECK_AVAILABLE = False
    debug_log("Steam Deck support not available")

# Try to import device management modules with graceful fallbacks
try:
    from device_manager import DeviceManager
    from power_core import PowerManager
    from profile_manager import ProfileManager
    from cpu_manager import CPUManager
    from plugin_settings import PowerDeckSettings
    from steamfork_fan_control import steamfork_fan_controller
    from sleep_wake_manager import get_sleep_wake_manager
    from inputplumber_manager import get_inputplumber_manager, ControllerMode
    device_support_available = True
except ImportError as e:
    error_log(f"Device support modules not available: {e}")
    device_support_available = False

# Import processor detection modules
try:
    from processor_detection import (
        get_current_processor_info, 
        get_processor_tdp_limits,
        get_processor_default_tdp,
        is_handheld_device,
        refresh_processor_detection
    )
    # Import unified processor database instead of old separate databases  
    from unified_processor_db import get_processor_info, get_processor_tdp_info, get_database_stats
    processor_support_available = True
    info_log("Processor database and detection loaded successfully")
except ImportError as e:
    error_log(f"Processor detection modules not available: {e}")
    processor_support_available = False

# Import sysfs-based power management
try:
    from sysfs_power_manager import (
        sysfs_power_manager,
        get_sysfs_power_capabilities,
        get_sysfs_tdp_limits,
        set_sysfs_tdp
    )
    sysfs_support_available = True
    info_log("Sysfs power management loaded successfully")
except ImportError as e:
    error_log(f"Sysfs power management not available: {e}")
    sysfs_support_available = False

class Plugin:
    def __init__(self):
        self.device_manager = None
        self.power_manager = None
        self.profile_manager = None
        self.cpu_manager = None
        self.settings = None
        self.device_controller = None  # Device-specific controller
        self.device_type = "generic"  # Device type identifier
        self.processor_info = None  # Processor specifications and capabilities
        self.power_mode = "hybrid"  # Power management mode: sysfs, database, or hybrid
        self.original_hardware_defaults = None  # Store unmodified hardware state for default profile creation
        # Initialize with minimal defaults - real values will be set from processor database during initialization
        self.current_profile = {
            "tdp": None,  # Will be set from processor database default_tdp during initialization
            "cpuBoost": True,  # Enabled by default to match typical system behavior
            "smt": True,
            "cpuCores": None,  # Will be detected from hardware during initialization
            "governor": "powersave",  # Always use powersave for efficiency
            "epp": "balance_power"  # Conservative EPP setting for efficiency
        }
        # TDP limits will be set from processor database or sysfs during initialization
        self.tdp_limits = {"min": 4, "max": None}  # Min is hard-coded 4W, max from database
        self.enable_per_game_profiles = True  # Per-game profiles setting - enabled by default
        self.rog_ally_native_tdp_enabled = False  # ROG Ally native TDP support - disabled by default
        self.device_info = {
            "device_name": "Unknown Device",
            "cpu_vendor": "unknown",
            "supports_tdp": True,
            "supports_cpu_boost": True,
            "supports_smt": True,
            "supports_gpu_control": True,
            "has_fan_control": False,  # Will be set during initialization
            # TDP values will be set from processor database during initialization
            "min_tdp": 4,  # Hard-coded minimum for underclocking
            "max_tdp": None,  # Will be set from processor database
            "min_gpu_freq": 400,
            "max_gpu_freq": 1600
        }
        self.ryzenadj_path = None
        self.warning_cache = set()  # Track warnings to prevent duplicates
        
        # Enhanced sleep/wake management
        self.sleep_wake_manager = None
        
        # Background update checking state
        self.last_update_check = None
        self.update_check_interval = 4 * 3600  # 4 hours in seconds
        self.update_available = False
        self.latest_available_version = None
        self.background_update_task = None
        self.staged_update_info = None
        self.staged_update_path = None
        self.update_staging_dir = "/tmp/powerdeck_staged_update"
        
    def log_warning_once(self, message: str):
        """Log a warning message only once to prevent spam"""
        if message not in self.warning_cache:
            self.warning_cache.add(message)
            decky.logger.warning(message)
        
    async def _main(self):
        decky.logger.info("PowerDeck initializing...")
        
        # Log device support status
        decky.logger.info(f"Device support available: {device_support_available}")
        
        # Initialize hardware detection
        await self.detect_hardware()
        
        # Set system-derived defaults from processor database and hardware detection
        await self._set_system_derived_defaults()
        
        # CRITICAL: Store original unmodified hardware state before any profiles are applied
        # This ensures default profile creation uses true hardware defaults, not modified state
        self.original_hardware_defaults = await self._detect_actual_system_defaults()
        decky.logger.info(f"Preserved original hardware defaults: {self.original_hardware_defaults}")
        
        if device_support_available:
            try:
                # Initialize managers
                self.settings = PowerDeckSettings()
                self.device_manager = DeviceManager()
                # power_manager will be created by device_manager based on detected hardware
                self.profile_manager = ProfileManager()
                self.cpu_manager = CPUManager()
                
                # Initialize CPU topology mapping for efficient core management
                info_log("Initializing CPU topology mapping...")
                self.cpu_manager.initialize_cpu_topology()
                
                # Detect fan control availability
                try:
                    self.device_info["has_fan_control"] = steamfork_fan_controller.is_available()
                    info_log(f"Fan control detection: available={self.device_info['has_fan_control']}")
                except Exception as e:
                    error_log(f"Failed to detect fan control availability: {e}")
                    self.device_info["has_fan_control"] = False
                
                # Load unified profiles instead of old settings format
                await self.load_unified_profiles()
                
                # Initialize enhanced sleep/wake management
                if device_support_available:
                    try:
                        self.sleep_wake_manager = get_sleep_wake_manager(self)
                        await self.sleep_wake_manager.start_monitoring()
                        decky.logger.info("Enhanced sleep/wake management initialized")
                    except Exception as e:
                        decky.logger.error(f"Failed to initialize enhanced sleep/wake management: {e}")
                        # Fallback to original monitoring
                        asyncio.create_task(self.monitor_system_wake())
                        decky.logger.info("Falling back to basic sleep/wake monitoring")
                else:
                    # Fallback to original monitoring if device support unavailable
                    asyncio.create_task(self.monitor_system_wake())
                    decky.logger.info("Using basic sleep/wake monitoring (no device support)")
                
                # Start background update checking task (non-blocking)
                self.background_update_task = asyncio.create_task(self.background_update_checker())
                
                decky.logger.info(f"PowerDeck initialized for device: {self.device_info['device_name']}")
            except Exception as e:
                decky.logger.error(f"Failed to initialize device managers: {e}")
        else:
            decky.logger.warning("Running in fallback mode without device support")
        
    async def _unload(self):
        decky.logger.info("PowerDeck unloading...")
        
        # Stop enhanced sleep/wake monitoring
        if self.sleep_wake_manager:
            try:
                await self.sleep_wake_manager.stop_monitoring()
                decky.logger.info("Enhanced sleep/wake monitoring stopped")
            except Exception as e:
                decky.logger.error(f"Error stopping sleep/wake monitoring: {e}")
        
        # Cancel background update checker task
        if self.background_update_task:
            try:
                self.background_update_task.cancel()
                decky.logger.info("Background update checker cancelled")
            except Exception as e:
                decky.logger.error(f"Error cancelling background update checker: {e}")
        
    async def _uninstall(self):
        decky.logger.info("PowerDeck uninstalling...")

    async def _detect_actual_system_defaults(self) -> Dict[str, Any]:
        """Detect actual system defaults from current hardware state - eliminates hard-coding"""
        system_defaults = {}
        
        try:
            # Detect current CPU boost state
            try:
                with open("/sys/devices/system/cpu/cpufreq/boost", 'r') as f:
                    boost_value = f.read().strip()
                    system_defaults["cpuBoost"] = boost_value == "1"
                    decky.logger.info(f"Detected system default CPU boost: {system_defaults['cpuBoost']}")
            except:
                system_defaults["cpuBoost"] = True  # Default to enabled - typical system behavior
                
            # Detect current SMT state
            try:
                with open("/sys/devices/system/cpu/smt/control", 'r') as f:
                    smt_value = f.read().strip()
                    system_defaults["smt"] = smt_value == "on"
                    decky.logger.info(f"Detected system default SMT: {system_defaults['smt']}")
            except:
                system_defaults["smt"] = True  # Conservative fallback
                
            # Detect current CPU governor
            try:
                with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", 'r') as f:
                    governor = f.read().strip()
                    system_defaults["governor"] = governor
                    decky.logger.info(f"Detected system default governor: {governor}")
            except:
                system_defaults["governor"] = "powersave"  # Conservative fallback
                
            # Detect current EPP setting
            try:
                with open("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference", 'r') as f:
                    epp = f.read().strip()
                    system_defaults["epp"] = epp
                    decky.logger.info(f"Detected system default EPP: {epp}")
            except:
                system_defaults["epp"] = "balance_performance"  # Conservative fallback
                
            # Detect current online CPU cores
            try:
                with open("/sys/devices/system/cpu/online", 'r') as f:
                    online_range = f.read().strip()
                    # Parse "0-11" format
                    if '-' in online_range:
                        max_online = int(online_range.split('-')[-1])
                        online_cores = max_online + 1
                    else:
                        online_cores = 1
                    system_defaults["cpuCores"] = online_cores
                    decky.logger.info(f"Detected system default online cores: {online_cores}")
            except:
                system_defaults["cpuCores"] = 8  # Conservative fallback
                
            decky.logger.info(f"Detected system defaults: {system_defaults}")
            return system_defaults
            
        except Exception as e:
            decky.logger.error(f"Failed to detect system defaults: {e}")
            # Return conservative defaults as fallback
            return {
                "cpuBoost": True,
                "smt": True, 
                "governor": "powersave",
                "epp": "balance_performance",
                "cpuCores": 8
            }

    async def _set_system_derived_defaults(self):
        """Set all default values from processor database and system detection - eliminates hard-coding"""
        try:
            decky.logger.info("Setting system-derived defaults from processor database and sysfs")
            
            # First, detect actual system defaults from hardware
            system_defaults = await self._detect_actual_system_defaults()
            
            # Get processor-based defaults
            if processor_support_available:
                try:
                    # Get TDP limits from processor database
                    tdp_min, tdp_max = get_processor_tdp_limits()  # Returns (4, database_max)
                    
                    # CORRECTED: Use processor tdp_min as PowerDeck default (NOT default_tdp)
                    processor_info = get_current_processor_info()
                    if processor_info.get("detected"):
                        # Use the processor's minimum TDP as PowerDeck default (15W for 7840U)
                        tdp_default = processor_info.get("tdp_min", 15)
                    else:
                        # Fallback conservative default
                        tdp_default = 15
                    
                    # Update TDP limits and defaults
                    self.tdp_limits = {"min": tdp_min, "max": tdp_max}
                    self.device_info["min_tdp"] = tdp_min
                    self.device_info["max_tdp"] = tdp_max
                    
                    # Set PowerDeck default TDP from processor minimum TDP
                    if self.current_profile["tdp"] is None:
                        self.current_profile["tdp"] = tdp_default
                        decky.logger.info(f"Set PowerDeck default TDP to processor minimum: {tdp_default}W")
                    
                    decky.logger.info(f"Applied processor database TDP limits: {tdp_min}W - {tdp_max}W (PowerDeck default: {tdp_default}W)")
                    
                except Exception as e:
                    decky.logger.warning(f"Failed to get processor database TDP values: {e}")
                    # Try to get fallback values from processor detection if available
                    try:
                        if processor_support_available:
                            fallback_min, fallback_max = get_processor_tdp_limits()
                            self.tdp_limits = {"min": fallback_min, "max": fallback_max}
                            self.device_info["min_tdp"] = fallback_min
                            self.device_info["max_tdp"] = fallback_max
                            decky.logger.info(f"Used processor detection fallback TDP limits: {fallback_min}W - {fallback_max}W")
                        else:
                            # Last resort conservative defaults only if processor database completely unavailable
                            self.tdp_limits = {"min": 4, "max": 25}
                            self.device_info["min_tdp"] = 4
                            self.device_info["max_tdp"] = 25
                            decky.logger.warning("Using last resort TDP limits: 4W - 25W")
                    except:
                        # Absolute final fallback
                        self.tdp_limits = {"min": 4, "max": 25}
                        self.device_info["min_tdp"] = 4
                        self.device_info["max_tdp"] = 25
                        decky.logger.warning("Using absolute fallback TDP limits: 4W - 25W")
                    if self.current_profile["tdp"] is None:
                        self.current_profile["tdp"] = 15
            else:
                # Fallback when processor database unavailable - try detection first
                decky.logger.warning("Processor database unavailable, attempting detection fallback")
                try:
                    if processor_support_available:
                        fallback_min, fallback_max = get_processor_tdp_limits()
                        self.tdp_limits = {"min": fallback_min, "max": fallback_max}
                        self.device_info["min_tdp"] = fallback_min
                        self.device_info["max_tdp"] = fallback_max
                        if self.current_profile["tdp"] is None:
                            fallback_default = get_processor_default_tdp()
                            self.current_profile["tdp"] = fallback_default
                        decky.logger.info(f"Used detection fallback: {fallback_min}W - {fallback_max}W")
                    else:
                        # Last resort only if no processor support at all
                        self.tdp_limits = {"min": 4, "max": 25}
                        self.device_info["min_tdp"] = 4
                        self.device_info["max_tdp"] = 25
                        if self.current_profile["tdp"] is None:
                            self.current_profile["tdp"] = 15
                        decky.logger.warning("Used absolute fallback TDP limits: 4W - 25W")
                except:
                    # Absolute last resort
                    self.tdp_limits = {"min": 4, "max": 25}
                    self.device_info["min_tdp"] = 4
                    self.device_info["max_tdp"] = 25
                    if self.current_profile["tdp"] is None:
                        self.current_profile["tdp"] = 15
                    decky.logger.warning("Used emergency fallback TDP limits: 4W - 25W")
            
            # Apply detected system defaults to current profile
            for key, value in system_defaults.items():
                if self.current_profile.get(key) is None:
                    self.current_profile[key] = value
                    decky.logger.info(f"Set {key} to system default: {value}")
            
            # Ensure hardware-detected CPU core count is used
            detected_cores = system_defaults.get("cpuCores", 8)
            self.device_info["max_cpu_cores"] = detected_cores
            decky.logger.info(f"Set CPU cores to system-detected value: {detected_cores}")
            
            decky.logger.info(f"System-derived defaults applied - TDP: {self.current_profile['tdp']}W, Cores: {self.current_profile['cpuCores']}, Boost: {self.current_profile['cpuBoost']}, SMT: {self.current_profile['smt']}")
            
        except Exception as e:
            decky.logger.error(f"Failed to set system-derived defaults: {e}")
            # Ensure we have some working defaults even if everything fails
            if self.current_profile["tdp"] is None:
                decky.logger.warning("TDP still None after all attempts, using emergency fallback")
                self.current_profile["tdp"] = 15
            if self.current_profile["cpuCores"] is None:
                decky.logger.warning("CPU cores still None after all attempts, using emergency fallback")
                self.current_profile["cpuCores"] = 8

    async def detect_hardware(self):
        """Detect actual hardware using DMI and system information"""
        try:
            # Get device information from DMI
            device_name = await self.read_file_safe("/sys/class/dmi/id/product_name")
            sys_vendor = await self.read_file_safe("/sys/class/dmi/id/sys_vendor")
            board_name = await self.read_file_safe("/sys/class/dmi/id/board_name")
            
            if device_name:
                self.device_info["device_name"] = f"{sys_vendor} {device_name}".strip()
            
            # Detect CPU vendor
            cpu_vendor = await self.get_cpu_vendor()
            if cpu_vendor:
                self.device_info["cpu_vendor"] = cpu_vendor
            
            # Detect processor specifications using processor database
            if processor_support_available:
                try:
                    self.processor_info = get_current_processor_info()
                    decky.logger.info(f"Processor detected: {self.processor_info.get('processor_name', 'Unknown')}")
                    
                    # Update device info with processor capabilities
                    if self.processor_info.get('detected', False):
                        # Don't use processor DB for core count - always detect from hardware
                        self.device_info["max_cpu_cores"] = await self.detect_max_cpu_cores()
                        self.device_info["cpu_model"] = self.processor_info.get('processor_name', 'Unknown')
                        self.device_info["cpu_family"] = self.processor_info.get('family', 'Unknown')
                        self.device_info["cpu_series"] = self.processor_info.get('series', 'Unknown')
                        self.device_info["form_factor"] = self.processor_info.get('form_factor', 'Unknown')
                        self.device_info["node_process"] = self.processor_info.get('node_process', 'Unknown')
                        self.device_info["gpu_model"] = self.processor_info.get('gpu_model', 'Unknown')
                        self.device_info["gpu_cu_count"] = self.processor_info.get('gpu_cu_count', 8)
                        
                        # Update TDP limits based on processor specs
                        proc_tdp_min, proc_tdp_max = get_processor_tdp_limits()
                        self.tdp_limits = {"min": proc_tdp_min, "max": proc_tdp_max}
                        self.device_info["min_tdp"] = proc_tdp_min
                        self.device_info["max_tdp"] = proc_tdp_max
                        
                        # CORRECTED: Set PowerDeck default TDP from processor tdp_min (NOT default_tdp)
                        # PowerDeck default = processor minimum TDP for conservative startup
                        processor_min_tdp = self.processor_info.get('tdp_min')
                        if processor_min_tdp:
                            self.current_profile["tdp"] = processor_min_tdp
                            decky.logger.info(f"Set PowerDeck default TDP to processor minimum: {processor_min_tdp}W")
                        else:
                            decky.logger.warning("No processor tdp_min found, keeping current default")
                        
                        # Check if it's a handheld device
                        if is_handheld_device():
                            self.device_info["is_handheld"] = True
                            decky.logger.info("Detected handheld gaming device")
                        else:
                            self.device_info["is_handheld"] = False
                        
                        decky.logger.info(f"Processor TDP limits: {proc_tdp_min}W - {proc_tdp_max}W")
                        decky.logger.info(f"GPU: {self.processor_info.get('gpu_model')} ({self.processor_info.get('gpu_cu_count')} CUs)")
                    
                except Exception as e:
                    decky.logger.warning(f"Processor detection failed: {e}")
                    self.processor_info = None
            
            # Detect CPU core count (hardware maximum, not just currently online)
            if not self.device_info.get("max_cpu_cores"):
                try:
                    self.device_info["max_cpu_cores"] = await self.detect_max_cpu_cores()
                except Exception as e:
                    decky.logger.warning(f"Failed to detect max CPU cores: {e}")
                    # Even in fallback, try to read from sysfs before giving up
                    try:
                        with open('/sys/devices/system/cpu/possible', 'r') as f:
                            possible_range = f.read().strip()
                        max_cpu = int(possible_range.split('-')[-1])
                        self.device_info["max_cpu_cores"] = max_cpu + 1
                        decky.logger.info(f"Fallback sysfs detection found {max_cpu + 1} cores")
                    except:
                        # Try processor database as final attempt before absolute fallback
                        try:
                            if processor_support_available:
                                processor_info = get_current_processor_info()
                                if processor_info.get("detected") and processor_info.get("max_cpu_cores"):
                                    self.device_info["max_cpu_cores"] = processor_info["max_cpu_cores"]
                                    decky.logger.info(f"Fallback processor database found {processor_info['max_cpu_cores']} cores")
                                else:
                                    self.device_info["max_cpu_cores"] = 8  # Conservative fallback
                                    decky.logger.warning("Used conservative fallback: 8 cores")
                            else:
                                self.device_info["max_cpu_cores"] = 8  # Conservative fallback  
                                decky.logger.warning("Used conservative fallback: 8 cores")
                        except:
                            self.device_info["max_cpu_cores"] = 8  # Absolute last resort
                            decky.logger.warning("Used absolute last resort: 8 cores")
            
            # Check for ryzenadj availability
            self.ryzenadj_path = self._find_ryzenadj_binary()
            
            # Initialize device-specific controller
            await self._initialize_device_controller()
            
            # Detect device-specific capabilities
            await self.detect_capabilities()
            
            decky.logger.info(f"Detected device: {self.device_info['device_name']}")
            decky.logger.info(f"CPU vendor: {self.device_info['cpu_vendor']}")
            decky.logger.info(f"Ryzenadj available: {bool(self.ryzenadj_path)}")
            
        except Exception as e:
            decky.logger.error(f"Hardware detection failed: {e}")

    def _find_ryzenadj_binary(self) -> Optional[str]:
        """Find RyzenAdj binary in system paths"""
        # Check standard system locations in order of preference
        potential_paths = [
            "/usr/bin/ryzenadj",           # System-wide installation
            "/opt/ryzenadj/bin/ryzenadj",  # PowerDeck installation location
            "/usr/local/bin/ryzenadj",     # Alternative system location
        ]
        
        for path in potential_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                decky.logger.info(f"Found RyzenAdj binary at: {path}")
                return path
        
        # Fallback to PATH search
        ryzenadj_path = shutil.which('ryzenadj')
        if ryzenadj_path:
            decky.logger.info(f"Found RyzenAdj binary in PATH: {ryzenadj_path}")
            return ryzenadj_path
            
        decky.logger.warning("RyzenAdj binary not found - TDP control may be limited")
        return None

    async def _initialize_device_controller(self):
        """Initialize device-specific controller based on detected hardware"""
        try:
            device_name = self.device_info.get("device_name", "").lower()
            
            # ROG Ally detection - only determines control method, not capabilities
            if ("rog ally" in device_name or "rc71" in device_name or "rc72" in device_name) and ROG_ALLY_AVAILABLE:
                self.device_controller = get_rog_ally_controller()
                self.device_type = "rog_ally"
                decky.logger.info("Initialized ROG Ally controller")
                
                # Update device info with ROG Ally specifics (non-TDP info only)
                ally_info = self.device_controller.get_device_info()
                # Only copy non-TDP related device info
                for key, value in ally_info.items():
                    if "tdp" not in key.lower() and "limit" not in key.lower():
                        self.device_info[key] = value
                
            # Legion Go detection - only determines control method, not capabilities
            elif ("legion" in device_name or "83e1" in device_name or "83l3" in device_name) and LEGION_AVAILABLE:
                self.device_controller = get_legion_controller()
                self.device_type = "legion"
                decky.logger.info("Initialized Legion controller")
                
                # Update device info with Legion specifics (non-TDP info only)
                legion_info = self.device_controller.get_device_info()
                # Only copy non-TDP related device info
                for key, value in legion_info.items():
                    if "tdp" not in key.lower() and "limit" not in key.lower():
                        self.device_info[key] = value
                
            # Steam Deck detection - only determines control method, not capabilities
            elif ("steam deck" in device_name or "jupiter" in device_name) and STEAM_DECK_AVAILABLE:
                self.device_controller = get_steam_deck_controller()
                self.device_type = "steam_deck"
                decky.logger.info("Initialized Steam Deck controller")
                
                # Update device info with Steam Deck specifics (non-TDP info only)
                deck_info = self.device_controller.get_device_info()
                # Only copy non-TDP related device info
                for key, value in deck_info.items():
                    if "tdp" not in key.lower() and "limit" not in key.lower():
                        self.device_info[key] = value
                
            # Generic AMD/Intel device
            else:
                self.device_type = "generic"
                decky.logger.info("Using generic power management")
            
            # TDP limits will be set later from processor database or sysfs detection
            # This ensures all devices use the same system-derived approach
            decky.logger.info(f"Device controller initialized as {self.device_type} - TDP limits will be determined from processor database")
                    
        except Exception as e:
            decky.logger.error(f"Failed to initialize device controller: {e}")
            self.device_type = "generic"

    async def read_file_safe(self, path: str) -> Optional[str]:
        """Safely read a file and return its content"""
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except:
            return None

    async def get_cpu_vendor(self) -> Optional[str]:
        """Get CPU vendor from /proc/cpuinfo"""
        try:
            with open("/proc/cpuinfo", 'r') as f:
                content = f.read()
                for line in content.split('\n'):
                    if line.startswith('vendor_id'):
                        vendor = line.split(':')[1].strip()
                        if vendor == "AuthenticAMD":
                            return "AMD"
                        elif vendor == "GenuineIntel":
                            return "Intel"
                        else:
                            return vendor
        except:
            pass
        return None

    async def detect_capabilities(self):
        """Detect what power management capabilities are available"""
        try:
            # Check TDP support
            if self.device_info["cpu_vendor"] == "Intel":
                # Intel uses RAPL
                intel_rapl_paths = [
                    "/sys/devices/virtual/powercap/intel-rapl-mmio/intel-rapl-mmio:0",
                    "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0"
                ]
                self.device_info["supports_tdp"] = any(os.path.exists(path) for path in intel_rapl_paths)
                if self.device_info["supports_tdp"]:
                    # Get Intel TDP limits from hardware - only update max if not already set by processor database
                    intel_limits = await self.get_intel_tdp_limits()
                    if intel_limits and self.device_info.get("max_tdp") is None:
                        self.device_info["min_tdp"] = intel_limits[0]
                        self.device_info["max_tdp"] = intel_limits[1]
                        self.tdp_limits = {"min": intel_limits[0], "max": intel_limits[1]}
                        decky.logger.info(f"Intel RAPL TDP limits detected: {intel_limits[0]}W - {intel_limits[1]}W")
            else:
                # AMD uses ryzenadj or device-specific methods
                self.device_info["supports_tdp"] = bool(self.ryzenadj_path)
                # TDP limits are already set from processor database in _set_system_derived_defaults()
                # Do not override with hard-coded fallback values here
            
            # Check CPU boost support
            cpu_boost_paths = [
                "/sys/devices/system/cpu/intel_pstate/no_turbo",  # Intel
                "/sys/devices/system/cpu/cpufreq/policy0/boost"   # AMD
            ]
            self.device_info["supports_cpu_boost"] = any(os.path.exists(path) for path in cpu_boost_paths)
            
            # Check SMT support
            self.device_info["supports_smt"] = os.path.exists("/sys/devices/system/cpu/smt/control")
            
            # Check GPU control support - both AMD and Intel
            amd_gpu_control_paths = [
                "/sys/class/drm/card0/device/power_dpm_force_performance_level",
                "/sys/class/drm/card1/device/power_dpm_force_performance_level"
            ]
            amd_gpu_support = any(os.path.exists(path) for path in amd_gpu_control_paths)
            
            # Check Intel GPU support via sysfs power manager
            intel_gpu_capabilities = sysfs_power_manager.get_capabilities()
            intel_gpu_support = intel_gpu_capabilities.supports_intel_gpu
            
            self.device_info["supports_gpu_control"] = amd_gpu_support or intel_gpu_support
            
            if self.device_info["supports_gpu_control"]:
                # Get GPU frequency limits (works for both AMD and Intel)
                await self.detect_gpu_limits()

            # Universal power management feature detection
            await self.detect_universal_power_features()
                
        except Exception as e:
            decky.logger.error(f"Capability detection failed: {e}")

    async def detect_universal_power_features(self):
        """Detect universal power management features available on any device"""
        try:
            # PCIe ASPM support
            aspm_path = "/sys/module/pcie_aspm/parameters/policy"
            self.device_info["supports_pcie_aspm"] = os.path.exists(aspm_path)
            
            # CPU C-State management
            cstate_path = "/sys/devices/system/cpu/cpu0/cpuidle"
            self.device_info["supports_cstate_control"] = os.path.exists(cstate_path)
            
            # USB power management
            usb_power_path = "/sys/bus/usb/devices"
            self.device_info["supports_usb_power_mgmt"] = os.path.exists(usb_power_path)
            
            # WiFi power saving detection
            self.device_info["supports_wifi_power_save"] = await self.detect_wifi_interfaces()
            
            # Memory pressure controls
            self.device_info["supports_memory_tuning"] = os.path.exists("/proc/sys/vm/swappiness")
            
            # Audio power management
            audio_power_path = "/sys/class/sound"
            self.device_info["supports_audio_power_mgmt"] = os.path.exists(audio_power_path)
            
            decky.logger.info(f"Universal power features detected: ASPM={self.device_info.get('supports_pcie_aspm')}, "
                            f"C-States={self.device_info.get('supports_cstate_control')}, "
                            f"USB={self.device_info.get('supports_usb_power_mgmt')}, "
                            f"WiFi={self.device_info.get('supports_wifi_power_save')}, "
                            f"Memory={self.device_info.get('supports_memory_tuning')}, "
                            f"Audio={self.device_info.get('supports_audio_power_mgmt')}")
                            
        except Exception as e:
            decky.logger.error(f"Universal power feature detection failed: {e}")

    async def detect_wifi_interfaces(self) -> bool:
        """Detect if WiFi interfaces are available for power management"""
        try:
            # Check for wireless interfaces
            with open("/proc/net/wireless", "r") as f:
                lines = f.readlines()
                return len(lines) > 2  # Header lines + at least one interface
        except:
            return False

    async def get_intel_tdp_limits(self) -> Optional[tuple]:
        """Get Intel TDP limits from RAPL"""
        try:
            max_power_paths = [
                "/sys/devices/virtual/powercap/intel-rapl-mmio/intel-rapl-mmio:0/constraint_0_max_power_uw",
                "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/constraint_0_max_power_uw"
            ]
            
            for path in max_power_paths:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        max_power_uw = int(f.read().strip())
                        max_tdp = max_power_uw // 1000000  # Convert to watts
                        return (4, max_tdp)  # Min 4W, max from hardware
        except:
            pass
        return None

    async def detect_gpu_limits(self):
        """Detect GPU frequency limits - supports both AMD and Intel GPUs"""
        try:
            # Check if Intel GPU is available via sysfs power manager
            intel_gpu_capabilities = sysfs_power_manager.get_capabilities()
            if intel_gpu_capabilities.supports_intel_gpu:
                # Intel GPU limits from sysfs power manager
                if intel_gpu_capabilities.gpu_min_freq_mhz and intel_gpu_capabilities.gpu_max_freq_mhz:
                    self.device_info["min_gpu_freq"] = intel_gpu_capabilities.gpu_min_freq_mhz
                    self.device_info["max_gpu_freq"] = intel_gpu_capabilities.gpu_max_freq_mhz
                    decky.logger.info(f"Intel GPU limits detected: {intel_gpu_capabilities.gpu_min_freq_mhz}-{intel_gpu_capabilities.gpu_max_freq_mhz} MHz")
                else:
                    # Fallback values for Intel GPU
                    self.device_info["min_gpu_freq"] = 300
                    self.device_info["max_gpu_freq"] = 1100
                    decky.logger.info("Intel GPU limits using fallback values: 300-1100 MHz")
            else:
                # Check for AMD GPU overdrive
                od_clk_path = "/sys/class/drm/card0/device/pp_od_clk_voltage"
                if os.path.exists(od_clk_path):
                    with open(od_clk_path, 'r') as f:
                        content = f.read()
                        lines = content.split('\n')
                        for line in lines:
                            if line.startswith('SCLK:'):
                                parts = line.split()
                                if len(parts) >= 3:
                                    min_freq = int(parts[1].replace('Mhz', ''))
                                    max_freq = int(parts[2].replace('Mhz', ''))
                                    self.device_info["min_gpu_freq"] = min_freq
                                    self.device_info["max_gpu_freq"] = max_freq
                                    decky.logger.info(f"AMD GPU limits detected: {min_freq}-{max_freq} MHz")
                                    break
        except Exception as e:
            decky.logger.error(f"GPU limit detection failed: {e}")

    async def load_saved_settings(self):
        """Load saved settings and profiles"""
        try:
            if self.settings:
                decky.logger.info(f"LOAD_SETTINGS: Starting to load saved settings")
                saved_settings = self.settings.get("powerDeckSettings", {})
                decky.logger.info(f"LOAD_SETTINGS: Found saved settings: {saved_settings}")
                
                if "currentProfile" in saved_settings:
                    old_profile = self.current_profile.copy()
                    self.current_profile.update(saved_settings["currentProfile"])
                    decky.logger.info(f"LOAD_SETTINGS: Updated current profile from {old_profile} to {self.current_profile}")
                else:
                    decky.logger.warning(f"LOAD_SETTINGS: No currentProfile found in saved settings")
                    
                if "tdpLimits" in saved_settings:
                    old_limits = self.tdp_limits.copy()
                    self.tdp_limits.update(saved_settings["tdpLimits"])
                    decky.logger.info(f"LOAD_SETTINGS: Updated TDP limits from {old_limits} to {self.tdp_limits}")
                    
                if "enablePerGameProfiles" in saved_settings:
                    self.enable_per_game_profiles = saved_settings["enablePerGameProfiles"]
                    decky.logger.info(f"LOAD_SETTINGS: Set enablePerGameProfiles to {self.enable_per_game_profiles}")
                    
                if "rogAllyNativeTdpEnabled" in saved_settings:
                    self.rog_ally_native_tdp_enabled = saved_settings["rogAllyNativeTdpEnabled"]
                    decky.logger.info(f"LOAD_SETTINGS: Set rogAllyNativeTdpEnabled to {self.rog_ally_native_tdp_enabled}")
                else:
                    # Default to True for ROG Ally devices, False for others if not found in settings
                    self.rog_ally_native_tdp_enabled = await self.is_rog_ally_device()
                    decky.logger.info(f"LOAD_SETTINGS: Set default rogAllyNativeTdpEnabled to {self.rog_ally_native_tdp_enabled} (ROG Ally device: {await self.is_rog_ally_device()})")
            else:
                decky.logger.error(f"LOAD_SETTINGS: self.settings is None!")
        except Exception as e:
            decky.logger.error(f"Failed to load saved settings: {e}")

    async def save_settings(self):
        """Save current settings"""
        try:
            if self.settings:
                settings_data = {
                    "currentProfile": self.current_profile,
                    "tdpLimits": self.tdp_limits,
                    "enablePerGameProfiles": self.enable_per_game_profiles,
                    "rogAllyNativeTdpEnabled": self.rog_ally_native_tdp_enabled
                }
                decky.logger.info(f"SAVE_SETTINGS: Saving settings data: {settings_data}")
                self.settings.set("powerDeckSettings", settings_data)
                decky.logger.info(f"SAVE_SETTINGS: Settings saved successfully")
            else:
                decky.logger.error(f"SAVE_SETTINGS: self.settings is None!")
        except Exception as e:
            decky.logger.error(f"Failed to save settings: {e}")

    async def get_ac_power_status_with_retry(self, max_retries: int = 5, delay_seconds: float = 2.0) -> bool:
        """Get AC power status with retry logic for initialization during boot"""
        import asyncio
        
        for attempt in range(max_retries):
            try:
                decky.logger.info(f"AC power detection attempt {attempt + 1}/{max_retries}")
                
                # Check multiple common AC power supply paths for broader device compatibility
                ac_paths = [
                    "/sys/class/power_supply/ACAD/online",  # Generic/ROG Ally
                    "/sys/class/power_supply/ADP1/online",  # Ayaneo Air and many laptops
                    "/sys/class/power_supply/AC/online",    # Some other devices
                    "/sys/class/power_supply/ADP0/online"   # Alternative naming
                ]
                
                ac_connected = False
                detected_path = None
                
                for ac_path in ac_paths:
                    if os.path.exists(ac_path):
                        try:
                            with open(ac_path, 'r') as f:
                                ac_value = f.read().strip()
                                ac_connected = ac_value == "1"
                                detected_path = ac_path
                                decky.logger.info(f"AC detection via {ac_path}: {ac_connected} (value: {ac_value})")
                                break  # Use first available path
                        except Exception as e:
                            decky.logger.warning(f"Failed to read AC power from {ac_path}: {e}")
                            continue
                
                if detected_path:
                    # If we detect AC power, return immediately (no need to retry)
                    if ac_connected:
                        decky.logger.info(f"AC power confirmed on attempt {attempt + 1} via {detected_path}")
                        return True
                    
                    # If AC not detected but this isn't the last attempt, continue retrying
                    if attempt < max_retries - 1:
                        decky.logger.info(f"AC not detected on attempt {attempt + 1} via {detected_path}, will retry...")
                        
                    # Return False if this was the last attempt and no AC detected
                    elif attempt == max_retries - 1:
                        decky.logger.info(f"Final attempt: AC not connected via {detected_path}")
                        return False
                        
                else:
                    decky.logger.warning(f"No AC power supply paths found on attempt {attempt + 1}")
                
                # Wait before next retry (except on last attempt)
                if attempt < max_retries - 1:
                    decky.logger.info(f"Waiting {delay_seconds}s before retry...")
                    await asyncio.sleep(delay_seconds)
                    
            except Exception as e:
                decky.logger.warning(f"AC power detection attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay_seconds)
                    
        # If all attempts failed to detect AC, default to AC mode for better user experience
        # (Better to have higher TDP than to be stuck at low battery TDP)
        decky.logger.warning("All AC power detection attempts failed, defaulting to AC mode for safety")
        return True

    async def load_unified_profiles(self):
        """Load settings from unified profile system instead of old settings format"""
        try:
            debug_log("Starting unified profile loading")
            
            # Detect current power state with retry logic for reliable boot detection
            ac_connected = await self.get_ac_power_status_with_retry()
            power_mode = "ac" if ac_connected else "battery"
            profile_id = f"00000000_{power_mode}"
            
            debug_log(f"Loading unified profile for power mode: {power_mode} (AC: {ac_connected})")
            decky.logger.info(f"BOOT INITIALIZATION: Power mode detected as {power_mode} (AC: {ac_connected})")
            
            # Load the appropriate default profile
            profile_data = await self.load_profile(profile_id)
            if profile_data:
                debug_log(f"Successfully loaded unified profile {profile_id}: {profile_data}")
                
                # CRITICAL FIX: Use processor tdp_min as PowerDeck default (NOT default_tdp)
                # PowerDeck default TDP = processor minimum TDP, range = 4W to processor max TDP
                processor_min_tdp = 15  # Fallback default
                if processor_support_available:
                    try:
                        from processor_detection import get_current_processor_info
                        proc_info = get_current_processor_info()
                        if proc_info and proc_info.get('detected', False):
                            processor_min_tdp = proc_info.get('tdp_min', 15)
                    except Exception:
                        pass
                
                loaded_tdp = profile_data.get("tdp", 10)  # TDP from saved profile
                
                # SAFETY CHECK: Never force TDP to unreasonable values
                if processor_min_tdp <= 0 or processor_min_tdp > 30:
                    processor_min_tdp = 15  # Safe fallback for handheld devices
                    decky.logger.warning(f"Processor database returned invalid minimum TDP {processor_min_tdp}W, using fallback 15W")
                
                # CRITICAL FIX: Validate CPU boost against true system defaults (enabled by default)
                # CPU boost should be enabled by default on most systems - PowerDeck should not disable it by default
                expected_cpu_boost = True  # True system default - users can disable manually if desired
                loaded_cpu_boost = profile_data.get("cpuBoost", False)  # CPU boost from saved profile
                
                profile_updated = False
                
                # IMPORTANT: Only update profiles if they have clearly invalid values (0W TDP)
                # Do NOT override user preferences with processor database values
                if loaded_tdp <= 0:
                    decky.logger.info(f"INVALID TDP: Profile has {loaded_tdp}W, setting to processor minimum {processor_min_tdp}W")
                    profile_data["tdp"] = processor_min_tdp
                    profile_updated = True
                else:
                    decky.logger.info(f"USER TDP PRESERVED: Profile TDP {loaded_tdp}W is valid, keeping user preference")
                    
                if loaded_cpu_boost != expected_cpu_boost:
                    decky.logger.info(f"CPU BOOST MISMATCH: Profile has {loaded_cpu_boost}, system default should be {expected_cpu_boost} - updating profile")
                    profile_data["cpuBoost"] = expected_cpu_boost
                    profile_updated = True
                
                if profile_updated:
                    # Save the corrected profile back to disk
                    await self.save_profile({"gameId": profile_id, **profile_data})
                    decky.logger.info(f"Updated profile {profile_id} with processor database values")
                    
                    # CRITICAL: Also update the companion profile (AC/battery) to maintain consistency
                    companion_mode = "battery" if power_mode == "ac" else "ac" 
                    companion_id = f"00000000_{companion_mode}"
                    companion_profile = await self.load_profile(companion_id)
                    if companion_profile:
                        companion_updated = False
                        companion_tdp = companion_profile.get("tdp", 0)
                        # Only fix companion profile if it has invalid TDP (0W or negative)
                        if companion_tdp <= 0:
                            companion_profile["tdp"] = processor_min_tdp
                            companion_updated = True
                            decky.logger.info(f"Fixed companion profile {companion_id} invalid TDP: {companion_tdp}W -> {processor_min_tdp}W")
                        if companion_profile.get("cpuBoost") != expected_cpu_boost:
                            companion_profile["cpuBoost"] = expected_cpu_boost
                            companion_updated = True
                        if companion_updated:
                            await self.save_profile({"gameId": companion_id, **companion_profile})
                            decky.logger.info(f"Updated companion profile {companion_id} for consistency")
                else:
                    decky.logger.info(f"PROFILE VALIDATED: TDP {loaded_tdp}W and CPU boost {loaded_cpu_boost} match system defaults")
                
                self.current_profile.update(profile_data)
                
                # CRITICAL FIX: Apply the profile immediately during initialization
                # This ensures the correct power settings are active from boot
                try:
                    apply_success = await self.apply_profile(profile_data)
                    if apply_success:
                        decky.logger.info(f"Applied power profile {profile_id} during initialization")
                    else:
                        decky.logger.warning(f"Partial failure applying profile {profile_id} during initialization")
                except Exception as e:
                    decky.logger.error(f"Failed to apply profile during initialization: {e}")
            else:
                debug_log(f"No unified profile found for {profile_id}, creating from original hardware defaults")
                
                # CRITICAL FIX: Create profiles from original unmodified hardware state
                # This ensures AC and battery profiles have identical values from true system defaults
                if self.original_hardware_defaults:
                    # Start with preserved original hardware defaults (unmodified state)
                    system_profile = self.original_hardware_defaults.copy()
                    
                    # Add TDP from processor database (already set in current_profile during _set_system_derived_defaults)
                    system_profile["tdp"] = self.current_profile.get("tdp", 15)
                    
                    # Ensure all required profile fields are present with system defaults
                    required_fields = ["cpuBoost", "smt", "cpuCores", "governor", "epp"]
                    for field in required_fields:
                        if field not in system_profile:
                            system_profile[field] = self.current_profile.get(field)
                            
                    debug_log(f"Creating profiles from original hardware defaults: {system_profile}")
                else:
                    # Fallback to current profile if original defaults not available
                    system_profile = self.current_profile.copy()
                    debug_log(f"Fallback: Creating profiles from current profile: {system_profile}")
                
                # Create identical AC and battery profiles from true system defaults
                await self.save_profile({"gameId": "00000000_ac", **system_profile})
                await self.save_profile({"gameId": "00000000_battery", **system_profile})
                decky.logger.info(f"Created identical default profiles with original hardware defaults: {system_profile}")
                
                # Apply the system-derived defaults to ensure settings are active
                try:
                    await self.apply_profile(system_profile)
                    decky.logger.info(f"Applied original hardware default profile during initialization")
                except Exception as e:
                    decky.logger.error(f"Failed to apply original hardware default profile during initialization: {e}")
                
            # Enable per-game profiles by default (as per cleanup requirements)
            self.enable_per_game_profiles = True
            debug_log(f"Enabled per-game profiles by default: {self.enable_per_game_profiles}")
            
            # ROG Ally native TDP support - this is loaded from saved settings, not reset here
            debug_log(f"ROG Ally native TDP support loaded from settings: {self.rog_ally_native_tdp_enabled}")
            
            # Migrate from old settings format if they exist
            await self._migrate_old_settings_to_unified()
            
        except Exception as e:
            decky.logger.error(f"Failed to load unified profiles: {e}")

    async def _migrate_old_settings_to_unified(self):
        """Migrate old powerdeck_settings.json to unified profile format"""
        try:
            if not self.settings:
                return
                
            saved_settings = self.settings.get("powerDeckSettings", {})
            if not saved_settings:
                debug_log("No old settings to migrate")
                return
                
            debug_log("Migrating old settings to unified profile format")
            
            # Extract current profile from old format
            if "currentProfile" in saved_settings:
                current_profile = saved_settings["currentProfile"]
                
                # CRITICAL FIX: Create identical AC and battery profiles using system-derived values
                # Use the current system-derived profile as the base for both AC and battery
                system_derived_profile = self.current_profile.copy()
                
                # Merge old settings with system-derived defaults (system values take precedence for missing fields)
                for key, value in current_profile.items():
                    if key in system_derived_profile:
                        system_derived_profile[key] = value
                
                # Save identical profiles for both AC and battery modes
                await self.save_profile({"gameId": "00000000_ac", **system_derived_profile})
                await self.save_profile({"gameId": "00000000_battery", **system_derived_profile})
                
                debug_log(f"Migrated to identical AC and battery profiles using system-derived defaults: {system_derived_profile}")
            else:
                # If no old profile exists, create identical AC and battery profiles from current system-derived defaults
                system_profile = self.current_profile.copy()
                await self.save_profile({"gameId": "00000000_ac", **system_profile})
                await self.save_profile({"gameId": "00000000_battery", **system_profile})
                debug_log(f"Created identical default AC and battery profiles from system-derived values: {system_profile}")
            
            # Extract per-game profiles setting
            if "enablePerGameProfiles" in saved_settings:
                self.enable_per_game_profiles = saved_settings["enablePerGameProfiles"]
                debug_log(f"Migrated enablePerGameProfiles setting: {self.enable_per_game_profiles}")
                
            # Mark migration as complete by clearing old settings
            self.settings.set("powerDeckSettings", {})
            debug_log("Migration completed, cleared old settings")
            
        except Exception as e:
            decky.logger.error(f"Failed to migrate old settings: {e}")

    async def get_scaling_driver(self) -> str:
        """Get current CPU scaling driver"""
        try:
            driver_path = "/sys/devices/system/cpu/cpufreq/policy0/scaling_driver"
            if os.path.exists(driver_path):
                with open(driver_path, 'r') as f:
                    driver_name = f.read().strip()
                    return driver_name
            else:
                # Fallback: check CPU vendor and make educated guess
                cpu_vendor = self.device_info.get("cpu_vendor", "unknown")
                if cpu_vendor == "AMD":
                    return "amd-pstate-epp"  # Common for modern AMD APUs
                elif cpu_vendor == "Intel":
                    return "intel_pstate"
                else:
                    return "acpi-cpufreq"  # Generic fallback
        except Exception as e:
            decky.logger.error(f"Failed to detect scaling driver: {e}")
            return "unknown"

    # Frontend API methods
    async def get_device_info(self) -> Dict[str, Any]:
        """Get comprehensive device information"""
        try:
            # PRIORITY: Add scaling driver detection FIRST for governor awareness
            try:
                scaling_driver = await self.get_scaling_driver()
                self.device_info["scalingDriver"] = scaling_driver
                decky.logger.info(f"SCALING DRIVER DETECTED: {scaling_driver}")
                decky.logger.info(f"DEVICE_INFO UPDATED WITH: scalingDriver={self.device_info['scalingDriver']}")
            except Exception as e:
                decky.logger.error(f"SCALING DRIVER DETECTION FAILED: {e}")
                self.device_info["scalingDriver"] = "unknown"

            # Always refresh CPU core count to ensure accurate detection
            try:
                self.device_info["max_cpu_cores"] = await self.detect_max_cpu_cores()
                decky.logger.info(f"Refreshed max_cpu_cores: {self.device_info['max_cpu_cores']}")
            except Exception as e:
                decky.logger.warning(f"Failed to refresh CPU core count: {e}")
            
            # Debug logging for GPU support
            decky.logger.info(f"Device info supports_gpu_control: {self.device_info.get('supports_gpu_control', False)}")
            decky.logger.info(f"Device info GPU fields: min_gpu_freq={self.device_info.get('min_gpu_freq')}, max_gpu_freq={self.device_info.get('max_gpu_freq')}")
            
            # Include processor information if available
            if self.processor_info:
                self.device_info["processor_info"] = self.processor_info
                
                # Add processor-specific capabilities to device info
                self.device_info["processor_detected"] = self.processor_info.get("detected", False)
                
                # NEW TDP LOGIC - get values from processor database
                if processor_support_available:
                    try:
                        # Get TDP limits: (hard_coded_min=4W, database_max)
                        tdp_min, tdp_max = get_processor_tdp_limits()
                        # Get default TDP from database ctdp_min  
                        tdp_default = get_processor_default_tdp()
                        
                        self.device_info["tdp_min"] = tdp_min        # Always 4W (hard-coded)
                        self.device_info["tdp_max"] = tdp_max        # From processor database ctdp_max
                        self.device_info["tdp_default"] = tdp_default # From processor database ctdp_min
                        
                        decky.logger.info(f"TDP Settings: min={tdp_min}W (hard-coded), default={tdp_default}W (DB ctdp_min), max={tdp_max}W (DB ctdp_max)")
                    except Exception as e:
                        decky.logger.warning(f"Failed to get processor TDP values: {e}")
                        # Fallback values
                        self.device_info["tdp_min"] = 4
                        self.device_info["tdp_max"] = 25  
                        self.device_info["tdp_default"] = 15
                
                self.device_info["recommended_profiles"] = self.processor_info.get("recommended_profiles", [])
            
            decky.logger.info(f"FINAL DEVICE INFO scalingDriver: {self.device_info.get('scalingDriver', 'MISSING')}")
            decky.logger.info(f"Device info keys: {list(self.device_info.keys())}")
            return self.device_info
        except Exception as e:
            decky.logger.error(f"Failed to get device info: {e}")
            return self.device_info

    async def get_current_profile(self) -> Dict[str, Any]:
        """Get current power profile"""
        decky.logger.info(f"GET_CURRENT_PROFILE: Returning current_profile: {self.current_profile}")
        decky.logger.info(f"GET_CURRENT_PROFILE: Type: {type(self.current_profile)}")
        decky.logger.info(f"GET_CURRENT_PROFILE: Keys: {list(self.current_profile.keys()) if isinstance(self.current_profile, dict) else 'Not a dict'}")
        
        # Ensure we have all required fields for frontend PowerProfile interface
        required_fields = ['tdp', 'cpuCores', 'cpuBoost', 'smt', 'governor', 'epp']
        result = dict(self.current_profile)  # Copy to avoid modifying original
        
        for field in required_fields:
            if field not in result:
                decky.logger.warning(f"GET_CURRENT_PROFILE: Missing field {field}, adding default")
                if field == 'tdp':
                    result[field] = 15
                elif field == 'cpuCores':
                    result[field] = 8
                elif field == 'cpuBoost':
                    result[field] = False
                elif field == 'smt':
                    result[field] = True
                elif field == 'governor':
                    result[field] = 'powersave'
                elif field == 'epp':
                    result[field] = 'balance_power'
        
        decky.logger.info(f"GET_CURRENT_PROFILE: Final result: {result}")
        return result

    async def save_profile(self, profile_data: Dict[str, Any]) -> bool:
        """Save a power profile to individual JSON file per profile ID"""
        try:
            import traceback
            import sys
            import os
            import json
            
            game_id = profile_data.get("gameId", "default")
            profile_copy = dict(profile_data)
            if "gameId" in profile_copy:
                del profile_copy["gameId"]
            
            # CRITICAL DEBUGGING: Full call context
            debug_log(f"SAVE_PROFILE called for profile ID: {game_id}")
            debug_log(f"Profile TDP: {profile_copy.get('tdp', 'UNKNOWN')}")
            debug_log(f"Full profile: {profile_copy}")
            
            # Create profiles directory structure
            profiles_dir = os.path.expanduser("~/.config/powerdeck/profiles")
            os.makedirs(profiles_dir, exist_ok=True)
            debug_log(f"Created profiles directory: {profiles_dir}")
            
            # Generate profile filename: profile_id.json
            profile_filename = f"{game_id}.json"
            profile_filepath = os.path.join(profiles_dir, profile_filename)
            
            # Save profile as individual JSON file
            with open(profile_filepath, 'w') as f:
                json.dump(profile_copy, f, indent=2)
            
            debug_log(f"Saving profile {game_id} to {profile_filepath}")
            debug_log(f"Profile file created: {profile_filepath}")
            debug_log(f"Profile data saved: {profile_copy}")
            
            # Also save to settings for backward compatibility
            if self.settings:
                self.settings.set(f"profile_{game_id}", profile_copy)
                debug_log("Profile also saved to settings for compatibility")
            
            # Update current profile if it's the active one
            self.current_profile.update(profile_copy)
            
            debug_log(f"SAVE_PROFILE completed for {game_id}")
            return True
        except Exception as e:
            error_log(f"Failed to save profile: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def load_profile(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Load a power profile from individual JSON file per profile ID"""
        try:
            import os
            import json
            
            decky.logger.info(f"PowerDeck Backend: Loading profile for {game_id}")
            
            # Try to load from individual JSON file first (unified schema)
            profiles_dir = os.path.expanduser("~/.config/powerdeck/profiles")
            profile_filename = f"{game_id}.json"
            profile_filepath = os.path.join(profiles_dir, profile_filename)
            
            decky.logger.info(f"PowerDeck Backend: Looking for profile file: {profile_filepath}")
            
            if os.path.exists(profile_filepath):
                with open(profile_filepath, 'r') as f:
                    profile_dict = json.load(f)
                decky.logger.info(f"PowerDeck Backend: Loading profile {game_id} from {profile_filepath}")
                decky.logger.info(f"PowerDeck Backend: Profile data loaded: {profile_dict}")
                self.current_profile.update(profile_dict)
                return profile_dict
            else:
                decky.logger.info(f"PowerDeck Backend: No profile file found at {profile_filepath}")
            
            # Fallback to settings for backward compatibility
            if self.settings:
                profile_dict = self.settings.get(f"profile_{game_id}")
                if profile_dict:
                    decky.logger.info(f"PowerDeck Backend: Loading profile {game_id} from settings (fallback)")
                    self.current_profile.update(profile_dict)
                    
                    # Save to new format for future use
                    try:
                        os.makedirs(profiles_dir, exist_ok=True)
                        with open(profile_filepath, 'w') as f:
                            json.dump(profile_dict, f, indent=2)
                        decky.logger.info(f"PowerDeck Backend: Migrated profile {game_id} to unified schema: {profile_filepath}")
                    except Exception as e:
                        decky.logger.warning(f"Failed to migrate profile to new format: {e}")
                    
                    return profile_dict
                else:
                    decky.logger.info(f"PowerDeck Backend: No profile found in settings for {game_id}")
            
            # No profile found anywhere
            decky.logger.info(f"PowerDeck Backend: No profile found for {game_id}, returning current profile")
            return self.current_profile
            
        except Exception as e:
            decky.logger.error(f"PowerDeck Backend: Failed to load profile for {game_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def set_tdp(self, tdp: int, save_to_profile: bool = False) -> bool:
        """Set TDP limit using device-specific controller when available"""
        try:
            # Validate TDP range
            min_tdp = self.tdp_limits["min"]
            max_tdp = self.tdp_limits["max"]
            
            if tdp < min_tdp:
                tdp = min_tdp
            elif tdp > max_tdp:
                tdp = max_tdp
            
            success = False
            
            # Use device-specific controller if available
            if self.device_controller:
                if self.device_type == "rog_ally":
                    # Check if ROG Ally native TDP support is enabled
                    if self.rog_ally_native_tdp_enabled:
                        # Use ROG Ally native TDP control
                        success = self.device_controller.set_power_limits(tdp, tdp, tdp)
                        if success:
                            decky.logger.info(f"TDP set to {tdp}W via ROG Ally native controller")
                        else:
                            decky.logger.warning(f"ROG Ally native TDP control failed, falling back to PowerDeck TDP")
                    else:
                        # Use PowerDeck TDP control (skip device controller)
                        decky.logger.info(f"Using PowerDeck TDP control (ROG Ally native disabled)")
                        success = False  # Force fallback to generic PowerDeck TDP
                elif self.device_type == "legion":
                    # Legion WMI control
                    success = self.device_controller.set_power_limits_wmi(tdp, tdp, tdp)
                    if success:
                        decky.logger.info(f"TDP set to {tdp}W via {self.device_type} controller")
                    else:
                        decky.logger.warning(f"{self.device_type} TDP control failed, falling back to generic")
                elif self.device_type == "steam_deck":
                    # Steam Deck specific control
                    success = await self.device_controller.set_tdp(tdp)
                    if success:
                        decky.logger.info(f"TDP set to {tdp}W via {self.device_type} controller")
                    else:
                        decky.logger.warning(f"{self.device_type} TDP control failed, falling back to generic")
            
            # Fallback to generic control if device-specific failed or unavailable
            if not success:
                if self.device_info["cpu_vendor"] == "Intel":
                    success = await self.set_intel_tdp(tdp)
                else:
                    success = await self.set_amd_tdp(tdp)
            
            if success:
                # Always update current_profile for hardware state tracking
                self.current_profile["tdp"] = tdp
                
                if save_to_profile:
                    # Also save the profile to persistent storage when requested
                    try:
                        await self.save_profile(self.current_game.game_id, self.current_profile)
                        decky.logger.info(f"SET_TDP: Hardware TDP set to {tdp}W and SAVED to profile")
                    except Exception as e:
                        decky.logger.error(f"Failed to save profile after TDP change: {e}")
                        decky.logger.info(f"SET_TDP: Hardware TDP set to {tdp}W but FAILED to save profile")
                else:
                    decky.logger.info(f"SET_TDP: Hardware TDP set to {tdp}W (state tracked, no profile save)")
                return True
            else:
                decky.logger.error(f"Failed to set TDP to {tdp}W")
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set TDP to {tdp}W: {e}")
            return False

    async def set_intel_tdp(self, tdp: int) -> bool:
        """Set Intel TDP using RAPL"""
        try:
            tdp_microwatts = tdp * 1000000
            tdp_paths = [
                "/sys/devices/virtual/powercap/intel-rapl-mmio/intel-rapl-mmio:0/constraint_*_power_limit_uw",
                "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/constraint_*_power_limit_uw"
            ]
            
            for path_pattern in tdp_paths:
                import glob
                paths = glob.glob(path_pattern)
                if paths:
                    for path in paths:
                        try:
                            result = subprocess.run(
                                ["sudo", "tee", path],
                                input=str(tdp_microwatts),
                                text=True,
                                capture_output=True,
                                timeout=5
                            )
                            if result.returncode == 0:
                                return True
                        except Exception as e:
                            decky.logger.error(f"Failed to write to {path}: {e}")
                            continue
            return False
        except Exception as e:
            decky.logger.error(f"Intel TDP set failed: {e}")
            return False

    async def set_amd_tdp(self, tdp: int) -> bool:
        """Set AMD TDP using ryzenadj"""
        try:
            if not self.ryzenadj_path:
                decky.logger.error("ryzenadj not available")
                return False
            
            tdp_milliwatts = tdp * 1000
            
            cmd = [
                self.ryzenadj_path,
                '--stapm-limit', str(tdp_milliwatts),
                '--fast-limit', str(tdp_milliwatts),
                '--slow-limit', str(tdp_milliwatts),
                '--tctl-temp', '95',
                '--apu-skin-temp', '95'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                decky.logger.info(f"AMD TDP set successfully via ryzenadj")
                return True
            else:
                decky.logger.error(f"ryzenadj failed: {result.stderr}")
                return False
                
        except Exception as e:
            decky.logger.error(f"AMD TDP set failed: {e}")
            return False

    async def set_cpu_boost(self, enabled: bool) -> bool:
        """Set CPU boost enable/disable using CPU manager"""
        try:
            # Use CPU manager for boost control to avoid conflicts
            if hasattr(self, 'cpu_manager') and self.cpu_manager:
                success = self.cpu_manager.set_cpu_boost(enabled)
            else:
                # Fallback if CPU manager not available
                from cpu_manager import get_cpu_manager
                cpu_manager = get_cpu_manager()
                success = cpu_manager.set_cpu_boost(enabled)
            
            if success:
                # Only update current_profile for hardware state tracking
                # DO NOT save settings here as it overwrites user customizations
                self.current_profile["cpuBoost"] = enabled
                decky.logger.info(f"SET_CPU_BOOST: Hardware CPU boost {'enabled' if enabled else 'disabled'} (no settings save to preserve user profile)")
                return True
            else:
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set CPU boost: {e}")
            return False

    async def detect_max_cpu_cores(self) -> int:
        """Detect the maximum number of CPU cores supported by hardware"""
        try:
            # First try to read from sysfs - this shows ALL possible CPUs, not just online ones
            with open('/sys/devices/system/cpu/possible', 'r') as f:
                possible_range = f.read().strip()
                
            # Parse ranges like "0-15" (16 cores) or "0-7,9-15" 
            max_cpu = 0
            for part in possible_range.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    max_cpu = max(max_cpu, end)
                else:
                    max_cpu = max(max_cpu, int(part))
            
            # CPU IDs are 0-based, so max_cpu=15 means 16 cores
            total_cores = max_cpu + 1
            decky.logger.info(f"Detected {total_cores} total CPU cores from sysfs")
            return total_cores
            
        except Exception as e:
            decky.logger.warning(f"Failed to read CPU possible from sysfs: {e}")
            
        # Fallback to psutil - but this may underreport if cores are offline
        try:
            logical_cores = psutil.cpu_count(logical=True)
            if logical_cores and logical_cores > 0:
                decky.logger.info(f"Fallback: detected {logical_cores} CPU cores from psutil")
                return logical_cores
        except Exception as e:
            decky.logger.warning(f"psutil CPU detection also failed: {e}")
            
        # Final fallback - common values for gaming handhelds
        decky.logger.warning("Using fallback CPU core count")
        return 8

    async def get_online_cpus(self):
        """Get list of online CPU numbers"""
        try:
            with open('/sys/devices/system/cpu/online', 'r') as f:
                online_range = f.read().strip()
                # Parse ranges like "0-15" or "0-7,9-15"
                cpus = []
                for part in online_range.split(','):
                    if '-' in part:
                        start, end = map(int, part.split('-'))
                        cpus.extend(range(start, end + 1))
                    else:
                        cpus.append(int(part))
                return cpus
        except:
            return [0]  # Fallback to CPU 0

    async def set_smt(self, enabled: bool) -> bool:
        """Set SMT (Simultaneous Multithreading) enable/disable"""
        try:
            smt_path = "/sys/devices/system/cpu/smt/control"
            if os.path.exists(smt_path):
                try:
                    # Get current core count before SMT change
                    current_cores = self.current_profile.get("cpuCores", 4)
                    current_boost = self.current_profile.get("cpuBoost", True)
                    current_governor = self.current_profile.get("governor", "powersave")
                    current_epp = self.current_profile.get("epp", "balance_performance")
                    
                    with open(smt_path, 'w') as f:
                        f.write('on' if enabled else 'off')
                    # Only update current_profile for hardware state tracking
                    # DO NOT save settings here as it overwrites user customizations
                    self.current_profile["smt"] = enabled
                    decky.logger.info(f"SET_SMT: Hardware SMT {'enabled' if enabled else 'disabled'} (no settings save to preserve user profile)")
                    
                    # After SMT change, reinitialize CPU topology to update sibling mappings
                    if hasattr(self, 'cpu_manager') and self.cpu_manager:
                        info_log("Reinitializing CPU topology after SMT change...")
                        self.cpu_manager._topology_initialized = False
                        self.cpu_manager.initialize_cpu_topology()
                        
                        # Reconfigure CPU cores to maintain the same physical core count
                        info_log(f"Reconfiguring CPU cores to {current_cores} after SMT change...")
                        await self.set_cpu_cores(current_cores)
                        
                        # Reapply CPU settings to new topology
                        info_log("Reapplying CPU settings after SMT topology change...")
                        self.cpu_manager.reapply_cpu_settings(current_boost, current_governor, current_epp)
                    
                    return True
                except Exception as e:
                    decky.logger.error(f"SMT control failed: {e}")
                    return False
            else:
                decky.logger.error("SMT control not available")
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set SMT: {e}")
            return False

    async def set_cpu_cores(self, cores: int) -> bool:
        """Set number of active CPU cores with C-state optimization for better power efficiency"""
        try:
            decky.logger.info(f"Request to set CPU cores to: {cores} (with C-state optimization)")
            
            # Get current SMT status and calculate core counts from hardware maximum
            smt_enabled = await self.get_current_smt_status()
            max_possible_cores = await self.detect_max_cpu_cores()
            
            # Calculate physical/logical cores based on hardware maximum, not current online
            if smt_enabled:
                physical_cores = max_possible_cores // 2  # SMT means 2 threads per physical core
                logical_cores = max_possible_cores
            else:
                physical_cores = max_possible_cores
                logical_cores = max_possible_cores
            
            decky.logger.info(f"Hardware info - Max possible: {max_possible_cores}, Physical: {physical_cores}, Logical: {logical_cores}, SMT: {smt_enabled}")
            
            # Validate core count is reasonable
            if cores < 1:
                decky.logger.warning(f"Core count {cores} too low, setting to 1")
                cores = 1
            
            if cores > max_possible_cores:
                decky.logger.warning(f"Core count {cores} exceeds maximum {max_possible_cores}")
                cores = max_possible_cores
            
            # If user wants more cores than physical, enable SMT
            if cores > physical_cores and not smt_enabled:
                decky.logger.info("Enabling SMT for requested core count")
                await self.set_smt(True)
                smt_enabled = True
                # Recalculate with SMT enabled
                logical_cores = max_possible_cores
            
            # SMT disabled means we can only use up to physical cores
            if not smt_enabled and cores > physical_cores:
                decky.logger.info(f"SMT disabled, limiting {cores} cores to {physical_cores} physical cores")
                cores = physical_cores

            target_cores = cores
            decky.logger.info(f"Setting target cores to: {target_cores}")
            
            # Get current boost setting before attempting core changes
            # This ensures it's available for both success and fallback paths
            current_boost = self.current_profile.get("cpuBoost", True)
            
            # Use enhanced CPU manager with C-state optimization
            from cpu_manager import get_cpu_manager
            cpu_manager = get_cpu_manager()
            
            success = cpu_manager.set_cpu_cores_with_cstate_optimization(target_cores)
            
            if success:
                # CPU manager handles boost reapplication internally via reapply_cpu_settings()
                # No need for redundant boost reapplication here
                
                # Only update current_profile for hardware state tracking
                # DO NOT save settings here as it overwrites user customizations
                self.current_profile["cpuCores"] = cores
                decky.logger.info(f"SET_CPU_CORES: Hardware CPU cores set to {cores} with C-state optimization (no settings save to preserve user profile)")
                return True
            else:
                decky.logger.error("Failed to set CPU cores with C-state optimization, falling back to legacy method")
                
                # Fallback to legacy method if enhanced method fails
                return await self._legacy_set_cpu_cores(target_cores, max_possible_cores, current_boost)
                
        except Exception as e:
            decky.logger.error(f"Failed to set CPU cores: {e}")
            return False

    async def _legacy_set_cpu_cores(self, target_cores: int, max_possible_cores: int, current_boost: bool) -> bool:
        """Legacy CPU core management without C-state optimization (fallback)"""
        try:
            decky.logger.info(f"Using legacy CPU core management for {target_cores} cores")
            
            success = True
            
            # First, ensure all needed cores are online (CPU 0 to target_cores-1)
            for i in range(target_cores):
                cpu_path = f"/sys/devices/system/cpu/cpu{i}/online"
                if os.path.exists(cpu_path) and i != 0:  # Never touch CPU 0
                    try:
                        with open(cpu_path, 'w') as f:
                            f.write("1")
                        decky.logger.info(f"Enabled CPU {i}")
                    except Exception as e:
                        decky.logger.error(f"Failed to enable CPU {i}: {e}")
                        success = False
            
            # Then disable cores beyond the target (from target_cores to max_possible_cores-1)
            for i in range(target_cores, max_possible_cores):
                cpu_path = f"/sys/devices/system/cpu/cpu{i}/online"
                if os.path.exists(cpu_path) and i != 0:  # Never disable CPU 0
                    try:
                        with open(cpu_path, 'w') as f:
                            f.write("0")
                        decky.logger.info(f"Disabled CPU {i}")
                    except Exception as e:
                        decky.logger.error(f"Failed to disable CPU {i}: {e}")
                        success = False
            
            if success:
                # Legacy CPU core setting completed - boost settings handled by CPU manager
                
                # Only update current_profile for hardware state tracking
                self.current_profile["cpuCores"] = target_cores
                decky.logger.info(f"SET_CPU_CORES: Hardware CPU cores set to {target_cores} (legacy method)")
                return True
            else:
                decky.logger.error("Failed to set some CPU cores using legacy method")
                return False
                
        except Exception as e:
            decky.logger.error(f"Legacy CPU core management failed: {e}")
            return False

    async def get_current_smt_status(self) -> bool:
        """Get current SMT status"""
        try:
            smt_path = "/sys/devices/system/cpu/smt/control"
            if os.path.exists(smt_path):
                with open(smt_path, 'r') as f:
                    status = f.read().strip()
                    return status == "on"
            return True  # Assume SMT is on if we can't detect
        except Exception as e:
            decky.logger.error(f"Failed to get SMT status: {e}")
            return True

    async def set_gpu_mode(self, mode: str) -> bool:
        """Set GPU power mode - supports both AMD and Intel GPUs"""
        try:
            # Check if Intel GPU is available via sysfs power manager
            intel_gpu_capabilities = sysfs_power_manager.get_capabilities()
            if intel_gpu_capabilities.supports_intel_gpu:
                return await self._set_intel_gpu_mode(mode)
            else:
                return await self._set_amd_gpu_mode(mode)
                
        except Exception as e:
            decky.logger.error(f"Failed to set GPU mode: {e}")
            return False
    
    async def _set_intel_gpu_mode(self, mode: str) -> bool:
        """Set Intel GPU power mode using frequency control"""
        try:
            # Map our modes to Intel GPU frequency ranges
            # Get hardware capabilities
            min_hw, max_hw = sysfs_power_manager.get_intel_gpu_frequency_range()
            if min_hw == 0 and max_hw == 0:
                # Fallback to detected capabilities
                caps = sysfs_power_manager.get_capabilities()
                min_hw = caps.gpu_min_freq_mhz or 300
                max_hw = caps.gpu_max_freq_mhz or 1100
            
            # Define frequency ranges for different modes
            if mode == "battery":
                # Low performance mode - use minimum frequencies
                min_freq = min_hw
                max_freq = min_hw + ((max_hw - min_hw) // 3)  # ~33% of range
            elif mode == "balanced":
                # Balanced mode - use mid-range frequencies
                min_freq = min_hw
                max_freq = min_hw + ((max_hw - min_hw) * 2 // 3)  # ~67% of range
            elif mode == "performance":
                # High performance mode - use full range
                min_freq = min_hw
                max_freq = max_hw
            elif mode == "range" or mode == "manual":
                # Manual mode - use current profile frequencies or defaults
                profile_min = self.current_profile.get("gpuMinFreq", min_hw)
                profile_max = self.current_profile.get("gpuMaxFreq", max_hw)
                min_freq = max(profile_min, min_hw)
                max_freq = min(profile_max, max_hw)
            else:
                # Default to balanced
                min_freq = min_hw
                max_freq = min_hw + ((max_hw - min_hw) * 2 // 3)
            
            # Apply the frequency settings
            success = sysfs_power_manager.set_intel_gpu_frequency_range(min_freq, max_freq)
            
            if success:
                self.current_profile["gpuMode"] = mode
                decky.logger.info(f"SET_GPU_MODE: Intel GPU mode set to {mode} ({min_freq}-{max_freq} MHz)")
                return True
            else:
                decky.logger.error(f"Failed to apply Intel GPU frequency range: {min_freq}-{max_freq} MHz")
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set Intel GPU mode: {e}")
            return False
    
    async def _set_amd_gpu_mode(self, mode: str) -> bool:
        """Set AMD GPU power mode using DPM"""
        try:
            gpu_path = "/sys/class/drm/card0/device/power_dpm_force_performance_level"
            
            if not os.path.exists(gpu_path):
                # Try card1
                gpu_path = "/sys/class/drm/card1/device/power_dpm_force_performance_level"
                
            if not os.path.exists(gpu_path):
                decky.logger.error("AMD GPU power management not available")
                return False
            
            # Map our modes to AMD DPM modes
            mode_mapping = {
                "battery": "low",
                "balanced": "auto", 
                "performance": "high",
                "range": "manual",
                "manual": "manual"
            }
            
            dpm_mode = mode_mapping.get(mode, "auto")
            
            try:
                with open(gpu_path, 'w') as f:
                    f.write(dpm_mode)
                # Only update current_profile for hardware state tracking
                # DO NOT save settings here as it overwrites user customizations
                self.current_profile["gpuMode"] = mode
                decky.logger.info(f"SET_GPU_MODE: AMD GPU mode set to {mode} (DPM: {dpm_mode})")
                return True
            except Exception as e:
                decky.logger.error(f"AMD GPU mode set failed: {e}")
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set AMD GPU mode: {e}")
            return False

    async def set_gpu_frequency(self, min_freq: int, max_freq: int) -> bool:
        """Set GPU frequency range - supports both AMD and Intel GPUs"""
        try:
            # Check if Intel GPU is available via sysfs power manager
            intel_gpu_capabilities = sysfs_power_manager.get_capabilities()
            if intel_gpu_capabilities.supports_intel_gpu:
                # Intel GPU frequency control via sysfs
                success = sysfs_power_manager.set_intel_gpu_frequency_range(min_freq, max_freq)
                if success:
                    self.current_profile["gpuMinFreq"] = min_freq
                    self.current_profile["gpuMaxFreq"] = max_freq
                    decky.logger.info(f"SET_GPU_FREQUENCY: Intel GPU frequency range set to {min_freq}-{max_freq}MHz")
                    return True
                else:
                    decky.logger.error(f"Failed to set Intel GPU frequency range: {min_freq}-{max_freq}MHz")
                    return False
            else:
                # AMD GPU frequency control
                # First set to manual mode
                await self.set_gpu_mode("range")
                
                # Read available DPM levels to constrain frequencies
                dmp_path = "/sys/class/drm/card0/device/pp_dpm_sclk"
                if not os.path.exists(dmp_path):
                    dmp_path = "/sys/class/drm/card1/device/pp_dpm_sclk"
                
                available_freqs = []
                try:
                    with open(dmp_path, 'r') as f:
                        for line in f:
                            if ':' in line and 'Mhz' in line:
                                freq_str = line.split(':')[1].strip().replace('Mhz', '').split()[0]
                                available_freqs.append(int(freq_str))
                    decky.logger.info(f"AMD GPU available frequencies: {available_freqs}")
                except Exception as e:
                    decky.logger.warning(f"Could not read DPM levels: {e}")
                    # Fallback to detected limits
                    available_freqs = [self.device_info.get("min_gpu_freq", 800), self.device_info.get("max_gpu_freq", 2700)]
                
                # Map requested frequencies to available levels
                if available_freqs:
                    # Find closest available frequencies
                    closest_min = min(available_freqs, key=lambda x: abs(x - min_freq))
                    closest_max = max(freq for freq in available_freqs if freq >= closest_min)
                    
                    # Ensure min <= max
                    if closest_min > closest_max:
                        closest_min = min(available_freqs)
                        closest_max = max(available_freqs)
                    
                    decky.logger.info(f"AMD GPU mapping {min_freq}-{max_freq}MHz to {closest_min}-{closest_max}MHz")
                    min_freq = closest_min
                    max_freq = closest_max
                
                # Set frequency limits via pp_od_clk_voltage
                od_path = "/sys/class/drm/card0/device/pp_od_clk_voltage"
                if not os.path.exists(od_path):
                    od_path = "/sys/class/drm/card1/device/pp_od_clk_voltage"
                    
                if not os.path.exists(od_path):
                    decky.logger.error("AMD GPU frequency control not available")
                    return False
                
                try:
                    # Reset to default first
                    with open(od_path, 'w') as f:
                        f.write("r")
                    
                    # Set new limits using available frequencies
                    with open(od_path, 'w') as f:
                        f.write(f"s 0 {min_freq}")
                    with open(od_path, 'w') as f:
                        f.write(f"s 1 {max_freq}")
                    
                    # Commit changes
                    with open(od_path, 'w') as f:
                        f.write("c")
                    
                    # Only update current_profile for hardware state tracking
                    # DO NOT save settings here as it overwrites user customizations
                    self.current_profile["gpuMinFreq"] = min_freq
                    self.current_profile["gpuMaxFreq"] = max_freq
                    decky.logger.info(f"SET_GPU_FREQUENCY: AMD GPU frequency range set to {min_freq}-{max_freq}MHz")
                    return True
                    
                except Exception as e:
                    decky.logger.error(f"AMD GPU frequency set failed: {e}")
                    return False
                    
        except Exception as e:
            decky.logger.error(f"Failed to set GPU frequency range: {e}")
            return False

    async def set_fixed_gpu_frequency(self, freq: int) -> bool:
        """Set fixed GPU frequency"""
        try:
            # Set both min and max to the same frequency
            return await self.set_gpu_frequency(freq, freq)
        except Exception as e:
            decky.logger.error(f"Failed to set fixed GPU frequency: {e}")
            return False

    async def set_power_governor(self, governor: str) -> bool:
        """Set CPU power governor with fallback for unavailable governors"""
        try:
            # Get available governors
            available_governors_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"
            if os.path.exists(available_governors_path):
                with open(available_governors_path, 'r') as f:
                    available_governors = f.read().strip().split()
            else:
                available_governors = ["performance", "powersave"]  # Safe fallback
            
            # Map requested governor to available governor if needed
            governor_mapping = {
                "balanced": "powersave",       # AMD systems often don't have balanced
                "ondemand": "powersave",       # Fallback if ondemand not available
                "conservative": "powersave",   # Fallback if conservative not available
                "schedutil": "powersave"       # Fallback if schedutil not available
            }
            
            target_governor = governor
            if governor not in available_governors:
                if governor in governor_mapping:
                    target_governor = governor_mapping[governor]
                    decky.logger.info(f"Governor '{governor}' not available, using fallback: '{target_governor}'")
                else:
                    target_governor = "powersave"  # Safe default
                    decky.logger.warning(f"Governor '{governor}' not available, defaulting to: '{target_governor}'")
            
            online_cpus = await self.get_online_cpus()
            success = True
            
            for cpu in online_cpus:
                gov_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
                if os.path.exists(gov_path):
                    try:
                        with open(gov_path, 'w') as f:
                            f.write(target_governor)
                    except Exception as e:
                        decky.logger.error(f"Failed to set governor for CPU {cpu}: {e}")
                        success = False
            
            if success:
                # Only update current_profile for hardware state tracking
                # DO NOT save settings here as it overwrites user customizations
                self.current_profile["governor"] = target_governor
                decky.logger.info(f"SET_POWER_GOVERNOR: Hardware power governor set to {target_governor} (no settings save to preserve user profile)")
                return True
            else:
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set power governor: {e}")
            return False

    async def set_epp(self, epp: str) -> bool:
        """Set Energy Performance Preference - with validation for available options"""
        try:
            # First check if the requested EPP is available
            available_epp = await self.get_available_epp_options()
            if epp not in available_epp:
                decky.logger.warning(f"Requested EPP '{epp}' not available. Available options: {available_epp}")
                # Try to find a close alternative
                if epp in ["balance_power", "power"] and "performance" in available_epp:
                    decky.logger.info(f"Using 'performance' as fallback for requested '{epp}' on amd-pstate-epp system")
                    epp = "performance"
                else:
                    decky.logger.error(f"No suitable EPP alternative found for '{epp}'")
                    return False

            online_cpus = await self.get_online_cpus()
            success = True
            
            for cpu in online_cpus:
                epp_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/energy_performance_preference"
                if os.path.exists(epp_path):
                    try:
                        with open(epp_path, 'w') as f:
                            f.write(epp)
                    except Exception as e:
                        decky.logger.error(f"Failed to set EPP for CPU {cpu}: {e}")
                        success = False
            
            if success:
                # Only update current_profile for hardware state tracking
                # DO NOT save settings here as it overwrites user customizations
                self.current_profile["epp"] = epp
                decky.logger.info(f"SET_EPP: Hardware EPP set to {epp} (validated and applied)")
                return True
            else:
                decky.logger.error(f"Failed to apply EPP: {epp}")
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to set EPP: {e}")
            return False

    async def get_tdp_limits(self) -> Dict[str, int]:
        """Get current TDP limits"""
        return self.tdp_limits

    async def set_tdp_limits(self, min_tdp: int, max_tdp: int) -> bool:
        """Set custom TDP limits"""
        try:
            self.tdp_limits = {"min": min_tdp, "max": max_tdp}
            self.device_info["min_tdp"] = min_tdp
            self.device_info["max_tdp"] = max_tdp
            # TDP limits are part of device configuration, so save is appropriate here
            await self.save_settings()
            decky.logger.info(f"TDP limits set to {min_tdp}-{max_tdp}W")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to set TDP limits: {e}")
            return False

    async def get_current_game_info(self) -> Dict[str, str]:
        """Get current game information with proper Steam/game detection - Enhanced from working commit 8bc1228"""
        debug_log("GET_CURRENT_GAME_INFO called")
        try:
            # Import Steam utilities for proper game detection
            import subprocess
            import re
            
            # Try to detect running Steam games first
            try:
                # Method 1: Check for Steam processes with game names
                ps_output = subprocess.check_output(['ps', 'aux'], text=True)
                
                # Look for Steam game processes with game paths
                # Pattern 1: Look for reaper process with AppId and find the actual game path
                if 'reaper SteamLaunch AppId=' in ps_output:
                    # Extract the AppId first
                    app_id_match = re.search(r'reaper SteamLaunch AppId=(\d+)', ps_output)
                    if app_id_match:
                        app_id = app_id_match.group(1)
                        
                        # Look for the actual game executable path (ends with .exe)
                        game_path_pattern = r'steamapps/common/([^/]+(?:\s+[^/]*)*)/[^/]*\.exe'
                        game_path_matches = re.findall(game_path_pattern, ps_output)
                        
                        for game_folder in game_path_matches:
                            # Skip runtime and proton folders
                            if not any(skip in game_folder.lower() for skip in ['runtime', 'proton', 'sniper']):
                                decky.logger.info(f"Found Steam game via path: AppId={app_id}, Folder={game_folder}")
                                return {"id": f"steam_{app_id}", "name": game_folder}
                        
                        # If no good path found, use AppId only
                        decky.logger.info(f"Found Steam game via AppId only: {app_id}")
                        return {"id": f"steam_{app_id}", "name": f"Steam Game {app_id}"}
                
                # Pattern 2: Look for game executable in Steam directories 
                game_exe_pattern = r'(steamapps/common/([^/]+)(?:/[^/]*)?\.exe)'
                exe_matches = re.findall(game_exe_pattern, ps_output)
                
                if exe_matches:
                    full_path, game_folder = exe_matches[0]
                    decky.logger.info(f"Found Steam game via executable: {game_folder}")
                    
                    # Use the full game name
                    game_name = game_folder if game_folder else "Unknown Game"
                    
                    if game_name:
                        return {"id": f"game_{game_name.lower().replace(' ', '_')}", "name": game_name}
                
                # Pattern 3: Original AppId detection as fallback
                steam_game_pattern = r'steam.*app.*?(\d+)'
                game_matches = re.findall(steam_game_pattern, ps_output, re.IGNORECASE)
                
                if game_matches:
                    app_id = game_matches[0]
                    decky.logger.info(f"Detected Steam game with App ID: {app_id}")
                    return {"id": f"steam_{app_id}", "name": f"Steam Game {app_id}"}
                
                # ENHANCED PATTERN 4: Look for more Steam patterns from working commit
                # Check for Steam runtime processes with better filtering
                steam_runtime_pattern = r'steam-runtime-launch-service.*--pass-fd.*steamapps'
                if re.search(steam_runtime_pattern, ps_output):
                    # Try to extract game name from command line
                    runtime_matches = re.findall(r'steamapps/common/([^/\s]+)', ps_output)
                    if runtime_matches:
                        game_name = runtime_matches[0]
                        decky.logger.info(f"Found Steam game via runtime: {game_name}")
                        return {"id": f"game_{game_name.lower().replace(' ', '_')}", "name": game_name}
                
                # ENHANCED PATTERN 5: Check for Proton processes with game identification
                proton_pattern = r'proton.*run.*steamapps/common/([^/\s]+)'
                proton_matches = re.findall(proton_pattern, ps_output, re.IGNORECASE)
                if proton_matches:
                    game_name = proton_matches[0]
                    # Clean up game name
                    game_name = game_name.replace('_', ' ').title()
                    decky.logger.info(f"Found Steam game via Proton: {game_name}")
                    return {"id": f"proton_game_{game_name.lower().replace(' ', '_')}", "name": game_name}
                    
            except Exception as e:
                decky.logger.warning(f"Steam game detection failed: {e}")
            
            # Method 2: Check for other gaming processes (Enhanced from working commit)
            try:
                # Look for common game executables with better detection
                ps_output = subprocess.check_output(['ps', 'aux'], text=True)
                
                # Enhanced gaming process detection
                gaming_patterns = [
                    (r'retroarch', 'RetroArch'),
                    (r'emulationstation', 'EmulationStation'),  
                    (r'yuzu', 'Yuzu'),
                    (r'dolphin-emu', 'Dolphin'),
                    (r'pcsx2', 'PCSX2'),
                    (r'ppsspp', 'PPSSPP'),
                    (r'duckstation', 'DuckStation'),
                    (r'melonds', 'melonDS'),
                    (r'citra', 'Citra'),
                    (r'rpcs3', 'RPCS3'),
                    (r'wine.*\.exe', 'Windows Game'),
                    (r'lutris', 'Lutris Game'),
                    (r'heroic', 'Heroic Game'),
                    (r'bottles', 'Bottles Game')
                ]
                
                for pattern, display_name in gaming_patterns:
                    if re.search(pattern, ps_output, re.IGNORECASE):
                        decky.logger.info(f"Detected gaming process: {display_name}")
                        return {"id": f"game_{display_name.lower().replace(' ', '_')}", "name": display_name}
                        
            except Exception as e:
                decky.logger.warning(f"Gaming process detection failed: {e}")
            
            # Method 3: Enhanced device classification from working commit
            sys.path.insert(0, os.path.dirname(__file__))
            decky.logger.info("Game detection: Starting enhanced device type detection")
            
            try:
                from processor_detection import is_handheld_device
                import glob
                import psutil
                
                # Use enhanced device classification logic
                is_handheld = is_handheld_device()
                decky.logger.info(f"Enhanced game detection: is_handheld_device() returned: {is_handheld}")
                
                if is_handheld:
                    decky.logger.info("Handheld gaming device detected - using Handheld profile")
                    return {"id": "handheld", "name": "Handheld"}
                else:
                    # Enhanced device type detection for non-handhelds
                    battery = psutil.sensors_battery()
                    has_battery = battery is not None
                    decky.logger.info(f"Enhanced detection: Battery status - has_battery: {has_battery}")
                    
                    if has_battery:
                        decky.logger.info("Laptop device detected (has battery, not handheld) - using Laptop profile")
                        return {"id": "laptop", "name": "Laptop"}
                    else:
                        decky.logger.info("Desktop device detected (no battery) - using Desktop profile") 
                        return {"id": "desktop", "name": "Desktop"}
                        
            except Exception as detection_error:
                # Enhanced fallback logic based on device patterns
                decky.logger.error(f"Enhanced game detection: Device type detection failed: {detection_error}")
                
                # Try DMI-based detection as ultimate fallback
                try:
                    with open("/sys/class/dmi/id/product_name", "r") as f:
                        product_name = f.read().strip().lower()
                        decky.logger.info(f"DMI fallback detection: product_name = {product_name}")
                        
                        # Check for known handheld patterns
                        if any(pattern in product_name for pattern in ["ayaneo", "steam deck", "rog ally", "legion go", "onex", "gpd"]):
                            decky.logger.info("Handheld detected via DMI fallback")
                            return {"id": "handheld", "name": "Handheld"}
                except:
                    pass
                
                # Final fallback to handheld for unknown devices (safest for gaming handhelds)
                decky.logger.info("Using ultimate fallback: Handheld profile")
                return {"id": "handheld", "name": "Handheld"}
                
        except Exception as e:
            decky.logger.error(f"Failed to get enhanced game info: {e}")
            # Default fallback that should work on most gaming devices
            return {"id": "handheld", "name": "Handheld"}

    async def get_ac_power_status(self) -> bool:
        """Get AC power connection status using hardware-level detection"""
        try:
            decky.logger.info("FRONTEND POLLING CALL DETECTED")
            decky.logger.info("=== AC POWER STATUS CHECK ===")
            decky.logger.info("Frontend requesting AC power status (polling active)")
            
            # Import AC power manager for hardware-level detection
            sys.path.insert(0, os.path.dirname(__file__))
            from ac_power_manager import get_hardware_ac_status, supports_hardware_ac_detection, debug_power_supply_info
            
            # Debug: Log all power supply information
            debug_power_supply_info()
            
            # Try hardware-level detection first (most reliable)
            if supports_hardware_ac_detection():
                decky.logger.info("Using hardware-level AC power detection")
                hardware_status = get_hardware_ac_status()
                if hardware_status is not None:
                    decky.logger.info(f"Hardware AC power status: {hardware_status}")
                    decky.logger.info(f"RETURNING AC STATUS: {hardware_status} to frontend")
                    return hardware_status
                else:
                    decky.logger.warning("Hardware AC detection returned None")
            else:
                decky.logger.warning("Hardware AC detection not supported")
            
            # Fallback to psutil if hardware detection unavailable
            decky.logger.info("Falling back to psutil battery detection")
            battery = psutil.sensors_battery()
            if battery:
                fallback_status = battery.power_plugged
                decky.logger.info(f"Fallback AC power status: {fallback_status}")
                decky.logger.info(f"RETURNING FALLBACK AC STATUS: {fallback_status} to frontend")
                return fallback_status
            else:
                decky.logger.warning("No battery information available from psutil")
                
            decky.logger.error("All AC power detection methods failed")
            decky.logger.info(f"RETURNING DEFAULT AC STATUS: False to frontend")
            return False
        except Exception as e:
            decky.logger.error(f"Failed to get AC power status: {e}")
            return False

    async def supports_custom_ac_power_management(self) -> bool:
        """Check if the device supports custom AC power management.
        
        Returns:
            bool: True if custom AC power management is supported
        """
        decky.logger.info("Checking if device supports custom AC power management")
        # Import device manager to check capabilities
        sys.path.insert(0, os.path.dirname(__file__))
        from device_manager import DeviceManager
        
        try:
            device_manager = DeviceManager()
            device_name = device_manager.get_device_name()
            decky.logger.info(f"Device detected: {device_name}")
            
            # PowerDeck supports AC power management for supported devices
            # AYANEO 2S is explicitly supported
            if "AYANEO 2S" in device_name:
                decky.logger.info("AYANEO 2S detected - AC power management supported")
                return True
            elif "AYANEO" in device_name:
                decky.logger.info("AYANEO device detected - AC power management supported")
                return True
            else:
                decky.logger.info(f"Unknown device: {device_name} - AC power management may not be supported")
                return False
                
        except Exception as e:
            decky.logger.error(f"Error checking AC power management support: {e}")
            return False

    async def debug_frontend_state(self, frontend_ac_power: bool, backend_ac_power: bool, action: str) -> bool:
        """Log frontend state for debugging real-time AC monitoring"""
        decky.logger.info(f"FRONTEND DEBUG: {action}")
        decky.logger.info(f"  Frontend AC Power: {frontend_ac_power}")
        decky.logger.info(f"  Backend AC Power: {backend_ac_power}")
        decky.logger.info(f"  States Match: {frontend_ac_power == backend_ac_power}")
        return True

    async def supports_hardware_ac_detection(self) -> bool:
        """Check if hardware-level AC power detection is available"""
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from ac_power_manager import supports_hardware_ac_detection
            return supports_hardware_ac_detection()
        except Exception as e:
            decky.logger.error(f"Failed to check AC detection support: {e}")
            return False

    async def auto_switch_power_profile(self) -> bool:
        """Automatically switch between AC and battery profiles based on power state"""
        try:
            decky.logger.info("=== AUTO POWER PROFILE SWITCHING ===")
            
            # Get current AC power status
            is_ac_power = await self.get_ac_power_status()
            decky.logger.info(f"Current power state: {'AC' if is_ac_power else 'Battery'}")
            
            # Get TDP values using new processor database logic
            tdp_min = 4  # Hard-coded minimum for underclocking  
            tdp_max = 25  # Fallback maximum
            tdp_default = 15  # Fallback default
            max_cores = 8  # Fallback default
            
            # Get dynamic values from processor database if available
            if processor_support_available:
                try:
                    # Get TDP limits: (hard_coded_min=4W, database_max)
                    tdp_min, tdp_max = get_processor_tdp_limits()
                    # Get default TDP from database ctdp_min
                    tdp_default = get_processor_default_tdp()
                    processor_info = get_current_processor_info()
                    if processor_info and processor_info.get("detected", False):
                        max_cores = processor_info.get("max_cpu_cores", 8)
                        decky.logger.info(f"Using processor database: min={tdp_min}W (hard-coded), default={tdp_default}W (DB ctdp_min), max={tdp_max}W (DB ctdp_max), cores={max_cores}")
                except Exception as e:
                    decky.logger.warning(f"Failed to get processor database values: {e}")
            
            if is_ac_power:
                # AC Power: Balanced profile optimized for power efficiency (not max performance)
                target_profile_name = "performance"
                fallback_profile = {
                    "tdp": tdp_max,  # Use processor database max TDP (e.g., 30W for 7840U)
                    "cpuBoost": False,  # Disabled for better power efficiency (matching SimpleDeckyTDP)
                    "smt": True,
                    "cpuCores": max_cores,  # Use processor max cores
                    "governor": "powersave",  # Always use powersave for efficiency
                    "epp": "balance_power"  # Conservative EPP setting
                }
            else:
                # Battery Power: Maximum power efficiency profile (matching SimpleDeckyTDP efficiency)
                target_profile_name = "battery_saver"
                fallback_profile = {
                    "tdp": max(4, tdp_default - 3),  # More conservative TDP for battery (e.g., 12W for 7840U)
                    "cpuBoost": False,  # Always disabled on battery
                    "smt": False,  # Disable SMT for maximum efficiency (saves ~1W like SimpleDeckyTDP)
                    "cpuCores": max(2, max_cores // 2),  # Half the cores for battery efficiency
                    "governor": "powersave",  # Always use powersave for efficiency
                    "epp": "power"  # Maximum power efficiency
                }
            
            decky.logger.info(f"Target profile: {target_profile_name}")
            
            # Try to load the target profile from saved profiles
            profile_data = None
            try:
                profiles_file = os.path.join(os.path.dirname(__file__), "..", "settings", "PowerDeck", "PowerDeck", "profiles.json")
                if os.path.exists(profiles_file):
                    with open(profiles_file, 'r') as f:
                        profiles = json.load(f)
                        if target_profile_name in profiles.get("profiles", {}):
                            static_profile = profiles["profiles"][target_profile_name]
                            # Convert static profile format to PowerDeck format
                            profile_data = {
                                "tdp": static_profile.get("tdp", fallback_profile["tdp"]),
                                "cpuBoost": static_profile.get("cpu", {}).get("boost_enabled", fallback_profile["cpuBoost"]),
                                "smt": static_profile.get("cpu", {}).get("smt_enabled", fallback_profile["smt"]),
                                "cpuCores": fallback_profile["cpuCores"],  # Use fallback cores
                                "governor": static_profile.get("cpu", {}).get("governor", fallback_profile["governor"]),
                                "epp": static_profile.get("cpu", {}).get("epp", fallback_profile["epp"])
                            }
                            decky.logger.info(f"Loaded static profile {target_profile_name}: {profile_data}")
                        else:
                            decky.logger.warning(f"Static profile {target_profile_name} not found, using fallback")
                            profile_data = fallback_profile
                else:
                    decky.logger.warning(f"Profiles file not found, using fallback")
                    profile_data = fallback_profile
            except Exception as e:
                decky.logger.warning(f"Failed to load static profile {target_profile_name}: {e}")
                profile_data = fallback_profile
            
            # Apply the profile
            if profile_data:
                # Update current profile
                self.current_profile.update(profile_data)
                
                # Apply the settings to hardware
                success = await self.apply_profile(profile_data)
                if success:
                    decky.logger.info(f"Successfully applied {target_profile_name} profile for {'AC' if is_ac_power else 'Battery'} power")
                    return True
                else:
                    decky.logger.error(f"Failed to apply {target_profile_name} profile")
                    return False
            
            return False
            
        except Exception as e:
            decky.logger.error(f"Failed to auto-switch power profile: {e}")
            return False
    
    async def apply_profile(self, profile_data: Dict[str, Any]) -> bool:
        """Apply a complete power profile to hardware"""
        try:
            decky.logger.info(f"=== APPLYING POWER PROFILE ===")
            decky.logger.info(f"Profile data: {profile_data}")
            
            success_count = 0
            total_operations = 0
            
            # Apply TDP setting
            if "tdp" in profile_data:
                total_operations += 1
                try:
                    tdp_success = await self.set_tdp(profile_data["tdp"])
                    if tdp_success:
                        success_count += 1
                        decky.logger.info(f"Applied TDP: {profile_data['tdp']}W")
                    else:
                        decky.logger.warning(f"Failed to apply TDP: {profile_data['tdp']}W")
                except Exception as e:
                    decky.logger.error(f"Error applying TDP: {e}")
            
            # Apply CPU boost setting
            if "cpuBoost" in profile_data:
                total_operations += 1
                try:
                    boost_success = await self.set_cpu_boost(profile_data["cpuBoost"])
                    if boost_success:
                        success_count += 1
                        decky.logger.info(f"Applied CPU boost: {profile_data['cpuBoost']}")
                    else:
                        decky.logger.warning(f"Failed to apply CPU boost: {profile_data['cpuBoost']}")
                except Exception as e:
                    decky.logger.error(f"Error applying CPU boost: {e}")
            
            # Apply SMT setting (before CPU cores for proper management)
            if "smt" in profile_data:
                total_operations += 1
                try:
                    smt_success = await self.set_smt(profile_data["smt"])
                    if smt_success:
                        success_count += 1
                        decky.logger.info(f"Applied SMT: {profile_data['smt']}")
                    else:
                        decky.logger.warning(f"Failed to apply SMT: {profile_data['smt']}")
                except Exception as e:
                    decky.logger.error(f"Error applying SMT: {e}")
            
            # Apply CPU cores setting
            if "cpuCores" in profile_data:
                total_operations += 1
                try:
                    cores_success = await self.set_cpu_cores(profile_data["cpuCores"])
                    if cores_success:
                        success_count += 1
                        decky.logger.info(f"Applied CPU cores: {profile_data['cpuCores']}")
                    else:
                        decky.logger.warning(f"Failed to apply CPU cores: {profile_data['cpuCores']}")
                except Exception as e:
                    decky.logger.error(f"Error applying CPU cores: {e}")
            
            # Apply CPU governor and EPP settings
            if "governor" in profile_data or "powerGovernor" in profile_data or "epp" in profile_data:
                # Handle both old "powerGovernor" and new "governor" field names
                governor = profile_data.get("governor") or profile_data.get("powerGovernor", "powersave")
                epp = profile_data.get("epp", "balance_power")
                
                # Set governor if present
                if "governor" in profile_data or "powerGovernor" in profile_data:
                    total_operations += 1
                    try:
                        governor_success = await self.set_power_governor(governor)
                        if governor_success:
                            success_count += 1
                            decky.logger.info(f"Applied CPU governor: {governor}")
                        else:
                            decky.logger.warning(f"Failed to apply CPU governor: {governor}")
                    except Exception as e:
                        decky.logger.error(f"Error applying CPU governor: {e}")
                
                # Set EPP if present
                if "epp" in profile_data:
                    total_operations += 1
                    try:
                        epp_success = await self.set_epp(epp)
                        if epp_success:
                            success_count += 1
                            decky.logger.info(f"Applied EPP: {epp}")
                        else:
                            decky.logger.warning(f"Failed to apply EPP: {epp}")
                    except Exception as e:
                        decky.logger.error(f"Error applying EPP: {epp}")
            
            # Apply fan control profile (critical for proper cooling management)
            if "fanProfile" in profile_data:
                total_operations += 1
                try:
                    fan_profile = profile_data["fanProfile"]
                    fan_success = await self.set_fan_cooling_profile(fan_profile)
                    if fan_success.get("success", False):
                        success_count += 1
                        decky.logger.info(f"Applied fan profile: {fan_profile} (service restarted)")
                    else:
                        decky.logger.warning(f"Failed to apply fan profile: {fan_profile}")
                except Exception as e:
                    decky.logger.error(f"Error applying fan profile: {e}")
            
            # Apply GPU mode and frequency settings
            if "gpuMode" in profile_data:
                total_operations += 1
                try:
                    gpu_mode = profile_data["gpuMode"]
                    gpu_success = await self.set_gpu_mode(gpu_mode)
                    if gpu_success:
                        success_count += 1
                        decky.logger.info(f"Applied GPU mode: {gpu_mode}")
                    else:
                        decky.logger.warning(f"Failed to apply GPU mode: {gpu_mode}")
                except Exception as e:
                    decky.logger.error(f"Error applying GPU mode: {e}")
            
            # Apply GPU frequency settings (for manual/range modes)
            if "gpuFreqMin" in profile_data and "gpuFreqMax" in profile_data:
                total_operations += 1
                try:
                    min_freq = profile_data["gpuFreqMin"]
                    max_freq = profile_data["gpuFreqMax"]
                    freq_success = await self.set_gpu_frequency(min_freq, max_freq)
                    if freq_success:
                        success_count += 1
                        decky.logger.info(f"Applied GPU frequency range: {min_freq}-{max_freq} MHz")
                    else:
                        decky.logger.warning(f"Failed to apply GPU frequency range: {min_freq}-{max_freq} MHz")
                except Exception as e:
                    decky.logger.error(f"Error applying GPU frequency: {e}")
            
            # Apply USB autosuspend setting (only if enabled in profile)
            if profile_data.get("usbAutosuspend", False):
                total_operations += 1
                try:
                    usb_success = await self.set_usb_autosuspend(True)
                    if usb_success:
                        success_count += 1
                        decky.logger.info("Applied USB autosuspend: enabled")
                    else:
                        decky.logger.warning("Failed to apply USB autosuspend")
                except Exception as e:
                    decky.logger.error(f"Error applying USB autosuspend: {e}")
            
            # Apply PCIe ASPM setting (only if enabled in profile)  
            if profile_data.get("pcieAspm", False):
                total_operations += 1
                try:
                    pcie_success = await self.set_pcie_aspm_policy("powersave")
                    if pcie_success:
                        success_count += 1
                        decky.logger.info("Applied PCIe ASPM: powersave policy")
                    else:
                        decky.logger.warning("Failed to apply PCIe ASPM")
                except Exception as e:
                    decky.logger.error(f"Error applying PCIe ASPM: {e}")
            
            # Calculate success rate
            if total_operations > 0:
                success_rate = success_count / total_operations
                decky.logger.info(f"Profile application completed: {success_count}/{total_operations} operations successful ({success_rate:.1%})")
                return success_rate >= 0.7  # Consider successful if 70% or more operations succeed
            else:
                decky.logger.warning("No profile operations to apply")
                return False
                
        except Exception as e:
            decky.logger.error(f"Failed to apply profile: {e}")
            return False

    async def get_cpu_limits(self) -> Dict[str, int]:
        """Get CPU frequency limits"""
        try:
            limits = {"min": 1200, "max": 4500}  # Default values
            
            # Try to read actual limits
            try:
                with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq", "r") as f:
                    limits["min"] = int(f.read().strip()) // 1000  # Convert to MHz
                with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "r") as f:
                    limits["max"] = int(f.read().strip()) // 1000  # Convert to MHz
            except Exception:
                pass
                
            return limits
        except Exception as e:
            decky.logger.error(f"Failed to get CPU limits: {e}")
            return {"min": 1200, "max": 4500}

    async def get_online_cpus(self) -> List[int]:
        """Get list of online CPU cores"""
        try:
            online_cpus = []
            cpu_online_path = "/sys/devices/system/cpu/online"
            
            if os.path.exists(cpu_online_path):
                with open(cpu_online_path, "r") as f:
                    online_range = f.read().strip()
                    
                # Parse range like "0-15" or "0,2-7,9"
                for part in online_range.split(','):
                    if '-' in part:
                        start, end = map(int, part.split('-'))
                        online_cpus.extend(range(start, end + 1))
                    else:
                        online_cpus.append(int(part))
            else:
                # Fallback: assume cores 0-15
                online_cpus = list(range(16))
                
            return online_cpus
        except Exception as e:
            decky.logger.error(f"Failed to get online CPUs: {e}")
            return list(range(16))  # Fallback to 16 cores

    # Support method implementations
    async def supports_tdp(self) -> bool:
        """Check if TDP control is supported"""
        return self.device_info.get("supports_tdp", False)

    async def supports_cpu_boost(self) -> bool:
        """Check if CPU boost control is supported"""
        return self.device_info.get("supports_cpu_boost", False)
        
    async def supports_smt(self) -> bool:
        """Check if SMT control is supported"""
        return self.device_info.get("supports_smt", False)
        
    async def supports_core_control(self) -> bool:
        """Check if CPU core control is supported"""
        return os.path.exists("/sys/devices/system/cpu/cpu1/online")
        
    async def supports_gpu_control(self) -> bool:
        """Check if GPU control is supported"""
        return self.device_info.get("supports_gpu_control", False)

    # Current state methods
    async def get_current_tdp(self) -> int:
        """Get current TDP value"""
        try:
            ryzenadj_available = bool(self.ryzenadj_path)
            if self.device_info.get("cpu_vendor") == "AMD" and ryzenadj_available:
                # Try to get actual TDP from ryzenadj
                try:
                    result = subprocess.run([self.ryzenadj_path, "--info"], 
                                          capture_output=True, text=True, timeout=5,
                                          stderr=subprocess.DEVNULL)  # Suppress stderr to prevent NVMe wake
                    if result.returncode == 0:
                        # Parse ryzenadj output for current TDP
                        for line in result.stdout.split('\n'):
                            if 'PPT LIMIT FAST' in line:
                                # Extract TDP value
                                parts = line.split()
                                for i, part in enumerate(parts):
                                    if part.replace('.', '', 1).isdigit():
                                        return int(float(part))
                except Exception as e:
                    decky.logger.error(f"Ryzenadj info failed: {e}")
            
            # Fallback: return stored value or default
            return self.current_profile.get("tdp", 15)
        except Exception as e:
            decky.logger.error(f"Failed to get current TDP: {e}")
            return 15

    async def get_current_gpu_frequency(self) -> int:
        """Get current GPU frequency - supports both AMD and Intel GPUs"""
        try:
            # Check if Intel GPU is available via sysfs power manager
            intel_gpu_capabilities = sysfs_power_manager.get_capabilities()
            if intel_gpu_capabilities.supports_intel_gpu:
                return sysfs_power_manager.get_intel_gpu_current_frequency()
            else:
                # AMD GPU frequency detection
                gpu_freq_path = "/sys/class/drm/card0/device/pp_dpm_sclk"
                if not os.path.exists(gpu_freq_path):
                    gpu_freq_path = "/sys/class/drm/card1/device/pp_dpm_sclk"
                    
                if os.path.exists(gpu_freq_path):
                    with open(gpu_freq_path, "r") as f:
                        lines = f.read().strip().split('\n')
                        # Find the line with * (current frequency)
                        for line in lines:
                            if '*' in line:
                                # Extract frequency (format: "1: 800Mhz *")
                                parts = line.split()
                                for part in parts:
                                    if 'Mhz' in part or 'MHz' in part:
                                        return int(part.replace('Mhz', '').replace('MHz', ''))
                
                # Fallback
                return self.current_profile.get("gpuFreq", 1600)
                
        except Exception as e:
            decky.logger.error(f"Failed to get GPU frequency: {e}")
            return self.current_profile.get("gpuFreq", 1600)
        except Exception as e:
            decky.logger.error(f"Failed to get GPU frequency: {e}")
            return 1600

    async def get_current_cpu_boost(self) -> bool:
        """Get current CPU boost status"""
        try:
            boost_path = "/sys/devices/system/cpu/cpufreq/boost"
            if os.path.exists(boost_path):
                with open(boost_path, "r") as f:
                    return f.read().strip() == "1"
            return self.current_profile.get("cpuBoost", True)
        except Exception as e:
            decky.logger.error(f"Failed to get CPU boost status: {e}")
            return True

    async def get_current_power_governor(self) -> str:
        """Get current power governor"""
        try:
            gov_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
            if os.path.exists(gov_path):
                with open(gov_path, "r") as f:
                    return f.read().strip()
            return self.current_profile.get("governor", "powersave")
        except Exception as e:
            decky.logger.error(f"Failed to get power governor: {e}")
            return "powersave"

    async def get_current_epp(self) -> str:
        """Get current EPP setting"""
        try:
            epp_path = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
            if os.path.exists(epp_path):
                with open(epp_path, "r") as f:
                    return f.read().strip()
            return self.current_profile.get("epp", "balance_power")
        except Exception as e:
            decky.logger.error(f"Failed to get EPP: {e}")
            return "balance_power"

    async def get_current_gpu_mode(self) -> str:
        """Get current GPU mode"""
        try:
            gpu_path = "/sys/class/drm/card0/device/power_dpm_force_performance_level"
            if not os.path.exists(gpu_path):
                gpu_path = "/sys/class/drm/card1/device/power_dpm_force_performance_level"
                
            if os.path.exists(gpu_path):
                with open(gpu_path, "r") as f:
                    dpm_mode = f.read().strip()
                    # Map DPM modes back to our modes
                    mode_mapping = {
                        "low": "battery",
                        "auto": "balanced", 
                        "manual": "range",
                        "high": "performance"
                    }
                    return mode_mapping.get(dpm_mode, "balanced")
            return self.current_profile.get("gpuMode", "balanced")
        except Exception as e:
            decky.logger.error(f"Failed to get GPU mode: {e}")
            return "balanced"

    async def get_available_governors(self) -> List[str]:
        """Get list of available power governors"""
        try:
            # First check scaling driver to determine correct governors
            scaling_driver = await self.get_scaling_driver()
            decky.logger.info(f"GET_AVAILABLE_GOVERNORS: Scaling driver: {scaling_driver}")
            
            # For amd-pstate-epp, only performance and powersave are valid
            if scaling_driver == "amd-pstate-epp":
                governors = ["performance", "powersave"]
                decky.logger.info(f"GET_AVAILABLE_GOVERNORS: Using amd-pstate-epp governors: {governors}")
                return governors
            
            # For other drivers, read from system file
            gov_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"
            if os.path.exists(gov_path):
                with open(gov_path, "r") as f:
                    governors = f.read().strip().split()
                    decky.logger.info(f"GET_AVAILABLE_GOVERNORS: Read from file: {governors}")
                    return governors
            
            # Fallback for unknown drivers
            governors = ["performance", "powersave", "schedutil", "ondemand", "conservative"]
            decky.logger.info(f"GET_AVAILABLE_GOVERNORS: Using fallback: {governors}")
            return governors
        except Exception as e:
            decky.logger.error(f"Failed to get available governors: {e}")
            return ["performance", "powersave", "schedutil"]

    async def get_available_epp_options(self) -> List[str]:
        """Get list of available EPP options"""
        try:
            epp_path = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences"
            if os.path.exists(epp_path):
                with open(epp_path, "r") as f:
                    return f.read().strip().split()
            return ["performance", "balance_performance", "balance_power", "power"]
        except Exception as e:
            decky.logger.error(f"Failed to get available EPP options: {e}")
            return ["performance", "balance_performance", "balance_power", "power"]

    async def get_available_fan_profiles(self) -> List[str]:
        """Get list of available fan profiles"""
        if device_support_available:
            # Return profiles that match steamfork_fan_controller
            return ["auto", "quiet", "moderate", "aggressive"]
        else:
            return ["auto", "quiet", "moderate", "aggressive"]

    async def get_tdp_limits(self) -> Dict[str, int]:
        """Get TDP limits for this device using processor database"""
        device_info = await self.get_device_info()
        return {
            "min": device_info.get("tdp_min", 4),      # Hard-coded minimum (4W)
            "max": device_info.get("tdp_max", 25)      # Database maximum (ctdp_max)
        }

    async def get_default_tdp(self) -> int:
        """Get default TDP from processor database (ctdp_min) - Plugin class method"""
        device_info = await self.get_device_info()
        return device_info.get("tdp_default", 15)  # Database default (ctdp_min)

    async def get_cpu_cstate_info(self) -> Dict[str, Any]:
        """Get C-state information for frontend display"""
        try:
            from cpu_manager import get_cpu_manager
            cpu_manager = get_cpu_manager()
            
            cstate_info = cpu_manager.get_cpu_cstate_info()
            
            # Add summary information
            summary = {
                'supports_cstates': len(cstate_info) > 0,
                'deepest_cstate': 'C0',
                'total_online_cpus': len(cstate_info)
            }
            
            # Find deepest available C-state
            for cpu_key, cpu_info in cstate_info.items():
                for cstate in cpu_info.get('available_cstates', []):
                    state_name = cstate.get('name', '')
                    if state_name in ['C3', 'C6', 'C7', 'C8', 'C9', 'C10']:
                        if state_name > summary['deepest_cstate']:
                            summary['deepest_cstate'] = state_name
            
            return {
                'summary': summary,
                'detailed_info': cstate_info
            }
            
        except Exception as e:
            decky.logger.error(f"Failed to get C-state info: {e}")
            return {
                'summary': {
                    'supports_cstates': False,
                    'deepest_cstate': 'Unknown',
                    'total_online_cpus': 0
                },
                'detailed_info': {}
            }
        """Get current effective CPU cores considering SMT status"""
        try:
            smt_enabled = await self.get_current_smt_status()
            physical_cores = psutil.cpu_count(logical=False)
            
            # Count actually online cores
            online_cpus = await self.get_online_cpus()
            online_count = len([cpu for cpu in online_cpus if await self.is_cpu_online(cpu)])
            
            return online_count
        except Exception as e:
            decky.logger.error(f"Failed to get effective CPU cores: {e}")
            return 8

    async def is_cpu_online(self, cpu_id: int) -> bool:
        """Check if a specific CPU core is online"""
        try:
            if cpu_id == 0:
                return True  # CPU 0 is always online
            cpu_path = f"/sys/devices/system/cpu/cpu{cpu_id}/online"
            if os.path.exists(cpu_path):
                with open(cpu_path, "r") as f:
                    return f.read().strip() == "1"
            return True
        except Exception as e:
            return True

    async def get_current_cpu_core_count(self) -> int:
        """Get current number of online CPU cores"""
        try:
            # Use the same method as get_online_cpus for consistency
            online_cpus = await self.get_online_cpus()
            return len(online_cpus)
        except Exception as e:
            decky.logger.error(f"Failed to get current CPU core count: {e}")
            return 8

    # Universal Power Management Methods
    async def get_pcie_aspm_policy(self) -> str:
        """Get current PCIe ASPM policy"""
        try:
            if self.device_info.get("supports_pcie_aspm"):
                with open("/sys/module/pcie_aspm/parameters/policy", "r") as f:
                    policy_line = f.read().strip()
                    # Extract current policy (marked with brackets)
                    for policy in policy_line.split():
                        if policy.startswith("[") and policy.endswith("]"):
                            return policy[1:-1]
            return "default"
        except Exception as e:
            decky.logger.error(f"Failed to get PCIe ASPM policy: {e}")
            return "default"

    async def set_pcie_aspm_policy(self, policy: str) -> bool:
        """Set PCIe ASPM policy (default, performance, powersave, powersupersave)"""
        try:
            if not self.device_info.get("supports_pcie_aspm"):
                return False
            
            valid_policies = ["default", "performance", "powersave", "powersupersave"]
            if policy not in valid_policies:
                return False
                
            with open("/sys/module/pcie_aspm/parameters/policy", "w") as f:
                f.write(policy)
            decky.logger.info(f"Set PCIe ASPM policy to: {policy}")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to set PCIe ASMP policy: {e}")
            return False

    async def get_pcie_power_management(self) -> bool:
        """Get PCIe power management status (wrapper for ASPM policy)"""
        try:
            policy = await self.get_pcie_aspm_policy()
            # Return True if any power saving policy is active
            return policy in ["powersave", "powersupersave"]
        except Exception as e:
            decky.logger.error(f"Failed to get PCIe power management: {e}")
            return False

    async def set_pcie_power_management(self, enabled: bool) -> bool:
        """Set PCIe power management (wrapper for ASPM policy)"""
        try:
            if not self.device_info.get("supports_pcie_aspm"):
                return False
            
            # Use powersave when enabled, default when disabled
            policy = "powersave" if enabled else "default"
            return await self.set_pcie_aspm_policy(policy)
        except Exception as e:
            decky.logger.error(f"Failed to set PCIe power management: {e}")
            return False

    async def get_swappiness(self) -> int:
        """Get current memory swappiness value"""
        try:
            if self.device_info.get("supports_memory_tuning"):
                with open("/proc/sys/vm/swappiness", "r") as f:
                    return int(f.read().strip())
            return 60
        except Exception as e:
            decky.logger.error(f"Failed to get swappiness: {e}")
            return 60

    async def set_swappiness(self, value: int) -> bool:
        """Set memory swappiness (0-100)"""
        try:
            if not self.device_info.get("supports_memory_tuning"):
                return False
            
            if not 0 <= value <= 100:
                return False
                
            with open("/proc/sys/vm/swappiness", "w") as f:
                f.write(str(value))
            decky.logger.info(f"Set swappiness to: {value}")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to set swappiness: {e}")
            return False

    async def get_usb_autosuspend_status(self) -> Dict[str, bool]:
        """Get USB autosuspend status for all devices (excluding critical built-in devices)"""
        try:
            if not self.device_info.get("supports_usb_power_mgmt"):
                return {}
                
            usb_devices = {}
            import glob
            
            # Get VID/PID pairs of all input devices from /proc/bus/input/devices
            input_device_vid_pids = self.get_input_device_vid_pids()
            
            # Same exclusion logic as set_usb_autosuspend
            CRITICAL_DEVICE_EXCLUSIONS = [
                "gamepad", "controller", "joystick", "xbox", "playstation", "nintendo",
                "game", "joy", "pad", "stick", "keyboard", "mouse", "touchpad", 
                "trackpad", "touchscreen", "hid", "input", "builtin", "internal", 
                "integrated", "ayaneo", "rog", "ally", "steam", "deck", "onexplayer", "gpd"
            ]
            
            for control_file in glob.glob("/sys/bus/usb/devices/*/power/control"):
                device_path = os.path.dirname(os.path.dirname(control_file))
                device_name = os.path.basename(device_path)
                
                # Check if this device should be excluded (same logic as set function)
                should_exclude = False
                device_info = ""
                
                try:
                    # First, check if this USB device matches any input device VID/PID
                    vendor_file = os.path.join(device_path, "idVendor")
                    product_file = os.path.join(device_path, "idProduct")
                    
                    if os.path.exists(vendor_file) and os.path.exists(product_file):
                        with open(vendor_file, "r") as f:
                            device_vendor = f.read().strip()
                        with open(product_file, "r") as f:
                            device_product = f.read().strip()
                        
                        # Check if this VID/PID matches any input device
                        for input_vid, input_pid in input_device_vid_pids:
                            if device_vendor == input_vid and device_product == input_pid:
                                should_exclude = True
                                break
                    
                    # Get device information for exclusion check
                    product_name_file = os.path.join(device_path, "product")
                    if os.path.exists(product_name_file):
                        with open(product_name_file, "r") as f:
                            device_info = f.read().strip().lower()
                    
                    manufacturer_file = os.path.join(device_path, "manufacturer")
                    if os.path.exists(manufacturer_file):
                        with open(manufacturer_file, "r") as f:
                            manufacturer = f.read().strip().lower()
                            device_info += " " + manufacturer
                    
                    # Check interface class for HID devices
                    interface_dirs = glob.glob(f"{device_path}/*:*")
                    for interface_dir in interface_dirs:
                        class_file = os.path.join(interface_dir, "bInterfaceClass")
                        if os.path.exists(class_file):
                            with open(class_file, "r") as f:
                                interface_class = f.read().strip()
                                if interface_class == "03":  # HID class
                                    device_info += " hid"
                                    break
                    
                    # If not already excluded by VID/PID, check name-based exclusion patterns
                    if not should_exclude:
                        device_check_string = f"{device_name} {device_info}".lower()
                        for exclusion in CRITICAL_DEVICE_EXCLUSIONS:
                            if exclusion in device_check_string:
                                should_exclude = True
                                break
                    
                except Exception:
                    should_exclude = True  # Exclude if we can't read device info
                
                # Only include non-excluded devices in the status
                if not should_exclude:
                    try:
                        with open(control_file, "r") as f:
                            control = f.read().strip()
                            usb_devices[device_name] = (control == "auto")
                    except Exception:
                        continue
                    
            return usb_devices
        except Exception as e:
            decky.logger.error(f"Failed to get USB autosuspend status: {e}")
            return {}

    def get_input_device_vid_pids(self) -> List[Tuple[str, str]]:
        """Parse /proc/bus/input/devices to find all input device VID/PID pairs (excluding fingerprint readers)"""
        try:
            vid_pids = []
            
            with open("/proc/bus/input/devices", "r") as f:
                content = f.read()
            
            # Split into device blocks
            device_blocks = content.split("\n\n")
            
            for block in device_blocks:
                if not block.strip():
                    continue
                    
                lines = block.strip().split("\n")
                vendor = None
                product = None
                name = ""
                handlers = ""
                
                # Parse device information
                for line in lines:
                    line = line.strip()
                    if line.startswith("I: Bus="):
                        # Extract vendor and product from I: line
                        # Format: I: Bus=0003 Vendor=045e Product=0b00 Version=0001
                        parts = line.split()
                        for part in parts:
                            if part.startswith("Vendor="):
                                vendor = part.split("=")[1]
                            elif part.startswith("Product="):
                                product = part.split("=")[1]
                    elif line.startswith("N: Name="):
                        # Extract device name
                        name = line.split("Name=", 1)[1].strip('"').lower()
                    elif line.startswith("H: Handlers="):
                        # Extract handlers to see what type of device this is
                        handlers = line.split("Handlers=", 1)[1].lower()
                
                # Skip devices without VID/PID or that are clearly not controllers/input devices
                if not vendor or not product:
                    continue
                
                # Exclude fingerprint readers specifically
                if "fingerprint" in name or "finger" in name:
                    decky.logger.info(f"Excluding fingerprint reader: {name} ({vendor}:{product})")
                    continue
                
                # Only include devices that have input capabilities (kbd, mouse, event, js handlers)
                input_handlers = ["kbd", "mouse", "event", "js", "touchscreen"]
                has_input_handler = any(handler in handlers for handler in input_handlers)
                
                if has_input_handler:
                    vid_pids.append((vendor, product))
                    decky.logger.info(f"Found input device: {name} ({vendor}:{product}) - handlers: {handlers}")
                else:
                    decky.logger.debug(f"Skipping non-input device: {name} ({vendor}:{product}) - handlers: {handlers}")
            
            decky.logger.info(f"Found {len(vid_pids)} input devices with VID/PID pairs")
            return vid_pids
            
        except Exception as e:
            decky.logger.error(f"Failed to parse input devices: {e}")
            return []

    async def set_usb_autosuspend(self, enable: bool) -> bool:
        """Enable/disable USB autosuspend for power saving (excluding built-in gaming devices)"""
        try:
            if not self.device_info.get("supports_usb_power_mgmt"):
                return False
                
            import glob
            setting = "auto" if enable else "on"
            count = 0
            excluded_count = 0
            
            # Get VID/PID pairs of all input devices from /proc/bus/input/devices
            input_device_vid_pids = self.get_input_device_vid_pids()
            
            # Define additional device types that should NEVER be power managed
            CRITICAL_DEVICE_EXCLUSIONS = [
                # Built-in gaming controllers (common patterns)
                "gamepad", "controller", "joystick", "xbox", "playstation", "nintendo",
                "game", "joy", "pad", "stick",
                # Built-in keyboards and input devices
                "keyboard", "mouse", "touchpad", "trackpad", "touchscreen",
                # Critical system devices
                "hid", "input", "builtin", "internal", "integrated",
                # Handheld-specific controllers
                "ayaneo", "rog", "ally", "steam", "deck", "onexplayer", "gpd"
            ]
            
            for control_file in glob.glob("/sys/bus/usb/devices/*/power/control"):
                device_path = os.path.dirname(os.path.dirname(control_file))
                device_name = os.path.basename(device_path)
                
                # Check if this device should be excluded from power management
                should_exclude = False
                device_info = ""
                exclusion_reason = ""
                
                try:
                    # First, check if this USB device matches any input device VID/PID
                    vendor_file = os.path.join(device_path, "idVendor")
                    product_file = os.path.join(device_path, "idProduct")
                    
                    if os.path.exists(vendor_file) and os.path.exists(product_file):
                        with open(vendor_file, "r") as f:
                            device_vendor = f.read().strip()
                        with open(product_file, "r") as f:
                            device_product = f.read().strip()
                        
                        # Check if this VID/PID matches any input device
                        for input_vid, input_pid in input_device_vid_pids:
                            if device_vendor == input_vid and device_product == input_pid:
                                should_exclude = True
                                exclusion_reason = f"matches input device VID/PID {input_vid}:{input_pid}"
                                break
                    
                    # Get device product name if available
                    product_name_file = os.path.join(device_path, "product")
                    if os.path.exists(product_name_file):
                        with open(product_name_file, "r") as f:
                            device_info = f.read().strip().lower()
                    
                    # Get device manufacturer if available
                    manufacturer_file = os.path.join(device_path, "manufacturer")
                    if os.path.exists(manufacturer_file):
                        with open(manufacturer_file, "r") as f:
                            manufacturer = f.read().strip().lower()
                            device_info += " " + manufacturer
                    
                    # Check interface class (HID devices are often controllers/keyboards)
                    interface_dirs = glob.glob(f"{device_path}/*:*")
                    for interface_dir in interface_dirs:
                        class_file = os.path.join(interface_dir, "bInterfaceClass")
                        if os.path.exists(class_file):
                            with open(class_file, "r") as f:
                                interface_class = f.read().strip()
                                # Class 03 = HID (Human Interface Device) - often controllers/keyboards
                                if interface_class == "03":
                                    device_info += " hid"
                                    break
                    
                    # If not already excluded by VID/PID, check name-based exclusion patterns
                    if not should_exclude:
                        device_check_string = f"{device_name} {device_info}".lower()
                        for exclusion in CRITICAL_DEVICE_EXCLUSIONS:
                            if exclusion in device_check_string:
                                should_exclude = True
                                exclusion_reason = f"matches pattern '{exclusion}'"
                                break
                    
                    # Log exclusion details
                    if should_exclude:
                        decky.logger.info(f"USB Power Management: Excluding critical device '{device_name}' ({exclusion_reason}) - device info: {device_info}")
                    
                except Exception as e:
                    # If we can't read device info, err on the side of caution and exclude it
                    decky.logger.warning(f"Could not read USB device info for {device_name}, excluding for safety: {e}")
                    should_exclude = True
                    exclusion_reason = "safety exclusion due to read error"
                
                if should_exclude:
                    excluded_count += 1
                    continue
                
                try:
                    with open(control_file, "w") as f:
                        f.write(setting)
                    count += 1
                    decky.logger.debug(f"Set USB autosuspend to {setting} for device {device_name}")
                except Exception as e:
                    decky.logger.warning(f"Failed to set USB autosuspend for {device_name}: {e}")
                    continue
                    
            decky.logger.info(f"USB Power Management: Set autosuspend to {setting} for {count} devices, excluded {excluded_count} critical devices")
            return count > 0
        except Exception as e:
            decky.logger.error(f"Failed to set USB autosuspend: {e}")
            return False

    async def get_wifi_power_save(self) -> bool:
        """Get WiFi power save status"""
        try:
            if not self.device_info.get("supports_wifi_power_save"):
                return False
                
            # Use iwconfig to check power management
            result = subprocess.run(["iwconfig"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return "Power Management:on" in result.stdout
            return False
        except Exception as e:
            decky.logger.error(f"Failed to get WiFi power save: {e}")
            return False

    async def set_wifi_power_save(self, enable: bool) -> bool:
        """Enable/disable WiFi power saving"""
        try:
            if not self.device_info.get("supports_wifi_power_save"):
                self.log_warning_once("WiFi power save not supported on this device")
                return False
                
            # Get WiFi interface name using both methods
            interface = None
            
            # Try iw command first
            try:
                result = subprocess.run(["iw", "dev"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Interface' in line:
                            interface = line.split()[-1]
                            break
                else:
                    self.log_warning_once(f"iw dev command failed: {result.stderr}")
            except Exception as e:
                self.log_warning_once(f"iw command not available: {e}")
            
            # Fallback: try to find interface from /proc/net/wireless
            if not interface:
                try:
                    with open("/proc/net/wireless", "r") as f:
                        lines = f.readlines()
                        for line in lines[2:]:  # Skip header lines
                            if ':' in line:
                                interface = line.split(':')[0].strip()
                                break
                except Exception as e:
                    self.log_warning_once(f"Failed to read /proc/net/wireless: {e}")
                    
            if not interface:
                decky.logger.error("No WiFi interface found")
                return False
                
            decky.logger.info(f"Using WiFi interface: {interface}")
            
            # Set power save mode - try both iw and iwconfig methods
            power_mode = "on" if enable else "off"
            
            # Method 1: Try iw command (newer systems)
            try:
                result = subprocess.run(["iw", interface, "set", "power_save", power_mode], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    decky.logger.info(f"Set WiFi power save to: {power_mode} using iw")
                    return True
                else:
                    self.log_warning_once(f"iw power save failed: {result.stderr}")
            except Exception as e:
                self.log_warning_once(f"iw power save command failed: {e}")
            
            # Method 2: Try iwconfig command (older systems/fallback)
            try:
                iwconfig_mode = "on" if enable else "off"
                result = subprocess.run(["iwconfig", interface, "power", iwconfig_mode], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    decky.logger.info(f"Set WiFi power save to: {power_mode} using iwconfig")
                    return True
                else:
                    self.log_warning_once(f"iwconfig power save failed: {result.stderr}")
            except Exception as e:
                self.log_warning_once(f"iwconfig power save command failed: {e}")
                
            decky.logger.error("All WiFi power save methods failed")
            return False
            
        except Exception as e:
            decky.logger.error(f"Failed to set WiFi power save: {e}")
            return False

    async def get_cpu_system_info(self) -> Dict[str, Any]:
        """Get comprehensive CPU system information including P-state status"""
        try:
            if self.cpu_manager:
                return self.cpu_manager.get_system_info()
            else:
                decky.logger.warning("CPU manager not initialized")
                return {
                    'scaling_driver': 'unknown',
                    'available_governors': ['performance', 'powersave', 'schedutil'],
                    'current_governor': 'unknown',
                    'available_epp_options': ['performance', 'balance_performance', 'balance_power', 'power'],
                    'current_epp': 'unknown',
                    'supports_cpu_boost': False,
                    'cpu_boost_enabled': False,
                    'supports_smt': False,
                    'smt_enabled': False,
                    'supports_epp': False,
                    'pstate_status': None,
                    'online_cpus': await self.detect_max_cpu_cores(),
                    'total_cpus': await self.detect_max_cpu_cores(),
                    'max_cpu_cores': await self.detect_max_cpu_cores()
                }
        except Exception as e:
            decky.logger.error(f"Failed to get CPU system info: {e}")
            return {
                'scaling_driver': 'error',
                'available_governors': ['performance', 'powersave'],
                'current_governor': 'unknown',
                'available_epp_options': ['performance', 'power'],
                'current_epp': 'unknown',
                'supports_cpu_boost': False,
                'cpu_boost_enabled': False,
                'supports_smt': False,
                'smt_enabled': False,
                'supports_epp': False,
                'pstate_status': None,
                'online_cpus': 2,
                'total_cpus': 4,
                'max_cpu_cores': 4
            }

    async def get_per_game_profiles_enabled(self) -> bool:
        """Get per-game profiles setting"""
        return self.enable_per_game_profiles

    async def set_per_game_profiles_enabled(self, enabled: bool) -> bool:
        """Set per-game profiles setting"""
        try:
            self.enable_per_game_profiles = enabled
            await self.save_settings()
            decky.logger.info(f"Per-game profiles setting changed to: {enabled}")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to set per-game profiles setting: {e}")
            return False

    async def get_rog_ally_native_tdp_enabled(self) -> bool:
        """Get ROG Ally native TDP support setting"""
        return self.rog_ally_native_tdp_enabled

    async def set_rog_ally_native_tdp_enabled(self, enabled: bool) -> bool:
        """Set ROG Ally native TDP support setting"""
        try:
            # Only allow this setting on ROG Ally devices
            if not await self.is_rog_ally_device():
                decky.logger.warning("ROG Ally native TDP setting only available on ROG Ally devices")
                return False
                
            self.rog_ally_native_tdp_enabled = enabled
            await self.save_settings()
            decky.logger.info(f"ROG Ally native TDP support changed to: {enabled}")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to set ROG Ally native TDP setting: {e}")
            return False

    async def is_rog_ally_device(self) -> bool:
        """Check if current device is a ROG Ally or ROG Ally X"""
        try:
            device_name = self.device_info.get("device_name", "").lower()
            return ("rog ally" in device_name or "rc71" in device_name or "rc72" in device_name)
        except Exception as e:
            decky.logger.error(f"Failed to check ROG Ally device: {e}")
            return False

    async def get_tdp_control_mode(self) -> str:
        """Get current TDP control mode (powerdeck, rog_ally_native, etc.)"""
        try:
            if self.device_type == "rog_ally":
                if self.rog_ally_native_tdp_enabled:
                    return "rog_ally_native"
                else:
                    return "powerdeck"
            elif self.device_type in ["legion", "steam_deck"]:
                return f"{self.device_type}_native"
            else:
                return "powerdeck"
        except Exception as e:
            decky.logger.error(f"Failed to get TDP control mode: {e}")
            return "powerdeck"

    # Processor Database API Methods
    async def get_processor_info(self) -> Dict[str, Any]:
        """Get comprehensive processor information and specifications"""
        try:
            if processor_support_available and self.processor_info:
                return self.processor_info
            else:
                return {
                    "detected": False,
                    "processor_name": "Unknown Processor",
                    "cpu_info": "Detection not available",
                    "message": "Processor database not loaded"
                }
        except Exception as e:
            decky.logger.error(f"Failed to get processor info: {e}")
            return {"detected": False, "error": str(e)}

    async def get_processor_capabilities(self) -> Dict[str, Any]:
        """Get processor capabilities and recommendations for PowerDeck"""
        try:
            if not processor_support_available:
                return {"available": False, "message": "Processor detection not available"}
                
            capabilities = get_current_processor_info()
            
            # Add current system state
            capabilities["current_tdp_limits"] = self.tdp_limits
            capabilities["is_handheld"] = is_handheld_device()
            capabilities["detection_available"] = True
            
            return capabilities
            
        except Exception as e:
            decky.logger.error(f"Failed to get processor capabilities: {e}")
            return {"available": False, "error": str(e)}

    async def refresh_processor_detection(self) -> bool:
        """Refresh processor detection (clear cache and re-detect)"""
        try:
            if not processor_support_available:
                return False
                
            refresh_processor_detection()
            self.processor_info = get_current_processor_info()
            
            # Update TDP limits based on refreshed detection
            if self.processor_info.get("detected", False):
                proc_tdp_min, proc_tdp_max = get_processor_tdp_limits()
                self.tdp_limits = {"min": proc_tdp_min, "max": proc_tdp_max}
                self.device_info["min_tdp"] = proc_tdp_min
                self.device_info["max_tdp"] = proc_tdp_max
                
            decky.logger.info("Processor detection refreshed")
            return True
            
        except Exception as e:
            decky.logger.error(f"Failed to refresh processor detection: {e}")
            return False

    async def get_processor_database_info(self) -> Dict[str, Any]:
        """Get information about the processor database"""
        try:
            if not processor_support_available:
                return {"available": False, "message": "Processor database not loaded"}
                
            # Use unified processor database instead of deprecated amd_processor_db
            db_stats = get_database_stats()
            
            return {
                "available": True,
                "total_processors": db_stats.get("total_processors", 0),
                "handheld_processors": db_stats.get("amd_processors", 0),  # AMD processors typically used in handhelds
                "processor_list": [f"Unified DB: {db_stats.get('total_processors', 0)} processors"],  # Summary instead of full list
                "amd_processors": db_stats.get("amd_processors", 0),
                "intel_processors": db_stats.get("intel_processors", 0),
                "database_version": get_plugin_version()
            }
            
        except Exception as e:
            decky.logger.error(f"Failed to get processor database info: {e}")
            return {"available": False, "error": str(e)}

    async def get_recommended_profiles_for_processor(self) -> List[Dict[str, Any]]:
        """Get recommended power profiles for the current processor"""
        try:
            if not processor_support_available or not self.processor_info:
                return []
                
            return self.processor_info.get("recommended_profiles", [])
            
        except Exception as e:
            decky.logger.error(f"Failed to get recommended profiles: {e}")
            return []

    # SteamFork Fan Control Integration
    async def get_fan_control_info(self) -> Dict[str, Any]:
        """Get SteamFork fan control information"""
        try:
            decky.logger.info(f"Fan control request - device_support_available: {device_support_available}")
            if not device_support_available:
                return {"available": False, "error": "Device support not available"}
                
            result = await steamfork_fan_controller.get_fan_info()
            decky.logger.info(f"Fan control result: {result}")
            return result
            
        except Exception as e:
            decky.logger.error(f"Failed to get fan control info: {e}")
            return {"available": False, "error": str(e)}

    async def set_fan_cooling_profile(self, profile: str) -> Dict[str, Any]:
        """Set SteamFork cooling profile"""
        try:
            if not device_support_available:
                return {"success": False, "error": "Device support not available"}
                
            result = await steamfork_fan_controller.set_cooling_profile(profile)
            
            if result.get("success"):
                decky.logger.info(f"Fan cooling profile set to: {profile}")
            else:
                decky.logger.error(f"Failed to set fan cooling profile: {result.get('error')}")
                
            return result
            
        except Exception as e:
            decky.logger.error(f"Failed to set fan cooling profile: {e}")
            return {"success": False, "error": str(e)}

    # Proper priority cascade: sysfs -> database -> fallback
    async def get_hybrid_tdp_limits(self) -> Dict[str, Any]:
        """Get TDP limits using proper priority: sysfs -> database -> fallback"""
        try:
            # 1. Try sysfs approach first
            if sysfs_support_available:
                try:
                    sysfs_caps = get_sysfs_power_capabilities()
                    if sysfs_caps["detected"] and sysfs_caps.get("tdp_info", {}).get("supports_tdp_control"):
                        info_log(f"Using sysfs power management for {sysfs_caps['processor_name']}")
                        return {
                            "method": "sysfs",
                            "min": sysfs_caps["tdp_info"]["min_watts"],
                            "max": sysfs_caps["tdp_info"]["max_watts"],
                            "current": sysfs_caps["tdp_info"]["current_watts"],
                            "detected_cpu": sysfs_caps["processor_name"],
                            "cpu_vendor": sysfs_caps["cpu_vendor"],
                            "capabilities": sysfs_caps
                        }
                except Exception as e:
                    debug_error(f"Sysfs power detection failed: {e}")
            
            # 2. Fall back to processor database if sysfs missing data
            if processor_support_available:
                try:
                    proc_tdp_min, proc_tdp_max = get_processor_tdp_limits()
                    processor_info = get_current_processor_info()
                    info_log(f"Using processor database for {processor_info.get('processor_name', 'Unknown')}")
                    return {
                        "method": "database",
                        "min": 4,  # Fixed 4W minimum
                        "max": proc_tdp_max,
                        "detected_cpu": processor_info.get("processor_name", "Unknown CPU"),
                        "processor_info": processor_info
                    }
                except Exception as e:
                    debug_error(f"Processor database detection failed: {e}")
            
            # 3. Final fallback to device-specific safe limits (last resort only)
            device_name = await self.get_device_name()
            safe_limits = self.calculate_safe_tdp_limits(device_name)
            info_log(f"Using device-specific fallback limits for {device_name}")
            return {
                "method": "device_fallback",
                "min": 4,
                "max": safe_limits["max"],
                "detected_cpu": f"Fallback limits for {device_name}"
            }
            
        except Exception as e:
            error_log(f"All TDP detection methods failed: {e}")
            return {
                "method": "emergency_fallback",
                "min": 4,
                "max": 25,
                "detected_cpu": "Emergency safety limits"
            }

    # CPU database integration for proper TDP limits
    async def get_processor_tdp_limits(self) -> Dict[str, Any]:
        """Get processor-based TDP limits with CPU detection - CORRECTED: 4W min, database max"""
        try:
            if processor_support_available:
                proc_tdp_min, proc_tdp_max = get_processor_tdp_limits()
                processor_info = get_current_processor_info()
                
                # CORRECTED: Always use 4W minimum, use database maximum
                return {
                    "min": 4,  # Fixed 4W minimum as required
                    "max": proc_tdp_max,  # Use database maximum (30W for 7840U)
                    "detected_cpu": processor_info.get("processor_name", "Unknown CPU")
                }
            else:
                # Fallback to device-specific safe limits
                device_name = await self.get_device_name()
                safe_limits = self.calculate_safe_tdp_limits(device_name)
                return {
                    "min": 4,  # Fixed 4W minimum as required
                    "max": safe_limits["max"],  # Use calculated safe maximum
                    "detected_cpu": f"Safety limits for {device_name}"
                }
        except Exception as e:
            decky.logger.error(f"Failed to get processor TDP limits: {e}")
            return {"min": 4, "max": 25, "detected_cpu": "Fallback safety limits"}

    # Enhanced device classification for proper profile naming
    async def get_device_classification(self) -> str:
        """Get device classification (Handheld, Portable, Desktop) for profile naming"""
        try:
            decky.logger.info("=== DEVICE CLASSIFICATION CHECK ===")
            # Get device name first for robust detection
            device_name = await self.get_device_name()
            device_lower = device_name.lower()
            decky.logger.info(f"Device classification: checking '{device_name}' (lower: '{device_lower}')")
            
            # Gaming handhelds have specific identifiers - CHECK FIRST
            gaming_identifiers = [
                "ayaneo", "rog ally", "steam deck", "legion go", 
                "onexplayer", "oxp", "gpd", "win max", "aya neo", "ally"
            ]
            
            # PRIORITY: Direct device name matching (most reliable)
            for identifier in gaming_identifiers:
                if identifier in device_lower:
                    decky.logger.info(f"Device classified as Handheld via device name match: '{identifier}' found in '{device_name}'")
                    return "Handheld"
            
            decky.logger.info("No gaming identifier match found in device name")
            
            # Check if it's a handheld gaming device via processor detection
            if processor_support_available:
                try:
                    if is_handheld_device():
                        decky.logger.info(f"Device classified as Handheld via processor detection")
                        return "Handheld"
                    else:
                        decky.logger.info("Processor detection says not a handheld device")
                except Exception as e:
                    decky.logger.warning(f"Processor handheld detection failed: {e}")
            else:
                decky.logger.info("Processor support not available for handheld detection")
            
            # Check if it's a handheld device using processor database
            if processor_support_available:
                try:
                    if is_handheld_device():
                        decky.logger.info(f"Device classified as Handheld via processor database")
                        return "Handheld"
                    else:
                        decky.logger.info("Processor database says not a handheld device")
                except Exception as e:
                    decky.logger.warning(f"Processor handheld detection failed: {e}")
            else:
                decky.logger.info("Processor support not available for handheld detection")
            
            # Check if it's a laptop (has battery but not a gaming handheld)
            battery = psutil.sensors_battery()
            if battery is not None:
                decky.logger.info(f"Device classified as Portable (has battery, not handheld): battery={battery.percent}%")
                return "Portable"  # Laptop without built-in gamepad
            else:
                decky.logger.info(f"Device classified as Desktop (no battery detected)")
                return "Desktop"  # No battery = desktop
                
        except Exception as e:
            decky.logger.error(f"Failed to classify device: {e}")
            return "Device"  # Fallback

    # Version and update functionality 
    async def get_current_version(self) -> str:
        """Get current plugin version"""
        return get_plugin_version()

    async def get_latest_version(self) -> str:
        """Get latest available version from GitHub API"""
        try:
            import urllib.request
            import urllib.error
            import ssl
            import re
            
            # GitHub API endpoint for latest release
            github_api_url = "https://api.github.com/repos/fewtarius/PowerDeck/releases/latest"
            
            decky.logger.info("Fetching latest version from GitHub...")
            
            try:
                # Create SSL context that doesn't verify certificates (for compatibility)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(github_api_url, timeout=10, context=ssl_context) as response:
                    data = json.loads(response.read().decode())
                    
                    # Extract version from tag_name (e.g., "v1.2.0" -> "1.2.0")
                    tag_name = data.get('tag_name', '')
                    if tag_name:
                        # Remove 'v' prefix if present
                        version_match = re.match(r'v?(.+)', tag_name)
                        if version_match:
                            latest_version = version_match.group(1)
                            decky.logger.info(f"Latest version from GitHub: {latest_version}")
                            return latest_version
                    
                    decky.logger.warning("No valid tag_name found in GitHub response")
                    return await self.get_current_version()
                    
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    decky.logger.info("No releases found in GitHub repository")
                    return await self.get_current_version()
                else:
                    decky.logger.error(f"HTTP error fetching latest version: {e}")
                    return await self.get_current_version()
            except Exception as e:
                decky.logger.error(f"Error fetching latest version: {e}")
                return await self.get_current_version()
                
        except Exception as e:
            decky.logger.error(f"Failed to get latest version: {e}")
            return get_plugin_version()

    async def check_for_updates(self) -> dict:
        """Check for available updates without downloading - Plugin class method"""
        try:
            import urllib.request
            import urllib.error
            import ssl
            import re
            from packaging import version
            
            # Get current version
            current_version = await self.get_current_version()
            decky.logger.info(f"Current PowerDeck version: {current_version}")
            
            # Check for updates from fewtarius/PowerDeck repository (public distribution repo)
            github_api_url = "https://api.github.com/repos/fewtarius/PowerDeck/releases/latest"
            
            decky.logger.info("Checking for PowerDeck updates...")
            
            try:
                # Create SSL context that doesn't verify certificates (for compatibility)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(github_api_url, timeout=10, context=ssl_context) as response:
                    data = json.loads(response.read().decode())
                    
                    tag_name = data.get('tag_name', '')
                    release_name = data.get('name', '')
                    release_body = data.get('body', '')
                    assets = data.get('assets', [])
                    
                    if tag_name:
                        # Extract version from tag_name (e.g., "v1.2.0" -> "1.2.0")
                        version_match = re.match(r'v?(.+)', tag_name)
                        if version_match:
                            latest_version = version_match.group(1)
                            
                            decky.logger.info(f"Latest version available: {latest_version}")
                            decky.logger.info(f"Release: {release_name}")
                            
                            try:
                                # Compare versions using packaging library
                                if version.parse(latest_version) > version.parse(current_version):
                                    decky.logger.info(f"UPDATE AVAILABLE: {current_version} -> {latest_version}")
                                    
                                    # Find the downloadable asset
                                    download_url = None
                                    for asset in assets:
                                        asset_name = asset.get('name', '').lower()
                                        if asset_name.endswith('.zip') or 'powerdeck' in asset_name:
                                            download_url = asset.get('browser_download_url')
                                            break
                                    
                                    # Fallback to source code zip if no specific asset found
                                    if not download_url:
                                        download_url = f"https://github.com/fewtarius/PowerDeck/archive/refs/tags/{tag_name}.zip"
                                    
                                    # Store update info for later installation
                                    self.update_available = True
                                    self.latest_available_version = latest_version
                                    
                                    return {
                                        'update_available': True,
                                        'current_version': current_version,
                                        'latest_version': latest_version,
                                        'release_name': release_name,
                                        'release_notes': release_body,
                                        'download_url': download_url,
                                        'staged': False
                                    }
                                    
                                else:
                                    decky.logger.info(f"You have the latest version: {current_version}")
                                    return {
                                        'update_available': False,
                                        'current_version': current_version,
                                        'latest_version': current_version,
                                        'message': 'You have the latest version'
                                    }
                                    
                            except Exception as ve:
                                # Fallback to string comparison if packaging fails
                                decky.logger.warning(f"Version comparison failed, using string comparison: {ve}")
                                if latest_version != current_version:
                                    decky.logger.info(f"VERSION DIFFERENCE DETECTED: {current_version} vs {latest_version}")
                                    
                                    # Find downloadable asset
                                    download_url = None
                                    for asset in assets:
                                        asset_name = asset.get('name', '').lower()
                                        if asset_name.endswith('.zip') or 'powerdeck' in asset_name:
                                            download_url = asset.get('browser_download_url')
                                            break
                                    
                                    if not download_url:
                                        download_url = f"https://github.com/fewtarius/PowerDeck/archive/refs/tags/{tag_name}.zip"
                                    
                                    self.update_available = True
                                    self.latest_available_version = latest_version
                                    
                                    return {
                                        'update_available': True,
                                        'current_version': current_version,
                                        'latest_version': latest_version,
                                        'release_name': release_name,
                                        'release_notes': release_body,
                                        'download_url': download_url,
                                        'staged': False
                                    }
                                else:
                                    return {
                                        'update_available': False,
                                        'current_version': current_version,
                                        'latest_version': current_version,
                                        'message': 'No version difference detected'
                                    }
                    
                    return {
                        'update_available': False,
                        'current_version': current_version,
                        'error': 'No valid version information found in GitHub response'
                    }
                    
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    decky.logger.info("No releases found in repository (repository may be private)")
                    return {
                        'update_available': False,
                        'current_version': current_version,
                        'error': 'No releases found'
                    }
                else:
                    decky.logger.error(f"HTTP error checking for updates: {e}")
                    return {
                        'update_available': False,
                        'current_version': current_version,
                        'error': f'HTTP error: {e}'
                    }
                    
            except Exception as e:
                decky.logger.error(f"Error checking for updates: {e}")
                return {
                    'update_available': False,
                    'current_version': current_version,
                    'error': str(e)
                }
                
        except ImportError as e:
            decky.logger.warning(f"Update checking disabled due to missing dependencies: {e}")
            current_version = await self.get_current_version()
            return {
                'update_available': False,
                'current_version': current_version,
                'error': 'Update checking disabled - missing dependencies'
            }
        except Exception as e:
            decky.logger.error(f"Failed to check for updates: {e}")
            current_version = await self.get_current_version()
            return {
                'update_available': False,
                'current_version': current_version,
                'error': str(e)
            }

    async def stage_update(self, download_url: str, version: str) -> dict:
        """Download and stage an update without installing - Plugin class method"""
        try:
            import urllib.request
            import tempfile
            import zipfile
            import shutil
            import os
            
            decky.logger.info(f"Staging PowerDeck v{version} update")
            decky.logger.info(f"Downloading from {download_url}...")
            
            # Clean up any existing staged update
            await self._cleanup_staged_update()
            
            # Create staging directory
            os.makedirs(self.update_staging_dir, exist_ok=True)
            
            # Download the update file
            update_file = os.path.join(self.update_staging_dir, f"powerdeck-{version}.zip")
            
            try:
                # Create SSL context that bypasses certificate verification for embedded systems
                import ssl
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                # Use urlopen with SSL context instead of urlretrieve
                import urllib.request
                with urllib.request.urlopen(download_url, timeout=30, context=ssl_context) as response:
                    with open(update_file, 'wb') as f:
                        f.write(response.read())
                
                decky.logger.info(f"Downloaded update to {update_file}")
            except Exception as e:
                decky.logger.error(f"Failed to download update: {e}")
                return {
                    'success': False,
                    'error': f'Download failed: {str(e)}'
                }
            
            # Extract and validate the update
            extract_dir = os.path.join(self.update_staging_dir, "extracted")
            
            try:
                with zipfile.ZipFile(update_file, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                decky.logger.info(f"Extracted update to {extract_dir}")
            except Exception as e:
                decky.logger.error(f"Failed to extract update: {e}")
                return {
                    'success': False,
                    'error': f'Extraction failed: {str(e)}'
                }
            
            # Find the PowerDeck source directory in extracted files
            plugin_source_dir = None
            for root, dirs, files in os.walk(extract_dir):
                if 'main.py' in files and 'plugin.json' in files:
                    plugin_source_dir = root
                    break
            
            if not plugin_source_dir:
                decky.logger.error("Could not find PowerDeck/ directory in downloaded update")
                return {
                    'success': False,
                    'error': 'Invalid update package - PowerDeck directory not found'
                }
            
            decky.logger.info(f"Found plugin source at: {plugin_source_dir}")
            
            # Validate the update package
            validation_result = await self._validate_staged_update(plugin_source_dir, version)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'error': f"Update validation failed: {validation_result['error']}"
                }
            
            # Store staging information
            self.staged_update_info = {
                'version': version,
                'download_url': download_url,
                'staged_at': time.time(),
                'source_dir': plugin_source_dir,
                'validation': validation_result
            }
            self.staged_update_path = plugin_source_dir
            
            decky.logger.info(f"Update v{version} staged successfully and validated")
            
            return {
                'success': True,
                'version': version,
                'staged_at': time.time(),
                'validation': validation_result,
                'message': f'Update v{version} staged successfully'
            }
            
        except Exception as e:
            decky.logger.error(f"Failed to stage update: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _validate_staged_update(self, source_dir: str, expected_version: str) -> dict:
        """Validate a staged update package"""
        try:
            # Check required files exist
            required_files = ['main.py', 'plugin.json']
            missing_files = []
            
            for file in required_files:
                file_path = os.path.join(source_dir, file)
                if not os.path.exists(file_path):
                    missing_files.append(file)
            
            if missing_files:
                return {
                    'valid': False,
                    'error': f'Missing required files: {", ".join(missing_files)}'
                }
            
            # Validate plugin.json
            try:
                plugin_json_path = os.path.join(source_dir, 'plugin.json')
                with open(plugin_json_path, 'r') as f:
                    plugin_data = json.load(f)
                
                # Check version matches
                file_version = plugin_data.get('version', 'unknown')
                if file_version != expected_version:
                    return {
                        'valid': False,
                        'error': f'Version mismatch: expected {expected_version}, found {file_version}'
                    }
                
                # Check plugin name
                if plugin_data.get('name') != 'PowerDeck':
                    return {
                        'valid': False,
                        'error': f'Invalid plugin name: {plugin_data.get("name")}'
                    }
                
            except Exception as e:
                return {
                    'valid': False,
                    'error': f'Invalid plugin.json: {str(e)}'
                }
            
            # Check main.py is valid Python
            try:
                main_py_path = os.path.join(source_dir, 'main.py')
                with open(main_py_path, 'r') as f:
                    content = f.read()
                
                # Basic validation - check for PowerDeck class
                if 'class Plugin' not in content:
                    return {
                        'valid': False,
                        'error': 'main.py does not contain Plugin class'
                    }
                
            except Exception as e:
                return {
                    'valid': False,
                    'error': f'Invalid main.py: {str(e)}'
                }
            
            return {
                'valid': True,
                'version': expected_version,
                'plugin_info': plugin_data,
                'file_count': len(os.listdir(source_dir))
            }
            
        except Exception as e:
            return {
                'valid': False,
                'error': str(e)
            }

    async def _cleanup_staged_update(self):
        """Clean up any existing staged update"""
        try:
            if os.path.exists(self.update_staging_dir):
                import shutil
                shutil.rmtree(self.update_staging_dir)
                decky.logger.info("Cleaned up previous staged update")
        except Exception as e:
            decky.logger.warning(f"Failed to cleanup staged update: {e}")

    async def install_staged_update(self) -> dict:
        """Install a previously staged update - Plugin class method"""
        try:
            if not self.staged_update_info or not self.staged_update_path:
                return {
                    'success': False,
                    'error': 'No update staged for installation'
                }
            
            if not os.path.exists(self.staged_update_path):
                return {
                    'success': False,
                    'error': 'Staged update files not found'
                }
            
            version = self.staged_update_info['version']
            source_dir = self.staged_update_path
            
            decky.logger.info(f"Installing staged update v{version}")
            decky.logger.info(f"Source directory: {source_dir}")
            
            # Get current plugin directory
            current_plugin_dir = "/home/deck/homebrew/plugins/PowerDeck"
            backup_base_dir = "/home/deck/plugin_backups"
            backup_dir = f"{backup_base_dir}/PowerDeck.backup.{await self.get_current_version()}"
            
            decky.logger.info(f"Current plugin directory: {current_plugin_dir}")
            decky.logger.info(f"Backup directory: {backup_dir}")
            
            # Ensure backup base directory exists
            os.makedirs(backup_base_dir, exist_ok=True)
            
            # Create backup before installation
            try:
                if os.path.exists(current_plugin_dir):
                    import shutil
                    
                    # Remove existing backup if it exists
                    if os.path.exists(backup_dir):
                        decky.logger.info(f"Removing existing backup at {backup_dir}")
                        shutil.rmtree(backup_dir)
                    
                    shutil.copytree(current_plugin_dir, backup_dir)
                    decky.logger.info(f"Created backup at {backup_dir}")
            except Exception as e:
                decky.logger.error(f"Failed to create backup: {e}")
                return {
                    'success': False,
                    'error': f'Backup creation failed: {str(e)}'
                }
            
            # Note: We cannot stop/start plugin_loader separately as it kills the calling process
            # The plugin_loader will be restarted after file installation
            
            # Replace plugin files
            try:
                import shutil
                
                # Remove current plugin directory
                if os.path.exists(current_plugin_dir):
                    shutil.rmtree(current_plugin_dir)
                
                # Copy staged update to plugin directory
                shutil.copytree(source_dir, current_plugin_dir)
                
                # Set proper permissions
                subprocess.run(['chown', '-R', 'deck:deck', current_plugin_dir], check=True)
                
                decky.logger.info(f"Installed PowerDeck v{version} successfully")
                
            except Exception as e:
                decky.logger.error(f"Failed to install update: {e}")
                
                # Restore backup on failure
                try:
                    if os.path.exists(backup_dir):
                        if os.path.exists(current_plugin_dir):
                            shutil.rmtree(current_plugin_dir)
                        shutil.copytree(backup_dir, current_plugin_dir)
                        decky.logger.info("Restored backup after installation failure")
                except Exception as restore_error:
                    decky.logger.error(f"Failed to restore backup: {restore_error}")
                
                return {
                    'success': False,
                    'error': f'Installation failed: {str(e)}'
                }
            
            # Clean up staged update
            await self._cleanup_staged_update()
            self.staged_update_info = None
            self.staged_update_path = None
            
            # Restart plugin loader (cannot stop/start separately)
            try:
                await self._restart_plugin_loader()
                decky.logger.info("Plugin loader restarted successfully")
                
                # Return immediately after triggering restart since this process will be killed
                return {
                    'success': True,
                    'version': version,
                    'backup_location': backup_dir,
                    'message': f'PowerDeck v{version} installation completed, plugin_loader restarting...'
                }
                
            except Exception as e:
                decky.logger.warning(f"Failed to restart plugin loader automatically: {e}")
                return {
                    'success': True,
                    'version': version,
                    'backup_location': backup_dir,
                    'message': f'PowerDeck v{version} installed, please restart plugin_loader manually'
                }
            
        except Exception as e:
            decky.logger.error(f"Failed to install staged update: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _restart_plugin_loader(self):
        """Restart plugin loader service (cannot stop/start separately)"""
        try:
            result = subprocess.run(['sudo', 'systemctl', 'restart', 'plugin_loader'], 
                                  check=True, capture_output=True, text=True)
            decky.logger.info("Plugin loader restarted via systemctl")
        except subprocess.CalledProcessError as e:
            decky.logger.error(f"Failed to restart plugin loader: {e}")
            raise

    async def get_update_status(self) -> dict:
        """Get current update status - Plugin class method"""
        try:
            current_version = await self.get_current_version()
            
            status = {
                'current_version': current_version,
                'update_available': self.update_available,
                'latest_version': self.latest_available_version,
                'staged_update': None
            }
            
            if self.staged_update_info:
                status['staged_update'] = {
                    'version': self.staged_update_info['version'],
                    'staged_at': self.staged_update_info['staged_at'],
                    'ready_to_install': os.path.exists(self.staged_update_path) if self.staged_update_path else False,
                    'validation': self.staged_update_info.get('validation', {})
                }
            
            return status
            
        except Exception as e:
            decky.logger.error(f"Failed to get update status: {e}")
            return {
                'current_version': 'unknown',
                'update_available': False,
                'error': str(e)
            }

    async def update_plugin(self) -> bool:
        """Check for updates only (deprecated - use check_for_updates) - Plugin class method"""
        decky.logger.warning("update_plugin() is deprecated, use check_for_updates() instead")
        result = await self.check_for_updates()
        return result.get('update_available', False)

    async def _download_and_install_update(self, download_url: str, version: str) -> bool:
        """Download and install plugin update"""
        try:
            import urllib.request
            import ssl
            import tempfile
            import zipfile
            import shutil
            
            decky.logger.info(f"Starting download of PowerDeck v{version}")
            
            # Create temporary directory for download
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download the update file
                update_file = os.path.join(temp_dir, f"powerdeck-{version}.zip")
                
                try:
                    decky.logger.info(f"Downloading from {download_url}...")
                    # Create SSL context that doesn't verify certificates (for compatibility)
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    
                    # Download using urlopen with SSL context, then write to file
                    with urllib.request.urlopen(download_url, timeout=30, context=ssl_context) as response:
                        with open(update_file, 'wb') as f:
                            f.write(response.read())
                    
                    decky.logger.info(f"Downloaded update to {update_file}")
                except Exception as e:
                    decky.logger.error(f"Failed to download update: {e}")
                    return False
                
                # Extract the downloaded file
                extract_dir = os.path.join(temp_dir, "extracted")
                try:
                    with zipfile.ZipFile(update_file, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    decky.logger.info(f"Extracted update to {extract_dir}")
                except Exception as e:
                    decky.logger.error(f"Failed to extract update: {e}")
                    return False
                
                # Find the PowerDeck plugin directory in the extracted files
                plugin_source_dir = os.path.join(extract_dir, "PowerDeck")
                ryzenadj_source_dir = os.path.join(extract_dir, "RyzenAdj")
                
                if not os.path.exists(plugin_source_dir):
                    decky.logger.error("Could not find PowerDeck/ directory in downloaded update")
                    return False
                
                # Verify plugin files exist
                required_files = ['main.py', 'plugin.json']
                for required_file in required_files:
                    if not os.path.exists(os.path.join(plugin_source_dir, required_file)):
                        decky.logger.error(f"Missing required file {required_file} in PowerDeck directory")
                        return False
                
                decky.logger.info(f"Found plugin source at: {plugin_source_dir}")
                
                # Get current plugin directory
                current_plugin_dir = os.path.dirname(__file__)
                decky.logger.info(f"Current plugin directory: {current_plugin_dir}")
                
                # Backup current plugin
                backup_dir = f"{current_plugin_dir}.backup.{version}"
                try:
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)
                    shutil.copytree(current_plugin_dir, backup_dir)
                    decky.logger.info(f"Created backup at: {backup_dir}")
                except Exception as e:
                    decky.logger.error(f"Failed to create backup: {e}")
                    return False
                
                # Install RyzenAdj if available (before plugin to avoid interruption)
                await self._install_ryzenadj_update(ryzenadj_source_dir)
                
                # Install the PowerDeck plugin update using rsync-like behavior
                try:
                    # Use subprocess to run rsync for atomic installation like install.sh
                    decky.logger.info("Installing PowerDeck plugin files...")
                    result = subprocess.run([
                        'sudo', 'rsync', '-av', '--delete',
                        f"{plugin_source_dir}/",  # Source with trailing slash
                        current_plugin_dir        # Destination
                    ], capture_output=True, text=True, timeout=60)
                    
                    if result.returncode != 0:
                        decky.logger.error(f"Failed to install plugin files via rsync: {result.stderr}")
                        # Fallback to manual file copying
                        await self._manual_file_installation(plugin_source_dir, current_plugin_dir)
                    else:
                        decky.logger.info("Plugin files installed successfully via rsync")
                        
                    # Set proper ownership
                    subprocess.run(['sudo', 'chown', '-R', 'deck:deck', current_plugin_dir], 
                                 capture_output=True, timeout=30)
                    
                    # Update VERSION file
                    version_file = os.path.join(current_plugin_dir, "VERSION")
                    with open(version_file, 'w') as f:
                        f.write(version)
                    decky.logger.info(f"Updated VERSION to {version}")
                    
                    # Give a moment for file operations to complete
                    import time
                    time.sleep(2)
                    
                    # Restart plugin loader to load the new version (use restart, not stop/start)
                    decky.logger.info("Restarting plugin loader to load updated plugin...")
                    try:
                        result = subprocess.run(['sudo', 'systemctl', 'restart', 'plugin_loader'], 
                                              capture_output=True, text=True, timeout=30)
                        if result.returncode == 0:
                            decky.logger.info("Plugin loader restarted successfully")
                        else:
                            decky.logger.warning(f"Plugin loader restart warning: {result.stderr}")
                            # Don't use stop/start fallback - it kills the plugin process!
                            decky.logger.info("Update installed, manual restart may be required")
                    except Exception as e:
                        decky.logger.warning(f"Could not restart plugin loader: {e}")
                        decky.logger.info("Update installed, manual restart may be required")
                    
                    decky.logger.info(f"Successfully updated PowerDeck to version {version}")
                    return True
                    
                except Exception as e:
                    decky.logger.error(f"Failed to install update: {e}")
                    
                    # Attempt to restore backup
                    try:
                        if os.path.exists(backup_dir):
                            if os.path.exists(current_plugin_dir):
                                shutil.rmtree(current_plugin_dir)
                            shutil.move(backup_dir, current_plugin_dir)
                            decky.logger.info("Restored backup after failed update")
                    except Exception as restore_error:
                        decky.logger.error(f"Failed to restore backup: {restore_error}")
                    
                    return False
        
        except Exception as e:
            decky.logger.error(f"Update installation failed: {e}")
            return False

    async def _install_ryzenadj_update(self, ryzenadj_source_dir: str) -> bool:
        """Install RyzenAdj binary if available in update package"""
        ryzenadj_binary = os.path.join(ryzenadj_source_dir, "build", "ryzenadj")
        
        if not os.path.exists(ryzenadj_binary):
            decky.logger.info("No RyzenAdj binary found in update package")
            return True  # Not an error, just not included
        
        decky.logger.info("Installing RyzenAdj binary from update package...")
        
        # Check if filesystem needs unlocking (SteamOS)
        filesystem_unlocked = False
        try:
            # Check if we're on SteamOS with read-only filesystem
            mount_result = subprocess.run(['mount'], capture_output=True, text=True, timeout=10)
            if mount_result.returncode == 0 and "on / type" in mount_result.stdout and "ro," in mount_result.stdout:
                # Try to unlock filesystem for /opt installation
                unlock_result = subprocess.run(['sudo', 'steamos-readonly', 'disable'], 
                                             capture_output=True, text=True, timeout=30)
                if unlock_result.returncode == 0:
                    filesystem_unlocked = True
                    decky.logger.info("Unlocked SteamOS filesystem for RyzenAdj installation")
        except Exception as e:
            decky.logger.warning(f"Could not check/unlock filesystem: {e}")
        
        try:
            # Create target directory
            target_dir = "/opt/ryzenadj/bin"
            target_path = os.path.join(target_dir, "ryzenadj")
            
            subprocess.run(['sudo', 'mkdir', '-p', target_dir], check=True, timeout=30)
            subprocess.run(['sudo', 'cp', ryzenadj_binary, target_path], check=True, timeout=30)
            subprocess.run(['sudo', 'chmod', '+x', target_path], check=True, timeout=30)
            
            decky.logger.info(f"RyzenAdj installed successfully at: {target_path}")
            return True
            
        except Exception as e:
            decky.logger.error(f"Failed to install RyzenAdj: {e}")
            return False
        finally:
            # Re-lock filesystem if we unlocked it
            if filesystem_unlocked:
                try:
                    subprocess.run(['sudo', 'steamos-readonly', 'enable'], timeout=30)
                    decky.logger.info("Re-locked SteamOS filesystem")
                except Exception as e:
                    decky.logger.warning(f"Could not re-lock filesystem: {e}")

    async def _manual_file_installation(self, plugin_source_dir: str, current_plugin_dir: str) -> None:
        """Fallback manual file installation if rsync fails"""
        decky.logger.info("Using manual file installation as rsync fallback...")
        
        # Copy essential files
        essential_files = ['main.py', 'plugin.json']
        essential_dirs = ['py_modules', 'dist']
        
        for file_name in essential_files:
            src_file = os.path.join(plugin_source_dir, file_name)
            dst_file = os.path.join(current_plugin_dir, file_name)
            if os.path.exists(src_file):
                shutil.copy2(src_file, dst_file)
                decky.logger.info(f"Updated {file_name}")
        
        for dir_name in essential_dirs:
            src_dir = os.path.join(plugin_source_dir, dir_name)
            dst_dir = os.path.join(current_plugin_dir, dir_name)
            if os.path.exists(src_dir):
                if os.path.exists(dst_dir):
                    shutil.rmtree(dst_dir)
                shutil.copytree(src_dir, dst_dir)
                decky.logger.info(f"Updated {dir_name}/")

    async def background_update_checker(self):
        """Background task to periodically check for updates"""
        try:
            while True:
                try:
                    # Wait for update check interval (4 hours)
                    await asyncio.sleep(self.update_check_interval)
                    
                    # Skip if too soon since last check
                    if self.last_update_check:
                        import time
                        time_since_last = time.time() - self.last_update_check
                        if time_since_last < self.update_check_interval:
                            continue
                    
                    decky.logger.info("Background update check starting...")
                    
                    try:
                        # Non-blocking version check with timeout
                        current_version = await asyncio.wait_for(
                            self.get_current_version(), 
                            timeout=10.0
                        )
                        latest_version = await asyncio.wait_for(
                            self.get_latest_version(), 
                            timeout=30.0
                        )
                        
                        import time
                        self.last_update_check = time.time()
                        
                        # Check if update available
                        if current_version != latest_version:
                            self.update_available = True
                            self.latest_available_version = latest_version
                            decky.logger.info(f"Background update check: Update available {current_version} -> {latest_version}")
                        else:
                            self.update_available = False
                            self.latest_available_version = None
                            decky.logger.info(f"Background update check: Up to date ({current_version})")
                        
                    except asyncio.TimeoutError:
                        decky.logger.warning("Background update check timed out")
                    except Exception as check_error:
                        decky.logger.error(f"Background update check error: {check_error}")
                        
                except asyncio.CancelledError:
                    decky.logger.info("Background update checker cancelled")
                    break
                except Exception as e:
                    decky.logger.error(f"Background update checker error: {e}")
                    # Continue running despite errors
                    await asyncio.sleep(300)  # Wait 5 minutes before retry
                    
        except Exception as e:
            decky.logger.error(f"Background update checker failed: {e}")

    async def get_update_status(self) -> Dict[str, Any]:
        """Get background update check status for frontend"""
        try:
            import time
            
            status = {
                "update_available": self.update_available,
                "latest_version": self.latest_available_version,
                "last_check": self.last_update_check,
                "check_interval_hours": self.update_check_interval / 3600
            }
            
            if self.last_update_check:
                time_since_check = time.time() - self.last_update_check
                status["hours_since_last_check"] = time_since_check / 3600
            else:
                status["hours_since_last_check"] = None
            
            return status
        except Exception as e:
            decky.logger.error(f"Failed to get update status: {e}")
            return {
                "update_available": False,
                "latest_version": None,
                "last_check": None,
                "check_interval_hours": 4,
                "hours_since_last_check": None
            }

    # Redux-compatible backend functions
    async def save_profile_settings(self, ac_profile: Dict[str, Any], battery_profile: Dict[str, Any]) -> bool:
        """Save profile settings to persistent storage"""
        try:
            settings_dir = os.path.join(os.path.dirname(__file__), "settings")
            os.makedirs(settings_dir, exist_ok=True)
            
            # Save AC profile
            ac_path = os.path.join(settings_dir, "ac_profile.json")
            with open(ac_path, 'w') as f:
                json.dump(ac_profile, f, indent=2)
            
            # Save Battery profile  
            battery_path = os.path.join(settings_dir, "battery_profile.json")
            with open(battery_path, 'w') as f:
                json.dump(battery_profile, f, indent=2)
            
            decky.logger.info("Profile settings saved successfully")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to save profile settings: {e}")
            return False

    async def load_profile_settings(self) -> Optional[Dict[str, Any]]:
        """Load saved profile settings"""
        try:
            settings_dir = os.path.join(os.path.dirname(__file__), "settings")
            ac_path = os.path.join(settings_dir, "ac_profile.json") 
            battery_path = os.path.join(settings_dir, "battery_profile.json")
            
            settings = {}
            
            # Load AC profile if exists
            if os.path.exists(ac_path):
                with open(ac_path, 'r') as f:
                    settings["acProfile"] = json.load(f)
            
            # Load Battery profile if exists
            if os.path.exists(battery_path):
                with open(battery_path, 'r') as f:
                    settings["batteryProfile"] = json.load(f)
            
            if settings:
                decky.logger.info("Profile settings loaded successfully")
                return settings
            else:
                decky.logger.info("No saved profile settings found")
                return None
        except Exception as e:
            decky.logger.error(f"Failed to load profile settings: {e}")
            return None

    async def apply_current_profile(self) -> bool:
        """Apply the current profile settings"""
        try:
            # This would be called by Redux middleware after profile changes
            # For now, we'll use the existing profile application logic
            current_profile = await self.get_current_profile()
            success = await self.apply_profile(current_profile)
            
            if success:
                decky.logger.info(f"Applied current profile: {current_profile}")
            else:
                decky.logger.error(f"Failed to apply current profile: {current_profile}")
            
            return success
        except Exception as e:
            decky.logger.error(f"Failed to apply current profile: {e}")
            return False

    async def check_ac_power(self) -> bool:
        """Check AC power status for Redux integration"""
        try:
            # Use existing AC power detection
            return await self.get_ac_power_status()
        except Exception as e:
            decky.logger.error(f"Failed to check AC power: {e}")
            return True  # Default to AC power on error

    async def debug_device_info(self) -> Dict[str, Any]:
        """Debug method to check device info values"""
        decky.logger.info("=== DEBUG DEVICE INFO ===")
        device_info = await self.get_device_info()
        decky.logger.info(f"Device info supports_gpu_control: {device_info.get('supports_gpu_control')}")
        decky.logger.info(f"Device info keys: {list(device_info.keys())}")
        return device_info

    async def set_fan_profile(self, profile: str) -> bool:
        """Set fan profile - Plugin class method"""
        try:
            result = await self.set_fan_cooling_profile(profile)
            return result.get("success", False)
        except Exception as e:
            decky.logger.error(f"Failed to set fan profile: {e}")
            return False

    async def set_cpu_frequency_limits(self, min_freq_khz: Optional[int] = None, max_freq_khz: Optional[int] = None) -> bool:
        """Set CPU frequency limits - Plugin class method"""
        try:
            if self.cpu_manager:
                success = self.cpu_manager.set_cpu_frequency_limits(min_freq_khz, max_freq_khz)
            else:
                from cpu_manager import get_cpu_manager
                cpu_manager = get_cpu_manager()
                success = cpu_manager.set_cpu_frequency_limits(min_freq_khz, max_freq_khz)
            
            if success:
                limits_str = []
                if min_freq_khz is not None:
                    limits_str.append(f"min: {min_freq_khz//1000}MHz")
                if max_freq_khz is not None:
                    limits_str.append(f"max: {max_freq_khz//1000}MHz")
                decky.logger.info(f"SET_CPU_FREQUENCY_LIMITS: CPU frequency limits set ({', '.join(limits_str)})")
            else:
                decky.logger.error("SET_CPU_FREQUENCY_LIMITS: Failed to set CPU frequency limits")
            
            return success
        except Exception as e:
            decky.logger.error(f"Failed to set CPU frequency limits: {e}")
            return False
    
    async def reset_cpu_frequency_limits(self) -> bool:
        """Reset CPU frequency limits to hardware defaults - Plugin class method"""
        try:
            if self.cpu_manager:
                success = self.cpu_manager.reset_cpu_frequency_limits()
            else:
                from cpu_manager import get_cpu_manager
                cpu_manager = get_cpu_manager()
                success = cpu_manager.reset_cpu_frequency_limits()
            
            if success:
                decky.logger.info("RESET_CPU_FREQUENCY_LIMITS: CPU frequency limits reset to hardware defaults")
            else:
                decky.logger.error("RESET_CPU_FREQUENCY_LIMITS: Failed to reset CPU frequency limits")
            
            return success
        except Exception as e:
            decky.logger.error(f"Failed to reset CPU frequency limits: {e}")
            return False

    async def set_governor(self, governor: str) -> bool:
        """Set CPU governor - Plugin class method"""
        try:
            return await self.set_power_governor(governor)
        except Exception as e:
            decky.logger.error(f"Failed to set governor: {e}")
            return False

    async def set_game_profile(self, game_id: str, profile_data: Dict[str, Any]) -> bool:
        """Save a profile for a specific game/profile ID - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: set_game_profile({game_id})")
        decky.logger.info(f"Plugin.set_game_profile called with: {profile_data}")
        try:
            # Add the game_id to the profile data
            profile_with_id = dict(profile_data)
            profile_with_id["gameId"] = game_id
            decky.logger.info(f"Calling self.save_profile with: {profile_with_id}")
            success = await self.save_profile(profile_with_id)
            decky.logger.info(f"Plugin.set_game_profile: Saved profile for {game_id}, success: {success}")
            return success
        except Exception as e:
            decky.logger.error(f"Plugin.set_game_profile failed for {game_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def get_game_profile(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Load a profile for a specific game/profile ID - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_game_profile({game_id})")
        try:
            decky.logger.info(f"Calling self.load_profile for: {game_id}")
            profile = await self.load_profile(game_id)
            if profile:
                decky.logger.info(f"Plugin.get_game_profile: Loaded profile for {game_id}: {profile}")
                return profile
            else:
                decky.logger.info(f"Plugin.get_game_profile: No profile found for {game_id}")
                return None
        except Exception as e:
            decky.logger.error(f"Plugin.get_game_profile failed for {game_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # Enhanced Sleep/Wake Management API
    async def get_sleep_wake_diagnostics(self) -> Dict[str, Any]:
        """Get sleep/wake system diagnostics - Plugin class method"""
        try:
            if self.sleep_wake_manager:
                # Return basic diagnostics from the new manager
                diagnostics = {
                    'enhanced_manager_available': True,
                    'monitoring_active': self.sleep_wake_manager.monitoring_active,
                    'last_suspend_count': self.sleep_wake_manager.last_suspend_count,
                    'manager_type': 'event_driven_v2'
                }
                decky.logger.info(f"Sleep/wake diagnostics: {diagnostics}")
                return diagnostics
            else:
                return {
                    'enhanced_manager_available': False,
                    'fallback_monitoring': True,
                    'dbus_available': False
                }
        except Exception as e:
            decky.logger.error(f"Failed to get sleep/wake diagnostics: {e}")
            return {'error': str(e)}
    
    async def get_recent_sleep_wake_events(self, hours: int = 24) -> list:
        """Get recent sleep/wake events - Plugin class method"""
        try:
            if self.sleep_wake_manager:
                # Load events from the log file
                import json
                events_file = "/tmp/powerdeck_sleep_wake_events.json"
                events = []
                
                if os.path.exists(events_file):
                    try:
                        with open(events_file, 'r') as f:
                            events = json.load(f)
                    except:
                        events = []
                
                # Filter events by timeframe
                import time
                cutoff_time = time.time() - (hours * 3600)
                recent_events = [e for e in events if e.get('timestamp', 0) > cutoff_time]
                
                decky.logger.info(f"Retrieved {len(recent_events)} sleep/wake events from last {hours} hours")
                return recent_events
            else:
                return []
        except Exception as e:
            decky.logger.error(f"Failed to get recent sleep/wake events: {e}")
            return []
    
    async def force_wake_state_restoration(self) -> bool:
        """Manually trigger wake state restoration - Plugin class method"""
        try:
            if self.sleep_wake_manager:
                decky.logger.info("Manually triggering wake state restoration")
                await self.sleep_wake_manager._handle_wake_event("manual")
                return True
            else:
                decky.logger.info("Enhanced sleep/wake manager not available, applying current profile")
                success = await self.apply_profile(self.current_profile)
                return success
        except Exception as e:
            decky.logger.error(f"Failed to force wake state restoration: {e}")
            return False
    
    async def monitor_system_wake(self):
        """Monitor system wake events and reapply settings"""
        try:
            decky.logger.info("Started wake from sleep monitoring")
            last_uptime = None
            
            while True:
                try:
                    # Check system uptime to detect sleep/wake cycles
                    with open('/proc/uptime', 'r') as f:
                        current_uptime = float(f.read().split()[0])
                    
                    # If this is not the first check and uptime decreased, system was suspended
                    if last_uptime is not None and current_uptime < last_uptime:
                        decky.logger.info("System wake detected - reapplying power profile")
                        
                        # Wait a moment for system to stabilize after wake
                        await asyncio.sleep(3)
                        
                        # Reapply current profile to restore all settings
                        try:
                            success = await self.apply_profile(self.current_profile)
                            if success:
                                decky.logger.info("Power profile reapplied after wake")
                            else:
                                decky.logger.warning("Failed to reapply profile after wake")
                        except Exception as e:
                            decky.logger.error(f"Error reapplying profile after wake: {e}")
                    
                    last_uptime = current_uptime
                    
                    # Check every 30 seconds
                    await asyncio.sleep(30)
                    
                except Exception as e:
                    decky.logger.error(f"Wake monitoring error: {e}")
                    await asyncio.sleep(60)  # Longer delay on error
                    
        except Exception as e:
            decky.logger.error(f"Wake monitoring failed: {e}")

    # ROG Ally Plugin Class Methods (corresponding to frontend callable functions)
    async def get_rog_ally_device_info(self) -> Dict[str, Any]:
        """Get ROG Ally device information - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_device_info()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_device_info'):
                info = self.device_controller.get_device_info()
                decky.logger.info(f"Plugin.get_rog_ally_device_info: {info}")
                return info
            else:
                decky.logger.warning("ROG Ally controller not available")
                return {}
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_device_info failed: {e}")
            return {}

    async def get_rog_ally_power_limits(self) -> Dict[str, Optional[int]]:
        """Get ROG Ally power limits - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_power_limits()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_power_limits'):
                limits = self.device_controller.get_power_limits()
                decky.logger.info(f"Plugin.get_rog_ally_power_limits: {limits}")
                return limits
            else:
                return {"fast_limit": None, "sustained_limit": None, "stapm_limit": None}
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_power_limits failed: {e}")
            return {"fast_limit": None, "sustained_limit": None, "stapm_limit": None}

    async def get_rog_ally_platform_profile(self) -> Optional[str]:
        """Get ROG Ally platform profile - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_platform_profile()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_platform_profile'):
                profile = self.device_controller.get_platform_profile()
                decky.logger.info(f"Plugin.get_rog_ally_platform_profile: {profile}")
                return profile
            else:
                return None
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_platform_profile failed: {e}")
            return None

    async def get_rog_ally_thermal_throttle_policy(self) -> Optional[int]:
        """Get ROG Ally thermal throttle policy - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_thermal_throttle_policy()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_thermal_throttle_policy'):
                policy = self.device_controller.get_thermal_throttle_policy()
                decky.logger.info(f"Plugin.get_rog_ally_thermal_throttle_policy: {policy}")
                return policy
            else:
                return None
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_thermal_throttle_policy failed: {e}")
            return None

    async def get_rog_ally_fan_status(self) -> Dict[str, Any]:
        """Get ROG Ally fan status - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_fan_status()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_fan_status'):
                status = self.device_controller.get_fan_status()
                decky.logger.info(f"Plugin.get_rog_ally_fan_status: {status}")
                return status
            else:
                return { 
                    "cpu_fan": {"speed": None, "mode": 2, "label": "cpu_fan"}, 
                    "gpu_fan": {"speed": None, "mode": 0, "label": "gpu_fan"} 
                }
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_fan_status failed: {e}")
            return { 
                "cpu_fan": {"speed": None, "mode": 2, "label": "cpu_fan"}, 
                "gpu_fan": {"speed": None, "mode": 0, "label": "gpu_fan"} 
            }

    async def get_rog_ally_battery_charge_limit(self) -> Optional[int]:
        """Get ROG Ally battery charge limit - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_battery_charge_limit()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_battery_charge_limit'):
                limit = self.device_controller.get_battery_charge_limit()
                decky.logger.info(f"Plugin.get_rog_ally_battery_charge_limit: {limit}")
                return limit
            else:
                return None
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_battery_charge_limit failed: {e}")
            return None

    async def get_rog_ally_mcu_powersave(self) -> Optional[bool]:
        """Get ROG Ally MCU powersave status - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_rog_ally_mcu_powersave()")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'get_mcu_powersave'):
                status = self.device_controller.get_mcu_powersave()
                decky.logger.info(f"Plugin.get_rog_ally_mcu_powersave: {status}")
                return status
            else:
                return None
        except Exception as e:
            decky.logger.error(f"Plugin.get_rog_ally_mcu_powersave failed: {e}")
            return None

    async def set_rog_ally_mcu_powersave(self, enabled: bool) -> bool:
        """Set ROG Ally MCU powersave mode - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: set_rog_ally_mcu_powersave({enabled})")
        try:
            if hasattr(self, 'device_controller') and hasattr(self.device_controller, 'set_mcu_powersave'):
                result = self.device_controller.set_mcu_powersave(enabled)
                decky.logger.info(f"Plugin.set_rog_ally_mcu_powersave: {result}")
                return result
            else:
                return False
        except Exception as e:
            decky.logger.error(f"Plugin.set_rog_ally_mcu_powersave failed: {e}")
            return False

    # =========================================================================
    # InputPlumber Integration Methods
    # =========================================================================

    async def get_inputplumber_status(self) -> Dict[str, Any]:
        """Get InputPlumber availability and capabilities - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_inputplumber_status()")
        try:
            if not device_support_available:
                return {
                    "available": False,
                    "error": "Device support not available"
                }
            
            inputplumber_mgr = get_inputplumber_manager()
            capabilities = inputplumber_mgr.get_capabilities()
            current_mode = inputplumber_mgr.get_current_mode()
            
            result = {
                "available": capabilities.get("available", False),
                "dbus_mode": capabilities.get("dbus_mode", False),
                "current_mode": current_mode,
                "supported_modes": capabilities.get("supported_modes", []),
                "device": capabilities.get("device", "Unknown")
            }
            
            decky.logger.info(f"Plugin.get_inputplumber_status: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Plugin.get_inputplumber_status failed: {e}")
            return {
                "available": False,
                "error": str(e)
            }

    async def get_inputplumber_modes(self) -> List[Dict[str, str]]:
        """Get list of supported InputPlumber controller modes - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_inputplumber_modes()")
        try:
            if not device_support_available:
                return []
            
            inputplumber_mgr = get_inputplumber_manager()
            modes = inputplumber_mgr.get_supported_modes()
            
            decky.logger.info(f"Plugin.get_inputplumber_modes: {len(modes)} modes")
            return modes
        except Exception as e:
            decky.logger.error(f"Plugin.get_inputplumber_modes failed: {e}")
            return []

    async def set_inputplumber_mode(self, mode: str) -> bool:
        """Set InputPlumber controller mode - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: set_inputplumber_mode({mode})")
        try:
            if not device_support_available:
                decky.logger.warning("Device support not available, cannot set InputPlumber mode")
                return False
            
            inputplumber_mgr = get_inputplumber_manager()
            
            # Validate mode
            if not inputplumber_mgr.validate_mode(mode):
                decky.logger.error(f"Invalid controller mode: {mode}")
                return False
            
            # Set mode
            success = inputplumber_mgr.set_controller_mode(mode)
            
            if success:
                decky.logger.info(f"Plugin.set_inputplumber_mode: Successfully set to {mode}")
            else:
                decky.logger.error(f"Plugin.set_inputplumber_mode: Failed to set mode {mode}")
            
            return success
        except Exception as e:
            decky.logger.error(f"Plugin.set_inputplumber_mode failed: {e}")
            return False

    async def get_inputplumber_profile_for_game(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get InputPlumber settings for a specific game profile - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: get_inputplumber_profile_for_game({game_id})")
        try:
            if not self.profile_manager:
                return None
            
            # Load game profile
            profile = await self.profile_manager.load_profile(game_id)
            
            if profile and "inputplumber" in profile:
                return profile["inputplumber"]
            
            return None
        except Exception as e:
            decky.logger.error(f"Plugin.get_inputplumber_profile_for_game failed: {e}")
            return None

    async def save_inputplumber_profile_for_game(self, game_id: str, inputplumber_settings: Dict[str, Any]) -> bool:
        """Save InputPlumber settings to a game profile - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: save_inputplumber_profile_for_game({game_id})")
        try:
            if not self.profile_manager:
                return False
            
            # Load existing profile or create new
            profile = await self.profile_manager.load_profile(game_id) or {}
            
            # Update InputPlumber settings
            profile["inputplumber"] = inputplumber_settings
            
            # Save profile
            success = await self.profile_manager.save_profile(game_id, profile)
            
            decky.logger.info(f"Plugin.save_inputplumber_profile_for_game: {success}")
            return success
        except Exception as e:
            decky.logger.error(f"Plugin.save_inputplumber_profile_for_game failed: {e}")
            return False

    async def apply_inputplumber_profile_for_game(self, game_id: str) -> bool:
        """Apply InputPlumber settings from game profile - Plugin class method"""
        decky.logger.info(f"PLUGIN METHOD: apply_inputplumber_profile_for_game({game_id})")
        try:
            # Check if per-game profiles are enabled
            if not self.enable_per_game_profiles:
                decky.logger.info("Per-game profiles disabled, using default profile")
                game_id = "default"
            
            # Get profile settings
            inputplumber_settings = await self.get_inputplumber_profile_for_game(game_id)
            
            if not inputplumber_settings:
                decky.logger.info(f"No InputPlumber settings for game {game_id}")
                return False
            
            # Apply controller mode
            mode = inputplumber_settings.get("controller_mode")
            if mode:
                success = await self.set_inputplumber_mode(mode)
                decky.logger.info(f"Applied InputPlumber mode {mode}: {success}")
                return success
            
            return False
        except Exception as e:
            decky.logger.error(f"Plugin.apply_inputplumber_profile_for_game failed: {e}")
            return False

# Global plugin instance
plugin = Plugin()

# Global functions for frontend calls
async def get_current_game_info():
    """Global function called by frontend"""
    return await plugin.get_current_game_info()

async def get_device_info():
    """Global function called by frontend"""  
    decky.logger.info(f"FRONTEND CALL: get_device_info()")
    result = await plugin.get_device_info()
    decky.logger.info(f"DEVICE INFO RETURNED TO FRONTEND: {result}")
    decky.logger.info(f"GPU FIELDS IN RESPONSE: min_gpu_freq={result.get('min_gpu_freq')}, max_gpu_freq={result.get('max_gpu_freq')}")
    return result

async def get_ac_power_status():
    """Global function called by frontend"""
    decky.logger.info(f"FRONTEND CALL: get_ac_power_status()")
    result = await plugin.get_ac_power_status()
    decky.logger.info(f"AC Power Status: {result}")
    return result

async def set_tdp(tdp: int, save_to_profile: bool = False):
    """Global function called by frontend"""
    decky.logger.info(f"FRONTEND CALL: set_tdp({tdp})")
    return await plugin.set_tdp(tdp, save_to_profile)

async def get_current_tdp():
    """Global function called by frontend"""
    return await plugin.get_current_tdp()

async def set_cpu_boost(enabled: bool):
    """Global function called by frontend"""
    return await plugin.set_cpu_boost(enabled)

async def get_current_cpu_boost():
    """Global function called by frontend"""
    return await plugin.get_current_cpu_boost()

async def get_per_game_profiles_enabled():
    """Global function called by frontend"""
    return await plugin.get_per_game_profiles_enabled()

async def set_per_game_profiles_enabled(enabled: bool):
    """Global function called by frontend"""
    return await plugin.set_per_game_profiles_enabled(enabled)

async def get_rog_ally_native_tdp_enabled():
    """Global function called by frontend"""
    return await plugin.get_rog_ally_native_tdp_enabled()

async def set_rog_ally_native_tdp_enabled(enabled: bool):
    """Global function called by frontend"""
    return await plugin.set_rog_ally_native_tdp_enabled(enabled)

async def is_rog_ally_device():
    """Global function called by frontend"""
    return await plugin.is_rog_ally_device()

async def get_tdp_control_mode():
    """Global function called by frontend"""
    return await plugin.get_tdp_control_mode()

async def get_current_profile():
    """Global function called by frontend"""
    import traceback
    stack = traceback.format_stack()
    decky.logger.info("GET_CURRENT_PROFILE CALLED BY FRONTEND")
    decky.logger.info(f"Call stack (last 3 frames):")
    for i, frame in enumerate(stack[-3:]):
        decky.logger.info(f"  Frame {i}: {frame.strip()}")
    
    result = await plugin.get_current_profile()
    decky.logger.info(f"RETURNING PROFILE TO FRONTEND: TDP={result.get('tdp', 'NOT_SET')}, cpuBoost={result.get('cpuBoost', 'NOT_SET')}")
    return result

async def save_profile(profile_data):
    """Global function called by frontend"""
    import traceback
    stack = traceback.format_stack()
    decky.logger.info("SAVE_PROFILE CALLED BY FRONTEND")
    decky.logger.info(f"Profile data to save: TDP={profile_data.get('tdp', 'NOT_SET')}, cpuBoost={profile_data.get('cpuBoost', 'NOT_SET')}")
    decky.logger.info(f"Call stack (last 3 frames):")
    for i, frame in enumerate(stack[-3:]):
        decky.logger.info(f"  Frame {i}: {frame.strip()}")
    
    result = await plugin.save_profile(profile_data)
    decky.logger.info(f"SAVE_PROFILE RESULT: {result}")
    return result

async def set_cpu_cores(cores: int):
    """Global function called by frontend"""
    return await plugin.set_cpu_cores(cores)

async def get_current_cpu_cores():
    """Global function called by frontend"""
    return await plugin.get_current_cpu_cores()

async def set_power_governor(governor: str):
    """Global function called by frontend"""
    return await plugin.set_power_governor(governor)

async def get_current_power_governor():
    """Global function called by frontend"""
    return await plugin.get_current_power_governor()

async def set_smt(enabled: bool):
    """Global function called by frontend"""
    return await plugin.set_smt(enabled)

async def get_current_smt_status():
    """Global function called by frontend"""
    return await plugin.get_current_smt_status()

async def set_epp(epp: str):
    """Global function called by frontend"""
    return await plugin.set_epp(epp)

async def get_current_epp():
    """Global function called by frontend"""
    return await plugin.get_current_epp()

async def set_cpu_frequency_limits(min_freq_khz: int = None, max_freq_khz: int = None):
    """Global function called by frontend"""
    return await plugin.set_cpu_frequency_limits(min_freq_khz, max_freq_khz)

async def reset_cpu_frequency_limits():
    """Global function called by frontend"""
    return await plugin.reset_cpu_frequency_limits()

async def get_cpu_frequency_info():
    """Global function called by frontend"""
    try:
        if plugin.cpu_manager:
            info = {
                'frequency_range': plugin.cpu_manager.get_cpu_frequency_range(),
                'current_frequencies': plugin.cpu_manager.get_current_cpu_frequencies(),
                'frequency_limits': plugin.cpu_manager.get_cpu_frequency_limits()
            }
            return info
        else:
            from cpu_manager import get_cpu_manager
            cpu_manager = get_cpu_manager()
            info = {
                'frequency_range': cpu_manager.get_cpu_frequency_range(),
                'current_frequencies': cpu_manager.get_current_cpu_frequencies(),
                'frequency_limits': cpu_manager.get_cpu_frequency_limits()
            }
            return info
    except Exception as e:
        decky.logger.error(f"Failed to get CPU frequency info: {e}")
        return None

async def debug_frontend_state(ui_state: bool, ac_power: bool, message: str):
    """Global function for frontend debugging"""
    decky.logger.info(f"FRONTEND DEBUG: {message} | UI State: {ui_state} | AC Power: {ac_power}")
    return True

async def get_available_fan_profiles():
    """Global function called by frontend"""
    if device_support_available:
        # Return profiles that match steamfork_fan_controller
        return ["auto", "quiet", "moderate", "aggressive"]  
    else:
        return ["auto", "quiet", "moderate", "aggressive"]

async def set_fan_profile(profile: str):
    """Global function called by frontend"""
    try:
        result = await plugin.set_fan_cooling_profile(profile)
        return result.get("success", False)
    except Exception as e:
        decky.logger.error(f"Failed to set fan profile: {e}")
        return False

async def get_fan_profile():
    """Global function called by frontend"""
    try:
        info = await plugin.get_fan_control_info()
        return info.get("current_profile", "balanced")
    except Exception as e:
        decky.logger.error(f"Failed to get fan profile: {e}")
        return "balanced"

async def set_governor(governor: str):
    """Global function called by frontend - wrapper for set_power_governor"""
    return await plugin.set_power_governor(governor)

async def get_current_governor():
    """Global function called by frontend"""
    return await plugin.get_current_power_governor()

async def get_available_governors():
    """Global function called by frontend"""
    return await plugin.get_available_governors()

async def get_tdp_limits():
    """Global function called by frontend - get TDP limits using processor database"""
    device_info = await plugin.get_device_info()
    return {
        "min": device_info.get("tdp_min", 4),      # Hard-coded minimum (4W)
        "max": device_info.get("tdp_max", 25)      # Database maximum (ctdp_max)
    }

async def get_hybrid_tdp_limits():
    """Global function called by frontend - get TDP limits using hybrid sysfs/database approach"""
    return await plugin.get_hybrid_tdp_limits()

async def get_sysfs_capabilities():
    """Global function called by frontend - get sysfs power capabilities"""
    if sysfs_support_available:
        try:
            return get_sysfs_power_capabilities()
        except Exception as e:
            decky.logger.error(f"Failed to get sysfs capabilities: {e}")
            return {"detected": False, "error": str(e)}
    return {"detected": False, "error": "Sysfs support not available"}

async def get_default_tdp():
    """Global function called by frontend - get default TDP from processor database"""
    device_info = await plugin.get_device_info()
    return device_info.get("tdp_default", 15)  # Database default (ctdp_min)

async def set_gpu_mode(mode: str):
    """Global function called by frontend"""
    return await plugin.set_gpu_mode(mode)

async def get_gpu_mode():
    """Global function called by frontend"""
    return await plugin.get_current_gpu_mode()

async def set_gpu_frequency(min_freq: int, max_freq: int):
    """Global function called by frontend"""
    return await plugin.set_gpu_frequency(min_freq, max_freq)

async def get_gpu_frequency():
    """Global function called by frontend"""
    return await plugin.get_current_gpu_frequency()

# Game Profile Management Functions - CALLABLE FUNCTIONS FOR FRONTEND
async def set_game_profile(game_id: str, profile_data):
    """Save a profile for a specific game/profile ID (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_game_profile({game_id})")
    decky.logger.info(f"Global set_game_profile called with: {profile_data}")
    if plugin:
        try:
            success = await plugin.set_game_profile(game_id, profile_data)
            decky.logger.info(f"Global set_game_profile: Result for {game_id}: {success}")
            return success
        except Exception as e:
            decky.logger.error(f"Global set_game_profile failed for {game_id}: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        decky.logger.error(f"Global set_game_profile: plugin is None!")
    return False

async def get_game_profile(game_id: str):
    """Load a profile for a specific game/profile ID (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: get_game_profile({game_id})")
    if plugin:
        try:
            profile = await plugin.get_game_profile(game_id)
            if profile:
                decky.logger.info(f"Global get_game_profile: Loaded profile for {game_id}: {profile}")
                return profile
            else:
                decky.logger.info(f"Global get_game_profile: No profile found for {game_id}")
                return None
        except Exception as e:
            decky.logger.error(f"Global get_game_profile failed for {game_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    else:
        decky.logger.error(f"Global get_game_profile: plugin is None!")
    return None

# Keep the snake_case versions for backward compatibility  
async def save_game_profile(game_id: str, profile_data):
    """Save a profile for a specific game/profile ID (backward compatibility)"""
    return await set_game_profile(game_id, profile_data)

async def load_game_profile(game_id: str):
    """Load a profile for a specific game/profile ID (backward compatibility)"""
    return await get_game_profile(game_id)

# Version and Update Functions - CALLABLE FUNCTIONS FOR FRONTEND
async def get_current_version() -> str:
    """Get current plugin version (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_current_version()")
    if plugin:
        try:
            version = await plugin.get_current_version()
            decky.logger.info(f"Global get_current_version: {version}")
            return version
        except Exception as e:
            decky.logger.error(f"Global get_current_version failed: {e}")
            return get_plugin_version()
    else:
        decky.logger.error("Global get_current_version: plugin is None!")
        return get_plugin_version()

async def get_latest_version() -> str:
    """Get latest available version from GitHub (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_latest_version()")
    if plugin:
        try:
            version = await plugin.get_latest_version()
            decky.logger.info(f"Global get_latest_version: {version}")
            return version
        except Exception as e:
            decky.logger.error(f"Global get_latest_version failed: {e}")
            return get_plugin_version()
    else:
        decky.logger.error("Global get_latest_version: plugin is None!")
        return get_plugin_version()

async def update_plugin() -> bool:
    """Check for plugin updates (frontend callable) - DEPRECATED"""
    decky.logger.info("GLOBAL FUNCTION: update_plugin() - DEPRECATED")
    decky.logger.warning("update_plugin() is deprecated, use check_for_updates() instead")
    if plugin:
        try:
            result = await plugin.update_plugin()
            decky.logger.info(f"Global update_plugin: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global update_plugin failed: {e}")
            return False
    else:
        decky.logger.error("Global update_plugin: plugin is None!")
        return False

async def check_for_updates() -> Dict[str, Any]:
    """Check for available updates (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: check_for_updates()")
    if plugin:
        try:
            result = await plugin.check_for_updates()
            decky.logger.info(f"Global check_for_updates: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global check_for_updates failed: {e}")
            return {'update_available': False, 'error': str(e)}
    else:
        decky.logger.error("Global check_for_updates: plugin is None!")
        return {'update_available': False, 'error': 'Plugin not initialized'}

async def stage_update(download_url: str, version: str) -> Dict[str, Any]:
    """Stage an update for installation (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: stage_update({version})")
    if plugin:
        try:
            result = await plugin.stage_update(download_url, version)
            decky.logger.info(f"Global stage_update: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global stage_update failed: {e}")
            return {'success': False, 'error': str(e)}
    else:
        decky.logger.error("Global stage_update: plugin is None!")
        return {'success': False, 'error': 'Plugin not initialized'}

async def install_staged_update() -> Dict[str, Any]:
    """Install a staged update (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: install_staged_update()")
    if plugin:
        try:
            result = await plugin.install_staged_update()
            decky.logger.info(f"Global install_staged_update: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global install_staged_update failed: {e}")
            return {'success': False, 'error': str(e)}
    else:
        decky.logger.error("Global install_staged_update: plugin is None!")
        return {'success': False, 'error': 'Plugin not initialized'}

async def get_update_status() -> Dict[str, Any]:
    """Get background update check status (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_update_status()")
    if plugin:
        try:
            status = await plugin.get_update_status()
            decky.logger.info(f"Global get_update_status: {status}")
            return status
        except Exception as e:
            decky.logger.error(f"Global get_update_status failed: {e}")
            return {"update_available": False, "latest_version": None}
    else:
        decky.logger.error("Global get_update_status: plugin is None!")
        return {"update_available": False, "latest_version": None}

# Enhanced Sleep/Wake Management Global Functions
async def get_sleep_wake_diagnostics() -> Dict[str, Any]:
    """Get sleep/wake system diagnostics (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_sleep_wake_diagnostics()")
    if plugin:
        try:
            diagnostics = await plugin.get_sleep_wake_diagnostics()
            decky.logger.info(f"Global get_sleep_wake_diagnostics: {diagnostics}")
            return diagnostics
        except Exception as e:
            decky.logger.error(f"Global get_sleep_wake_diagnostics failed: {e}")
            return {"error": str(e)}
    else:
        decky.logger.error("Global get_sleep_wake_diagnostics: plugin is None!")
        return {"error": "Plugin not available"}

async def get_recent_sleep_wake_events(hours: int = 24) -> list:
    """Get recent sleep/wake events (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: get_recent_sleep_wake_events({hours})")
    if plugin:
        try:
            events = await plugin.get_recent_sleep_wake_events(hours)
            decky.logger.info(f"Global get_recent_sleep_wake_events: {len(events)} events")
            return events
        except Exception as e:
            decky.logger.error(f"Global get_recent_sleep_wake_events failed: {e}")
            return []
    else:
        decky.logger.error("Global get_recent_sleep_wake_events: plugin is None!")
        return []

async def force_wake_state_restoration() -> bool:
    """Manually trigger wake state restoration (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: force_wake_state_restoration()")
    if plugin:
        try:
            result = await plugin.force_wake_state_restoration()
            decky.logger.info(f"Global force_wake_state_restoration: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global force_wake_state_restoration failed: {e}")
            return False
    else:
        decky.logger.error("Global force_wake_state_restoration: plugin is None!")
        return False

# ROG Ally Specific Callable Functions
async def get_rog_ally_device_info() -> Dict[str, Any]:
    """Get comprehensive ROG Ally device information (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_device_info()")
    return await plugin.get_rog_ally_device_info()

async def set_rog_ally_power_limits(fast_limit: int, sustained_limit: int, stapm_limit: int) -> bool:
    """Set ROG Ally power limits (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_power_limits({fast_limit}, {sustained_limit}, {stapm_limit})")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            result = plugin.device_controller.set_power_limits(fast_limit, sustained_limit, stapm_limit)
            decky.logger.info(f"Global set_rog_ally_power_limits: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global set_rog_ally_power_limits failed: {e}")
            return False
    else:
        decky.logger.warning("Global set_rog_ally_power_limits: Not a ROG Ally device")
        return False

async def get_rog_ally_power_limits() -> Dict[str, Optional[int]]:
    """Get current ROG Ally power limits (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_power_limits()")
    return await plugin.get_rog_ally_power_limits()

async def set_rog_ally_platform_profile(profile: str) -> bool:
    """Set ROG Ally platform profile (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_platform_profile({profile})")
    return await plugin.set_rog_ally_platform_profile(profile)

async def get_rog_ally_platform_profile() -> Optional[str]:
    """Get current ROG Ally platform profile (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_platform_profile()")
    return await plugin.get_rog_ally_platform_profile()

async def set_rog_ally_mcu_powersave(enabled: bool) -> bool:
    """Set ROG Ally MCU power save mode (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_mcu_powersave({enabled})")
    return await plugin.set_rog_ally_mcu_powersave(enabled)

async def get_rog_ally_mcu_powersave() -> Optional[bool]:
    """Get ROG Ally MCU power save status (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_mcu_powersave()")
    return await plugin.get_rog_ally_mcu_powersave()

# =========================================================================
# InputPlumber Global Functions (Frontend Callable)
# =========================================================================

async def get_inputplumber_status() -> Dict[str, Any]:
    """Get InputPlumber availability and status (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_inputplumber_status()")
    return await plugin.get_inputplumber_status()

async def get_inputplumber_modes() -> List[Dict[str, str]]:
    """Get supported InputPlumber controller modes (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_inputplumber_modes()")
    return await plugin.get_inputplumber_modes()

async def set_inputplumber_mode(mode: str) -> bool:
    """Set InputPlumber controller mode (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_inputplumber_mode({mode})")
    return await plugin.set_inputplumber_mode(mode)

async def get_inputplumber_profile_for_game(game_id: str) -> Optional[Dict[str, Any]]:
    """Get InputPlumber settings for game profile (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: get_inputplumber_profile_for_game({game_id})")
    return await plugin.get_inputplumber_profile_for_game(game_id)

async def save_inputplumber_profile_for_game(game_id: str, inputplumber_settings: Dict[str, Any]) -> bool:
    """Save InputPlumber settings to game profile (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: save_inputplumber_profile_for_game({game_id})")
    return await plugin.save_inputplumber_profile_for_game(game_id, inputplumber_settings)

async def apply_inputplumber_profile_for_game(game_id: str) -> bool:
    """Apply InputPlumber profile for game (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: apply_inputplumber_profile_for_game({game_id})")
    return await plugin.apply_inputplumber_profile_for_game(game_id)

async def set_rog_ally_thermal_throttle_policy(policy: int) -> bool:
    """Set ROG Ally thermal throttling policy (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_thermal_throttle_policy({policy})")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            result = plugin.device_controller.set_thermal_throttle_policy(policy)
            decky.logger.info(f"Global set_rog_ally_thermal_throttle_policy: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global set_rog_ally_thermal_throttle_policy failed: {e}")
            return False
    else:
        decky.logger.warning("Global set_rog_ally_thermal_throttle_policy: Not a ROG Ally device")
        return False

async def get_rog_ally_thermal_throttle_policy() -> Optional[int]:
    """Get ROG Ally thermal throttling policy (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_thermal_throttle_policy()")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            policy = plugin.device_controller.get_thermal_throttle_policy()
            decky.logger.info(f"Global get_rog_ally_thermal_throttle_policy: {policy}")
            return policy
        except Exception as e:
            decky.logger.error(f"Global get_rog_ally_thermal_throttle_policy failed: {e}")
            return None
    else:
        decky.logger.warning("Global get_rog_ally_thermal_throttle_policy: Not a ROG Ally device")
        return None

async def set_rog_ally_fan_mode(fan_id: int, mode: int) -> bool:
    """Set ROG Ally fan mode (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_fan_mode({fan_id}, {mode})")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            result = plugin.device_controller.set_fan_mode(fan_id, mode)
            decky.logger.info(f"Global set_rog_ally_fan_mode: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global set_rog_ally_fan_mode failed: {e}")
            return False
    else:
        decky.logger.warning("Global set_rog_ally_fan_mode: Not a ROG Ally device")
        return False

async def get_rog_ally_fan_status() -> Dict[str, Any]:
    """Get ROG Ally fan status (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_fan_status()")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            status = plugin.device_controller.get_fan_status()
            decky.logger.info(f"Global get_rog_ally_fan_status: {status}")
            return status
        except Exception as e:
            decky.logger.error(f"Global get_rog_ally_fan_status failed: {e}")
            return {'cpu_fan': {'speed': None, 'mode': None, 'label': None}, 'gpu_fan': {'speed': None, 'mode': None, 'label': None}}
    else:
        decky.logger.warning("Global get_rog_ally_fan_status: Not a ROG Ally device")
        return {'cpu_fan': {'speed': None, 'mode': None, 'label': None}, 'gpu_fan': {'speed': None, 'mode': None, 'label': None}}

async def set_rog_ally_battery_charge_limit(limit: int) -> bool:
    """Set ROG Ally battery charge limit (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_battery_charge_limit({limit})")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            result = plugin.device_controller.set_battery_charge_limit(limit)
            decky.logger.info(f"Global set_rog_ally_battery_charge_limit: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global set_rog_ally_battery_charge_limit failed: {e}")
            return False
    else:
        decky.logger.warning("Global set_rog_ally_battery_charge_limit: Not a ROG Ally device")
        return False

async def get_rog_ally_battery_charge_limit() -> Optional[int]:
    """Get ROG Ally battery charge limit (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_battery_charge_limit()")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            limit = plugin.device_controller.get_battery_charge_limit()
            decky.logger.info(f"Global get_rog_ally_battery_charge_limit: {limit}")
            return limit
        except Exception as e:
            decky.logger.error(f"Global get_rog_ally_battery_charge_limit failed: {e}")
            return None
    else:
        decky.logger.warning("Global get_rog_ally_battery_charge_limit: Not a ROG Ally device")
        return None

async def set_rog_ally_performance_mode(mode: str) -> bool:
    """Set ROG Ally comprehensive performance mode (frontend callable)"""
    decky.logger.info(f"GLOBAL FUNCTION: set_rog_ally_performance_mode({mode})")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            # Import the performance mode function from ROG Ally module
            from devices.rog_ally import set_performance_mode
            result = set_performance_mode(mode)
            decky.logger.info(f"Global set_rog_ally_performance_mode: {result}")
            return result
        except Exception as e:
            decky.logger.error(f"Global set_rog_ally_performance_mode failed: {e}")
            return False
    else:
        decky.logger.warning("Global set_rog_ally_performance_mode: Not a ROG Ally device")
        return False

async def get_rog_ally_comprehensive_status() -> Dict[str, Any]:
    """Get comprehensive ROG Ally status (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: get_rog_ally_comprehensive_status()")
    if plugin and plugin.device_type == "rog_ally" and plugin.device_controller:
        try:
            from devices.rog_ally import get_comprehensive_status
            status = get_comprehensive_status()
            decky.logger.info(f"Global get_rog_ally_comprehensive_status: Retrieved status")
            return status
        except Exception as e:
            decky.logger.error(f"Global get_rog_ally_comprehensive_status failed: {e}")
            return {}
    else:
        decky.logger.warning("Global get_rog_ally_comprehensive_status: Not a ROG Ally device")
        return {}

# Sleep/Wake Debug Functions for Ayaneo Flip Investigation
async def debug_capture_pre_sleep_state():
    """Debug function to manually capture pre-sleep state (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: debug_capture_pre_sleep_state()")
    if plugin and plugin.sleep_wake_manager:
        try:
            state = await plugin.sleep_wake_manager.manual_capture_pre_sleep_state()
            decky.logger.info(f"Debug: Pre-sleep state captured with {len(state)} parameters")
            return {"success": True, "state": state}
        except Exception as e:
            decky.logger.error(f"Debug capture pre-sleep state failed: {e}")
            return {"success": False, "error": str(e)}
    else:
        decky.logger.warning("Debug capture pre-sleep state: Sleep/wake manager not available")
        return {"success": False, "error": "Sleep/wake manager not available"}

async def debug_test_wake_restoration():
    """Debug function to manually test wake restoration (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: debug_test_wake_restoration()")
    if plugin and plugin.sleep_wake_manager:
        try:
            success = await plugin.sleep_wake_manager.manual_test_wake_restoration()
            decky.logger.info(f"Debug: Wake restoration test completed: {success}")
            return {"success": success}
        except Exception as e:
            decky.logger.error(f"Debug wake restoration test failed: {e}")
            return {"success": False, "error": str(e)}
    else:
        decky.logger.warning("Debug wake restoration test: Sleep/wake manager not available")
        return {"success": False, "error": "Sleep/wake manager not available"}

async def debug_get_comprehensive_state():
    """Debug function to get current comprehensive system state (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: debug_get_comprehensive_state()")
    if plugin and plugin.sleep_wake_manager:
        try:
            state = await plugin.sleep_wake_manager._capture_comprehensive_state()
            decky.logger.info(f"Debug: Comprehensive state captured with {len(state)} parameters")
            return {"success": True, "state": state}
        except Exception as e:
            decky.logger.error(f"Debug get comprehensive state failed: {e}")
            return {"success": False, "error": str(e)}
    else:
        decky.logger.warning("Debug get comprehensive state: Sleep/wake manager not available")
        return {"success": False, "error": "Sleep/wake manager not available"}

async def debug_get_state_comparison():
    """Debug function to get the latest state comparison data (frontend callable)"""
    decky.logger.info("GLOBAL FUNCTION: debug_get_state_comparison()")
    try:
        import json
        comparison_file = "/tmp/powerdeck_state_comparison.json"
        if os.path.exists(comparison_file):
            with open(comparison_file, 'r') as f:
                comparison_data = json.load(f)
            decky.logger.info("Debug: State comparison data retrieved")
            return {"success": True, "comparison": comparison_data}
        else:
            decky.logger.info("Debug: No state comparison data available")
            return {"success": False, "error": "No comparison data available"}
    except Exception as e:
        decky.logger.error(f"Debug get state comparison failed: {e}")
        return {"success": False, "error": str(e)}
