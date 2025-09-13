"""
PowerDeck - Lenovo Legion Support Module
Thermal and power management for Lenovo Legion Go devices

Copyright (C) 2025 Fewtarius

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import subprocess
import os
import decky_plugin
from time import sleep
from typing import Optional, Dict, Any

# Lenovo Legion WMI Interface Paths
LENOVO_WMI_BASE = "/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"

# Power Management Suffixes
FAST_POWER_SUFFIX = "ppt_pl3_fppt"
SUSTAINED_POWER_SUFFIX = "ppt_pl2_sppt"
STAPM_POWER_SUFFIX = "ppt_pl1_spl"

# Complete WMI Paths
LENOVO_FAST_POWER_PATH = f"{LENOVO_WMI_BASE}/{FAST_POWER_SUFFIX}/current_value"
LENOVO_SUSTAINED_POWER_PATH = f"{LENOVO_WMI_BASE}/{SUSTAINED_POWER_SUFFIX}/current_value"
LENOVO_STAPM_POWER_PATH = f"{LENOVO_WMI_BASE}/{STAPM_POWER_SUFFIX}/current_value"

# Thermal Management Paths
ACPI_PLATFORM_PROFILE = '/sys/firmware/acpi/platform_profile'
LEGION_THERMAL_MODE = "/sys/devices/platform/legion_laptop/mode"

# Legion Go LED Control
LEGION_LED_PATH = "/sys/class/leds/legion::power/brightness"

class LenovoLegionController:
    """PowerDeck controller for Lenovo Legion devices"""
    
    def __init__(self):
        self.device_name = self._detect_legion_variant()
        self.wmi_available = self._check_wmi_support()
        self.thermal_control_available = self._check_thermal_support()
    
    def _detect_legion_variant(self) -> str:
        """Detect specific Legion model"""
        try:
            with open('/sys/devices/virtual/dmi/id/product_name', 'r') as f:
                product_name = f.read().strip()
                if '83E1' in product_name or 'Legion Go' in product_name:
                    return 'Legion Go'
                elif '83L3' in product_name or 'Legion Go S' in product_name:
                    return 'Legion Go S'
                else:
                    return 'Unknown Legion Device'
        except Exception as e:
            decky_plugin.logger.warning(f"Could not detect Legion variant: {e}")
            return 'Legion (Unknown)'
    
    def _check_wmi_support(self) -> bool:
        """Check if Lenovo WMI power management is available"""
        return all(os.path.exists(path) for path in [
            LENOVO_FAST_POWER_PATH, 
            LENOVO_SUSTAINED_POWER_PATH, 
            LENOVO_STAPM_POWER_PATH
        ])
    
    def _check_thermal_support(self) -> bool:
        """Check if Legion thermal management interfaces are available"""
        return os.path.exists(ACPI_PLATFORM_PROFILE) or os.path.exists(LEGION_THERMAL_MODE)
    
    def _execute_privileged_write(self, path: str, value: str) -> bool:
        """Execute privileged write operation"""
        try:
            if not os.path.exists(path):
                decky_plugin.logger.error(f"Path does not exist: {path}")
                return False
            
            result = subprocess.run([
                'pkexec', 'bash', '-c', f'echo "{value}" > "{path}"'
            ], capture_output=True, text=True, timeout=15)
            
            success = result.returncode == 0
            if not success:
                decky_plugin.logger.error(f"Failed to write {value} to {path}: {result.stderr}")
            
            return success
        except Exception as e:
            decky_plugin.logger.error(f"Privileged write failed for {path}: {e}")
            return False
    
    def _read_sysfs_value(self, path: str) -> Optional[str]:
        """Safely read value from sysfs path"""
        try:
            if not os.path.exists(path):
                return None
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read {path}: {e}")
            return None
    
    def set_power_limits_wmi(self, fast_limit: int, sustained_limit: int, stapm_limit: int) -> bool:
        """Set Legion power limits via WMI interface"""
        if not self.wmi_available:
            decky_plugin.logger.error("Lenovo WMI interface not available")
            return False
        
        # Convert watts to milliwatts
        fast_mw = str(fast_limit * 1000)
        sustained_mw = str(sustained_limit * 1000)
        stapm_mw = str(stapm_limit * 1000)
        
        success = True
        success &= self._execute_privileged_write(LENOVO_FAST_POWER_PATH, fast_mw)
        sleep(0.1)  # Small delay between WMI operations
        success &= self._execute_privileged_write(LENOVO_SUSTAINED_POWER_PATH, sustained_mw)
        sleep(0.1)
        success &= self._execute_privileged_write(LENOVO_STAPM_POWER_PATH, stapm_mw)
        
        if success:
            decky_plugin.logger.info(f"Legion power limits set via WMI: Fast={fast_limit}W, Sustained={sustained_limit}W, STAPM={stapm_limit}W")
            # Set LED to purple to indicate custom TDP mode
            self._set_power_led_purple()
        
        return success
    
    def get_power_limits_wmi(self) -> Dict[str, Optional[int]]:
        """Get current Legion power limits from WMI"""
        limits = {
            'fast_limit': None,
            'sustained_limit': None,
            'stapm_limit': None
        }
        
        if not self.wmi_available:
            return limits
        
        try:
            fast_raw = self._read_sysfs_value(LENOVO_FAST_POWER_PATH)
            sustained_raw = self._read_sysfs_value(LENOVO_SUSTAINED_POWER_PATH)
            stapm_raw = self._read_sysfs_value(LENOVO_STAPM_POWER_PATH)
            
            # Convert milliwatts to watts
            if fast_raw:
                limits['fast_limit'] = int(fast_raw) // 1000
            if sustained_raw:
                limits['sustained_limit'] = int(sustained_raw) // 1000
            if stapm_raw:
                limits['stapm_limit'] = int(stapm_raw) // 1000
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read Legion power limits: {e}")
        
        return limits
    
    def _set_power_led_purple(self) -> bool:
        """Set Legion power LED to purple (custom TDP indicator)"""
        try:
            # Purple LED indication for custom TDP mode
            if os.path.exists(LEGION_LED_PATH):
                return self._execute_privileged_write(LEGION_LED_PATH, "128")  # Mid brightness
        except Exception as e:
            decky_plugin.logger.warning(f"Could not set Legion LED: {e}")
        
        return False
    
    def set_thermal_mode(self, mode: str) -> bool:
        """Set Legion thermal mode"""
        valid_modes = ['performance', 'balanced', 'quiet', 'custom']
        
        if mode not in valid_modes:
            decky_plugin.logger.error(f"Invalid thermal mode: {mode}")
            return False
        
        # Try Legion-specific thermal control first
        if os.path.exists(LEGION_THERMAL_MODE):
            success = self._execute_privileged_write(LEGION_THERMAL_MODE, mode)
            if success:
                decky_plugin.logger.info(f"Legion thermal mode set to: {mode}")
                return True
        
        # Fallback to ACPI platform profile
        if os.path.exists(ACPI_PLATFORM_PROFILE):
            # Map Legion modes to ACPI profiles
            acpi_mode_map = {
                'performance': 'performance',
                'balanced': 'balanced',
                'quiet': 'power-saver',
                'custom': 'balanced'
            }
            acpi_mode = acpi_mode_map.get(mode, 'balanced')
            
            success = self._execute_privileged_write(ACPI_PLATFORM_PROFILE, acpi_mode)
            if success:
                decky_plugin.logger.info(f"ACPI platform profile set to: {acpi_mode}")
                return True
        
        decky_plugin.logger.error("No thermal control interface available")
        return False
    
    def get_thermal_mode(self) -> Optional[str]:
        """Get current Legion thermal mode"""
        # Try Legion-specific thermal control first
        if os.path.exists(LEGION_THERMAL_MODE):
            return self._read_sysfs_value(LEGION_THERMAL_MODE)
        
        # Fallback to ACPI platform profile
        if os.path.exists(ACPI_PLATFORM_PROFILE):
            return self._read_sysfs_value(ACPI_PLATFORM_PROFILE)
        
        return None
    
    def enable_custom_tdp_mode(self) -> bool:
        """Enable Legion custom TDP mode with visual indication"""
        success = self.set_thermal_mode('custom')
        if success:
            self._set_power_led_purple()
            decky_plugin.logger.info("Legion custom TDP mode enabled")
        
        return success
    
    def get_device_info(self) -> Dict[str, Any]:
        """Get comprehensive Legion device information"""
        return {
            'device_name': self.device_name,
            'wmi_available': self.wmi_available,
            'thermal_control_available': self.thermal_control_available,
            'current_thermal_mode': self.get_thermal_mode(),
            'power_limits': self.get_power_limits_wmi(),
            'custom_tdp_supported': self.wmi_available
        }

# Global controller instance
_legion_controller = None

def get_legion_controller():
    """Get global Legion controller instance"""
    global _legion_controller
    if _legion_controller is None:
        _legion_controller = LenovoLegionController()
    return _legion_controller

# Convenience functions for backward compatibility
def set_tdp(tdp: int) -> bool:
    """Set Legion TDP (convenience function)"""
    controller = get_legion_controller()
    if controller.wmi_available:
        return controller.set_power_limits_wmi(tdp, tdp, tdp)
    else:
        decky_plugin.logger.error("Legion WMI TDP control not available")
        return False

def get_current_tdp() -> Optional[int]:
    """Get current Legion TDP (convenience function)"""
    controller = get_legion_controller()
    limits = controller.get_power_limits_wmi()
    return limits.get('stapm_limit')

def enable_wmi_tdp_mode() -> bool:
    """Enable Legion WMI TDP mode (convenience function)"""
    controller = get_legion_controller()
    return controller.enable_custom_tdp_mode()
