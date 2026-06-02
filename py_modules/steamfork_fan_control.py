"""
Platform Fan Control Integration for PowerDeck
==============================================

This module provides fan control functionality for SteamFork and JELOS systems.
Both distributions ship the same fan control tooling under different binary
names:

  - SteamFork: steamfork-fancontrol, steamfork-device-id, steamfork-get-setting
  - JELOS:     jelos-fancontrol,     jelos-device-id,     jelos-get-setting

The SteamForkFanController class name and module name are retained for
backward compatibility, but the implementation transparently detects and
supports either distribution.

Copyright (C) 2024 PowerDeck Project
License: GPL-2.0
"""

import os
import subprocess
import asyncio
import json
import tempfile
from typing import Dict, List, Optional, Tuple

# Distribution tool name variants.  Detection picks the first one present.
FAN_CONTROL_BINARIES = ("steamfork-fancontrol", "jelos-fancontrol")
DEVICE_ID_BINARIES  = ("steamfork-device-id",  "jelos-device-id")
GET_SETTING_BINARIES = ("steamfork-get-setting", "jelos-get-setting")
FAN_CONTROL_SERVICES = ("steamfork-fancontrol", "jelos-fancontrol")


def _find_executable(candidates: tuple) -> Optional[str]:
    """Return the first existing absolute path from a tuple of candidate names."""
    for name in candidates:
        path = f"/usr/bin/{name}"
        if os.path.exists(path):
            return path
    return None

# Try to import decky_plugin, fall back to logging if not available
try:
    import decky_plugin
    logger = decky_plugin.logger
except ImportError:
    # Fallback logging for testing outside plugin context
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(handler)


