"""
InputPlumber Manager - DBus-based InputPlumber Integration
Provides efficient DBus communication with InputPlumber for controller emulation
Significantly more efficient than DeckyPlumber's subprocess-based approach
"""
import os
import subprocess
from typing import Dict, List, Optional, Tuple
from enum import Enum
import decky_plugin

try:
    import dbus
    from dbus.exceptions import DBusException
    DBUS_AVAILABLE = True
except ImportError:
    decky_plugin.logger.warning("dbus-python not available, falling back to subprocess mode")
    DBUS_AVAILABLE = False


class ControllerMode(Enum):
    """Supported controller emulation modes"""
    DEFAULT = "default"
    XBOX = "xbox-series"
    XBOX_ELITE = "xbox-elite"
    DUAL_SENSE = "ds5"
    DUAL_SENSE_EDGE = "ds5-edge"
    HORI_STEAM = "hori-steam"
    STEAM_DECK = "deck-uhid"


class InputPlumberManager:
    """
    Manages InputPlumber integration via DBus
    Provides controller mode switching with device-specific input mapping
    """
    
    # DBus constants
    DBUS_SERVICE = "org.shadowblip.InputPlumber"
    DBUS_OBJECT_PATH = "/org/shadowblip/InputPlumber/CompositeDevice0"
    DBUS_INTERFACE = "org.shadowblip.Input.CompositeDevice"
    
    # State tracking
    STATE_FILE = "/tmp/.powerdeck_inputplumber.state"
    
    def __init__(self):
        """Initialize InputPlumber manager"""
        self._dbus_connection = None
        self._composite_device = None
        self._available = False
        self._capabilities = {}
        self._device_name = self._detect_device()
        
        # Initialize DBus connection
        self._init_dbus()
    
    def _detect_device(self) -> str:
        """Detect current device for input mapping"""
        try:
            with open("/sys/devices/virtual/dmi/id/product_name", "r") as f:
                device_name = f.read().strip()
                return device_name
        except Exception as e:
            decky_plugin.logger.error(f"Failed to detect device: {e}")
            return "Unknown"
    
    def _init_dbus(self):
        """Initialize DBus connection to InputPlumber"""
        if not DBUS_AVAILABLE:
            decky_plugin.logger.info("DBus not available, checking InputPlumber via subprocess fallback")
            # Check if InputPlumber is available via subprocess method
            self._check_inputplumber_subprocess()
            return
        
        try:
            # Get system bus
            self._dbus_connection = dbus.SystemBus()
            
            # Get InputPlumber service
            inputplumber_obj = self._dbus_connection.get_object(
                self.DBUS_SERVICE,
                self.DBUS_OBJECT_PATH
            )
            
            # Get composite device interface
            self._composite_device = dbus.Interface(
                inputplumber_obj,
                self.DBUS_INTERFACE
            )
            
            self._available = True
            decky_plugin.logger.info(f"InputPlumber DBus connection established for device: {self._device_name}")
            
            # Query capabilities
            self._query_capabilities()
            
        except DBusException as e:
            decky_plugin.logger.info(f"InputPlumber not available via DBus: {e}")
            # Try subprocess fallback
            self._check_inputplumber_subprocess()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to initialize InputPlumber DBus: {e}")
            # Try subprocess fallback
            self._check_inputplumber_subprocess()
    
    def _check_inputplumber_subprocess(self):
        """Check if InputPlumber is available via subprocess commands"""
        try:
            # Clear LD_LIBRARY_PATH to avoid library conflicts with system commands
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = ""
            
            # Try to query InputPlumber via systemctl
            result = subprocess.run(
                ["systemctl", "is-active", "inputplumber"],
                capture_output=True,
                text=True,
                timeout=2,
                env=env
            )
            
            decky_plugin.logger.info(f"systemctl check: returncode={result.returncode}, stdout='{result.stdout.strip()}', stderr='{result.stderr.strip()}'")
            
            if result.returncode == 0 and result.stdout.strip() == "active":
                self._available = True
                decky_plugin.logger.info(f"InputPlumber service detected (subprocess mode) for device: {self._device_name}")
                self._capabilities = {
                    "has_set_target_devices": True,
                    "dbus_available": False,
                    "subprocess_mode": True,
                    "device": self._device_name
                }
            else:
                self._available = False
                decky_plugin.logger.info(f"InputPlumber service not active (returncode={result.returncode}, output='{result.stdout.strip()}')")
        except Exception as e:
            decky_plugin.logger.error(f"Failed to check InputPlumber availability: {e}")
            self._available = False
    
    def _query_capabilities(self):
        """Query InputPlumber capabilities and version"""
        if not self._available:
            return
        
        try:
            # Try to introspect the interface for available methods
            introspectable = dbus.Interface(
                self._dbus_connection.get_object(
                    self.DBUS_SERVICE,
                    self.DBUS_OBJECT_PATH
                ),
                "org.freedesktop.DBus.Introspectable"
            )
            
            introspection = introspectable.Introspect()
            
            # Store basic capabilities
            self._capabilities = {
                "has_set_target_devices": "SetTargetDevices" in introspection,
                "dbus_available": True,
                "device": self._device_name
            }
            
            decky_plugin.logger.info(f"InputPlumber capabilities: {self._capabilities}")
            
        except Exception as e:
            decky_plugin.logger.warning(f"Failed to query InputPlumber capabilities: {e}")
            self._capabilities = {"dbus_available": True}
    
    def is_available(self) -> bool:
        """Check if InputPlumber is available"""
        # Re-check availability if not currently available
        if not self._available and DBUS_AVAILABLE:
            self._init_dbus()
        
        return self._available
    
    def get_inputplumber_version(self) -> Optional[str]:
        """
        Get InputPlumber version from systemctl status
        Returns version string like '0.58.4' or None if unavailable
        """
        try:
            # Clear LD_LIBRARY_PATH to avoid library conflicts
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = ""
            
            # Try to get version from systemctl status
            result = subprocess.run(
                ["systemctl", "status", "inputplumber", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=2,
                env=env
            )
            
            if result.returncode == 0:
                # Look for version in output (e.g., "inputplumber 0.58.4")
                for line in result.stdout.split("\n"):
                    if "inputplumber" in line.lower():
                        # Try to extract version number
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if "inputplumber" in part.lower() and i + 1 < len(parts):
                                # Check if next part looks like a version
                                potential_version = parts[i + 1]
                                if potential_version[0].isdigit():
                                    decky_plugin.logger.info(f"Detected InputPlumber version: {potential_version}")
                                    return potential_version
                
                # Fallback: assume version from service description
                decky_plugin.logger.warning("Could not parse InputPlumber version from systemctl status")
                return None
            else:
                decky_plugin.logger.warning(f"Failed to get InputPlumber version: returncode={result.returncode}")
                return None
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to detect InputPlumber version: {e}")
            return None
    
    def _version_greater_than_or_equal(self, version: str, target_version: str) -> bool:
        """
        Compare version strings (e.g., '0.58.5' >= '0.58.5')
        Returns True if version >= target_version
        """
        try:
            # Split into parts and compare
            version_parts = [int(x) for x in version.split('.')]
            target_parts = [int(x) for x in target_version.split('.')]
            
            # Pad shorter version with zeros
            while len(version_parts) < len(target_parts):
                version_parts.append(0)
            while len(target_parts) < len(version_parts):
                target_parts.append(0)
            
            # Compare each part
            for v, t in zip(version_parts, target_parts):
                if v > t:
                    return True
                elif v < t:
                    return False
            
            return True  # Equal
        except Exception as e:
            decky_plugin.logger.error(f"Failed to compare versions: {e}")
            return False  # Assume incompatible on error
    
    def get_supported_modes(self) -> List[str]:
        """
        Get list of supported controller modes
        Only returns essential modes: default, xbox-series, xbox-elite, ds5-edge, deck-uhid
        Filters out: ds5, hori-steam (compatibility issues)
        """
        # Essential modes only - user requested simplified list
        essential_modes = [
            ControllerMode.DEFAULT.value,       # default
            ControllerMode.XBOX.value,          # xbox-series
            ControllerMode.XBOX_ELITE.value,    # xbox-elite
            ControllerMode.DUAL_SENSE_EDGE.value, # ds5-edge
            ControllerMode.STEAM_DECK.value     # deck-uhid
        ]
        
        decky_plugin.logger.info(f"Returning {len(essential_modes)} essential controller modes")
        return essential_modes
    
    def get_capabilities(self) -> Dict:
        """Get InputPlumber capabilities"""
        version = self.get_inputplumber_version()
        return {
            "available": self._available,
            "dbus_mode": DBUS_AVAILABLE,
            "capabilities": self._capabilities,
            "supported_modes": self.get_supported_modes(),
            "version": version,
            "device": self._device_name
        }
    
    def _get_device_inputs(self, mode: str) -> List[str]:
        """
        Get device-specific input types for controller mode
        Handles special cases like Legion Go touchpad, AYANEO Flip touchscreen
        """
        # Default inputs for most devices
        inputs = ["keyboard", "mouse"]
        
        # Device-specific overrides
        device_lower = self._device_name.lower()
        
        # Lenovo Legion Go uses touchpad instead of mouse
        if "83e1" in device_lower or "legion go" in device_lower:
            inputs = ["keyboard", "touchpad"]
            decky_plugin.logger.info(f"Legion Go detected, using touchpad instead of mouse")
        
        # AYANEO Flip adds touchscreen
        elif "flip ds" in device_lower or "flip kb" in device_lower:
            inputs = ["keyboard", "mouse", "touchscreen"]
            decky_plugin.logger.info(f"AYANEO Flip detected, adding touchscreen support")
        
        return inputs
    
    def get_current_mode(self) -> Optional[str]:
        """Get current controller mode from state file"""
        try:
            if os.path.exists(self.STATE_FILE):
                with open(self.STATE_FILE, "r") as f:
                    mode = f.read().strip()
                    return mode if mode else ControllerMode.DEFAULT.value
            return ControllerMode.DEFAULT.value
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read InputPlumber state: {e}")
            return ControllerMode.DEFAULT.value
    
    def _save_current_mode(self, mode: str):
        """Save current mode to state file"""
        try:
            with open(self.STATE_FILE, "w") as f:
                f.write(mode)
        except Exception as e:
            decky_plugin.logger.error(f"Failed to save InputPlumber state: {e}")
    
    def set_controller_mode_dbus(self, mode: str) -> bool:
        """
        Set controller mode using DBus (efficient method)
        Returns True if successful, False otherwise
        """
        if not self._available:
            decky_plugin.logger.warning("InputPlumber not available, cannot set controller mode")
            return False
        
        try:
            # Check if already in this mode
            current_mode = self.get_current_mode()
            if current_mode == mode:
                decky_plugin.logger.info(f"Already in mode {mode}, skipping")
                return True
            
            if mode == ControllerMode.DEFAULT.value:
                # Default mode: restart InputPlumber service
                decky_plugin.logger.info("Setting default mode, restarting InputPlumber")
                if os.path.exists(self.STATE_FILE):
                    os.remove(self.STATE_FILE)
                
                # Restart service
                subprocess.run(
                    ["systemctl", "restart", "inputplumber"],
                    check=True,
                    capture_output=True
                )
                return True
            
            else:
                # Set specific controller mode via DBus
                inputs = self._get_device_inputs(mode)
                
                # Build arguments array: [mode, input1, input2, ...]
                args = [mode] + inputs
                
                decky_plugin.logger.info(f"Setting InputPlumber mode via DBus: {mode} with inputs: {inputs}")
                
                # Call DBus method
                self._composite_device.SetTargetDevices(args)
                
                # Save state
                self._save_current_mode(mode)
                
                decky_plugin.logger.info(f"Successfully set InputPlumber mode to {mode}")
                return True
                
        except DBusException as e:
            decky_plugin.logger.error(f"DBus error setting controller mode: {e}")
            return False
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set controller mode: {e}")
            return False
    
    def set_controller_mode_subprocess(self, mode: str) -> bool:
        """
        Set controller mode using subprocess (fallback method)
        Less efficient than DBus but works without dbus-python
        """
        try:
            current_mode = self.get_current_mode()
            if current_mode == mode:
                decky_plugin.logger.info(f"Already in mode {mode}, skipping")
                return True
            
            if mode == ControllerMode.DEFAULT.value:
                # Default mode: restart InputPlumber service
                if os.path.exists(self.STATE_FILE):
                    os.remove(self.STATE_FILE)
                
                subprocess.run(
                    ["systemctl", "restart", "inputplumber"],
                    check=True,
                    capture_output=True
                )
                return True
            
            else:
                # Set specific controller mode via busctl
                inputs = self._get_device_inputs(mode)
                
                # Build busctl command
                input_args = " ".join([f'"{mode}"'] + [f'"{inp}"' for inp in inputs])
                input_count = len([mode] + inputs)
                
                cmd = [
                    "busctl", "call",
                    self.DBUS_SERVICE,
                    self.DBUS_OBJECT_PATH,
                    self.DBUS_INTERFACE,
                    "SetTargetDevices",
                    "as",
                    str(input_count),
                    mode
                ] + inputs
                
                decky_plugin.logger.info(f"Setting InputPlumber mode via subprocess: {' '.join(cmd)}")
                
                # Clear LD_LIBRARY_PATH for clean environment
                env = os.environ.copy()
                env["LD_LIBRARY_PATH"] = ""
                
                result = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env
                )
                
                # Save state
                self._save_current_mode(mode)
                
                decky_plugin.logger.info(f"Successfully set InputPlumber mode to {mode}")
                return True
                
        except subprocess.CalledProcessError as e:
            decky_plugin.logger.error(f"Subprocess error setting controller mode: {e.stderr}")
            return False
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set controller mode via subprocess: {e}")
            return False
    
    def set_controller_mode(self, mode: str) -> bool:
        """
        Set controller mode (uses DBus if available, falls back to subprocess)
        """
        # Validate mode
        valid_modes = [m.value for m in ControllerMode]
        if mode not in valid_modes:
            decky_plugin.logger.error(f"Invalid controller mode: {mode}. Valid modes: {valid_modes}")
            return False
        
        # Use DBus if available, otherwise subprocess
        if self._available and DBUS_AVAILABLE:
            return self.set_controller_mode_dbus(mode)
        else:
            return self.set_controller_mode_subprocess(mode)
    
    def validate_mode(self, mode: str) -> bool:
        """Check if mode is valid"""
        return mode in [m.value for m in ControllerMode]


# Global instance
_inputplumber_manager = None


def get_inputplumber_manager() -> InputPlumberManager:
    """Get or create global InputPlumber manager instance"""
    global _inputplumber_manager
    if _inputplumber_manager is None:
        _inputplumber_manager = InputPlumberManager()
    return _inputplumber_manager