class SteamForkFanController:
    """
    Fan control integration for SteamFork and JELOS systems.

    Provides a safe interface to the platform's cooling profile system while
    maintaining compatibility with the existing fan control daemon.  Detects
    whichever flavor of tooling (SteamFork or JELOS) is installed and uses it.
    """

    def __init__(self):
        self.platform_available = False
        self.platform_name = None        # "SteamFork" or "JELOS" once detected
        self.fancontrol_binary = None    # e.g. /usr/bin/jelos-fancontrol
        self.device_id_binary = None     # e.g. /usr/bin/jelos-device-id
        self.get_setting_binary = None   # e.g. /usr/bin/jelos-get-setting
        self.fancontrol_service = None   # e.g. jelos-fancontrol
        # Backward-compat alias used by callers
        self.steamfork_available = False
        self.current_profile = "auto"
        self.supported_profiles = ["auto", "quiet", "moderate", "aggressive"]
        self.pwm_path = None
        self.fan_enabled_path = None

        # Check if platform fan control is available
        self._detect_platform()

    def _detect_platform(self) -> bool:
        """Detect if SteamFork or JELOS fan control is available on this system."""
        try:
            # Resolve the platform-specific binaries
            self.fancontrol_binary = _find_executable(FAN_CONTROL_BINARIES)
            if not self.fancontrol_binary:
                logger.info("Platform fan control not found - feature disabled "
                            f"(looked for: {', '.join(FAN_CONTROL_BINARIES)})")
                return False

            self.device_id_binary = _find_executable(DEVICE_ID_BINARIES)
            self.get_setting_binary = _find_executable(GET_SETTING_BINARIES)

            # Determine the platform name from the resolved binary path
            if "jelos" in self.fancontrol_binary:
                self.platform_name = "JELOS"
            else:
                self.platform_name = "SteamFork"

            logger.info(f"Detected platform: {self.platform_name} "
                        f"(fancontrol={self.fancontrol_binary})")

            # Find the matching systemd service name
            for svc in FAN_CONTROL_SERVICES:
                if svc in self.fancontrol_binary:
                    self.fancontrol_service = svc
                    break

            if not self.device_id_binary:
                logger.error(f"Platform device-id binary not found "
                             f"(looked for: {', '.join(DEVICE_ID_BINARIES)})")
                return False

            # Get quirk paths for the device-specific fan control script
            quirk_paths = self._get_quirk_paths()
            if not quirk_paths:
                return False

            # Look for fan control script in quirk paths
            for path in quirk_paths:
                fancontrol_path = os.path.join(path, "bin", "fancontrol")
                if os.path.exists(fancontrol_path):
                    logger.info(f"Found {self.platform_name} fan control at: {fancontrol_path}")
                    self.platform_available = True
                    break

            if not self.platform_available:
                logger.warning("No fancontrol script found in any quirk path")
                return False

            # Backward-compat alias
            self.steamfork_available = True

            # Find PWM interface
            self._find_pwm_interface()

            if self.platform_available:
                # Get current profile
                self._get_current_profile()
                logger.info(f"{self.platform_name} fan control initialized - "
                            f"current profile: {self.current_profile}")

            return self.platform_available

        except Exception as e:
            logger.error(f"Error detecting platform fan control: {e}")
            return False

    def _get_quirk_paths(self) -> List[str]:
        """Run the platform device-id tool to retrieve quirk paths.

        Tries multiple invocation approaches because the plugin's bundled
        environment can break system binaries (LD_LIBRARY_PATH / bash library
        issues).
        """
        if not self.device_id_binary:
            return []

        # Approach 1: bash with minimal environment
        try:
            env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/tmp"}
            result = subprocess.run(["/bin/bash", self.device_id_binary, "quirkpaths"],
                                    capture_output=True, text=True, timeout=5, env=env)
            if result.returncode == 0:
                paths = result.stdout.strip().split()
                if paths:
                    return paths
            logger.warning(f"Could not get {self.platform_name} device quirk paths "
                           f"- returncode: {result.returncode}")
        except Exception as e:
            logger.warning(f"Error running {self.device_id_binary} with bash: {e}")

        # Approach 2: sh fallback
        try:
            result = subprocess.run(["/bin/sh", self.device_id_binary, "quirkpaths"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                paths = result.stdout.strip().split()
                if paths:
                    return paths
            logger.warning(f"Could not get {self.platform_name} device quirk paths "
                           f"with sh - returncode: {result.returncode}")
        except Exception as e:
            logger.warning(f"Error running {self.device_id_binary} with sh: {e}")

        logger.error(f"Could not get quirk paths from {self.device_id_binary}")
        return []
    
    def _find_pwm_interface(self) -> None:
        """Find the PWM fan control interface."""
        try:
            # Look for OXP platform PWM interface (common on handhelds)
            pwm_base = "/sys/devices/platform/oxp-platform"
            
            if not os.path.exists(pwm_base):
                logger.warning(f"PWM base path {pwm_base} does not exist")
                return
                
            for root, dirs, files in os.walk(pwm_base):
                if "pwm1" in files:
                    self.pwm_path = os.path.join(root, "pwm1")
                    self.fan_enabled_path = os.path.join(root, "pwm1_enable")
                    logger.info(f"Found PWM interface: {self.pwm_path}")
                    return
                    
            logger.warning("No PWM interface found")
        except Exception as e:
            logger.error(f"Could not find PWM interface: {e}")
    
    def _get_current_profile(self) -> str:
        """Get the current cooling profile from platform settings."""
        try:
            if not self.get_setting_binary:
                # Fall back to the SteamFork name for backward compatibility
                self.get_setting_binary = _find_executable(GET_SETTING_BINARIES)
            if not self.get_setting_binary:
                logger.warning("No platform get-setting binary available")
                self.current_profile = "quiet"
                return "quiet"

            result = subprocess.run([self.get_setting_binary, "cooling.profile"],
                                  capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                profile = result.stdout.strip()
                if profile in self.supported_profiles:
                    self.current_profile = profile
                    return profile

            # Default to quiet if not set
            self.current_profile = "quiet"
            return "quiet"

        except Exception as e:
            logger.error(f"Error getting current cooling profile: {e}")
            return "auto"
    
    def is_available(self) -> bool:
        """Check if platform (SteamFork/JELOS) fan control is available."""
        return self.platform_available
    
    def get_available_profiles(self) -> List[Dict]:
        """Get list of available cooling profiles."""
        return [
            {"value": "auto", "label": "Auto (Hardware Control)", "description": "Let hardware manage fan automatically"},
            {"value": "quiet", "label": "Quiet", "description": "6-level quiet operation (55-90°C)"},
            {"value": "moderate", "label": "Moderate", "description": "5-level balanced cooling (50-90°C)"},
            {"value": "aggressive", "label": "Aggressive", "description": "3-level maximum cooling (45-85°C)"}
        ]
    
    async def get_fan_info(self) -> Dict:
        """Get comprehensive fan control information."""
        if not self.platform_available:
            return {
                "available": False,
                "error": f"{self.platform_name or 'Platform'} fan control not available"
            }
        
        try:
            current_speed = None
            fan_enabled = None
            
            # Get current fan speed and status
            if self.pwm_path and os.path.exists(self.pwm_path):
                with open(self.pwm_path, 'r') as f:
                    current_speed = int(f.read().strip())
            
            if self.fan_enabled_path and os.path.exists(self.fan_enabled_path):
                with open(self.fan_enabled_path, 'r') as f:
                    fan_enabled = bool(int(f.read().strip()))
            
            return {
                "available": True,
                "current_profile": self.current_profile,
                "supported_profiles": self.supported_profiles,
                "current_speed": current_speed,
                "fan_enabled": fan_enabled,
                "profile_descriptions": {
                    "auto": "Hardware automatic control",
                    "quiet": "Prioritizes silence - higher temp thresholds (55-90°C)",
                    "moderate": "Balanced cooling and noise (50-90°C)", 
                    "aggressive": "Maximum cooling - lower temp thresholds (45-85°C)"
                },
                "speed_ranges": {
                    "quiet": "24-128 PWM (6 levels)",
                    "moderate": "24-128 PWM (5 levels)",
                    "aggressive": "64-128 PWM (3 levels)",
                    "auto": "Hardware controlled"
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting fan info: {e}")
            return {
                "available": True,
                "error": f"Could not read fan status: {e}",
                "current_profile": self.current_profile
            }
    
    async def set_cooling_profile(self, profile: str) -> Dict:
        """
        Set the cooling profile by directly modifying the platform.json file.

        Args:
            profile: One of 'auto', 'quiet', 'moderate', 'aggressive'

        Returns:
            Dict with success status and any error messages
        """
        if not self.platform_available:
            return {
                "success": False,
                "error": f"{self.platform_name or 'Platform'} fan control not available"
            }

        if profile not in self.supported_profiles:
            return {
                "success": False,
                "error": f"Unsupported profile '{profile}'. Supported: {self.supported_profiles}"
            }

        try:
            logger.info(f"Setting cooling profile to: {profile}")

            # Path to the platform configuration (shared by SteamFork and JELOS)
            platform_config_path = "/home/.config/system/platform.json"
            
            # Read current configuration
            config_data = {}
            if os.path.exists(platform_config_path):
                try:
                    with open(platform_config_path, 'r') as f:
                        config_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Could not read existing config: {e}, creating new one")
                    config_data = {}
            
            # Ensure cooling section exists
            if "cooling" not in config_data:
                config_data["cooling"] = {}
            
            # Update the cooling profile
            old_profile = config_data.get("cooling", {}).get("profile", "unknown")
            config_data["cooling"]["profile"] = profile
            
            # Write updated configuration with proper permissions
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_file:
                json.dump(config_data, temp_file, indent=2)
                temp_path = temp_file.name
            
            # Move temp file to final location with sudo
            try:
                # Ensure directory exists
                subprocess.run(["sudo", "mkdir", "-p", "/home/.config/system"], 
                             capture_output=True, text=True, timeout=5)
                
                # Copy file with proper ownership
                subprocess.run(["sudo", "cp", temp_path, platform_config_path], 
                             capture_output=True, text=True, timeout=5)
                
                subprocess.run(["sudo", "chown", "deck:deck", platform_config_path], 
                             capture_output=True, text=True, timeout=5)
                
                subprocess.run(["sudo", "chmod", "644", platform_config_path], 
                             capture_output=True, text=True, timeout=5)
                
                # Clean up temp file
                os.unlink(temp_path)
                
                logger.info(f"Successfully updated platform config: {old_profile} → {profile}")
                
            except Exception as e:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise e
            
            # Update internal state
            self.current_profile = profile
            
            # Restart fan control service to apply new profile - CRITICAL for profile changes to take effect
            try:
                logger.info(f"CRITICAL: Restarting {self.fancontrol_service} service to apply profile change: {old_profile} -> {profile}")

                # Use restart command with proper timing to avoid start-limit-hit
                # First, reset any failed states
                reset_result = subprocess.run(["sudo", "systemctl", "reset-failed", self.fancontrol_service],
                                            capture_output=True, text=True, timeout=5)
                if reset_result.returncode != 0:
                    logger.debug(f"Reset-failed returned: {reset_result.returncode} (this is normal if service wasn't failed)")

                # Now restart the service
                restart_result = subprocess.run(["sudo", "systemctl", "restart", self.fancontrol_service],
                                              capture_output=True, text=True, timeout=20)

                if restart_result.returncode != 0:
                    error_msg = restart_result.stderr.strip() if restart_result.stderr else "Unknown error restarting service"
                    logger.error(f"CRITICAL: Failed to restart {self.fancontrol_service} service: {error_msg}")

                    # Try to check if service is actually running despite the error
                    status_result = subprocess.run(["systemctl", "is-active", self.fancontrol_service],
                                                 capture_output=True, text=True, timeout=5)
                    if status_result.stdout.strip() == "active":
                        logger.info("Service appears to be running despite restart error")
                    else:
                        # Critical failure - return error
                        return {
                            "success": False,
                            "error": f"Fan profile set but service restart failed: {error_msg}"
                        }
                else:
                    logger.info(f"Successfully restarted {self.fancontrol_service} service - new profile active")
                    
            except subprocess.TimeoutExpired:
                logger.error(f"CRITICAL: Timeout restarting {self.fancontrol_service} service")
                return {
                    "success": False,
                    "error": "Fan profile set but service restart timed out"
                }
            except Exception as e:
                logger.error(f"CRITICAL: Error restarting {self.fancontrol_service} service: {e}")
                return {
                    "success": False,
                    "error": f"Fan profile set but service restart failed: {e}"
                }
            
            logger.info(f"Cooling profile changed: {old_profile} → {profile}")
            
            return {
                "success": True,
                "message": f"Cooling profile set to '{profile}'",
                "old_profile": old_profile,
                "new_profile": profile
            }
            
        except Exception as e:
            logger.error(f"Error setting cooling profile: {e}")
            return {
                "success": False,
                "error": f"Error setting cooling profile: {e}"
            }
    
    async def get_current_temperature(self) -> Optional[float]:
        """Get average CPU temperature in Celsius."""
        try:
            # Try thermal zones first (more reliable on modern systems)
            temps = []
            thermal_zones_path = "/sys/class/thermal"
            
            if os.path.exists(thermal_zones_path):
                for thermal_zone in os.listdir(thermal_zones_path):
                    if thermal_zone.startswith("thermal_zone"):
                        temp_file = os.path.join(thermal_zones_path, thermal_zone, "temp")
                        try:
                            with open(temp_file, 'r') as f:
                                temp_millic = int(f.read().strip())
                                if temp_millic > 0:  # Skip zero/invalid readings
                                    temp_celsius = temp_millic / 1000.0
                                    if temp_celsius > 15 and temp_celsius < 120:  # Reasonable CPU temp range
                                        temps.append(temp_celsius)
                        except (OSError, ValueError):
                            continue
            
            # Fallback: Try PCI device temperature sensors
            if not temps:
                for root, dirs, files in os.walk("/sys/devices/pci"):
                    for file in files:
                        if file == "temp1_input" and "nvme" not in root:
                            temp_file = os.path.join(root, file)
                            try:
                                with open(temp_file, 'r') as f:
                                    temp_millic = int(f.read().strip())
                                    temp_celsius = temp_millic / 1000.0
                                    if temp_celsius > 15 and temp_celsius < 120:
                                        temps.append(temp_celsius)
                            except (OSError, ValueError):
                                continue
            
            if temps:
                avg_temp = sum(temps) / len(temps)
                return round(avg_temp, 1)
            
            return None
            
        except Exception as e:
            logger.error(f"Error reading temperature: {e}")
            return None


# Global instance
steamfork_fan_controller = SteamForkFanController()
