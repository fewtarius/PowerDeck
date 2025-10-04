"""
PowerDeck - ROG Ally Support Module
Thermal and power management for ASUS ROG Ally devices

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
import json
import decky_plugin
from time import sleep
from typing import Optional, Dict, Any, List

# ROG Ally System Paths
ACPI_PLATFORM_PROFILE = '/sys/firmware/acpi/platform_profile'
ACPI_PLATFORM_PROFILE_CHOICES = '/sys/firmware/acpi/platform_profile_choices'
BATTERY_CHARGE_LIMIT = '/sys/class/power_supply/BAT0/charge_control_end_threshold'

# ASUS WMI Base Path
WMI_BASE_PATH = '/sys/devices/platform/asus-nb-wmi'

# ASUS WMI Power Management Paths
WMI_FAST_LIMIT = f'{WMI_BASE_PATH}/ppt_fppt'
WMI_SUSTAINED_LIMIT = f'{WMI_BASE_PATH}/ppt_pl2_sppt'
WMI_STAPM_LIMIT = f'{WMI_BASE_PATH}/ppt_pl1_spl'
WMI_APU_SPPT = f'{WMI_BASE_PATH}/ppt_apu_sppt'
WMI_PLATFORM_SPPT = f'{WMI_BASE_PATH}/ppt_platform_sppt'

# ASUS WMI Thermal and System Controls
WMI_THERMAL_THROTTLE_POLICY = f'{WMI_BASE_PATH}/throttle_thermal_policy'
WMI_NV_TEMP_TARGET = f'{WMI_BASE_PATH}/nv_temp_target'
WMI_MCU_POWERSAVE = f'{WMI_BASE_PATH}/mcu_powersave'
WMI_BOOT_SOUND = f'{WMI_BASE_PATH}/boot_sound'
WMI_CPUFV = f'{WMI_BASE_PATH}/cpufv'

# ASUS WMI Hardware Monitoring Paths
WMI_HWMON_BASE = f'{WMI_BASE_PATH}/hwmon'
WMI_FAN1_PWM = 'pwm1_enable'
WMI_FAN2_PWM = 'pwm2_enable'
WMI_FAN1_INPUT = 'fan1_input'
WMI_FAN2_INPUT = 'fan2_input'
WMI_FAN1_LABEL = 'fan1_label'
WMI_FAN2_LABEL = 'fan2_label'

# ASUS Armoury Crate Firmware Interface
ARMOURY_BASE_PATH = "/sys/devices/virtual/firmware-attributes/asus-armoury/attributes"
ARMOURY_FAST_LIMIT = f"{ARMOURY_BASE_PATH}/ppt_pl3_fppt/current_value"
ARMOURY_SUSTAINED_LIMIT = f"{ARMOURY_BASE_PATH}/ppt_pl2_sppt/current_value"
ARMOURY_STAPM_LIMIT = f"{ARMOURY_BASE_PATH}/ppt_pl1_spl/current_value"
ARMOURY_MCU_POWERSAVE = f"{ARMOURY_BASE_PATH}/mcu_powersave/current_value"
ARMOURY_BOOT_SOUND = f"{ARMOURY_BASE_PATH}/boot_sound/current_value"
ARMOURY_CHARGE_MODE = f"{ARMOURY_BASE_PATH}/charge_mode/current_value"

# AMD GPU Power Management (for ROG Ally iGPU)
AMD_GPU_BASE = '/sys/devices/pci0000:00/0000:00:08.1/0000:64:00.0'
AMD_GPU_POWER_DPM_FORCE = f'{AMD_GPU_BASE}/power_dpm_force_performance_level'
AMD_GPU_POWER_DPM_STATE = f'{AMD_GPU_BASE}/power_dpm_state'
AMD_GPU_THERMAL_THROTTLING = f'{AMD_GPU_BASE}/thermal_throttling_logging'

# System Defaults (matching kernel defaults)
DEFAULT_MCU_POWERSAVE = True
DEFAULT_PLATFORM_PROFILE = 'balanced'
DEFAULT_BATTERY_CHARGE_LIMIT = 100
DEFAULT_THERMAL_THROTTLE_POLICY = 0
DEFAULT_NV_TEMP_TARGET = 75
DEFAULT_BOOT_SOUND = True
DEFAULT_FAN1_PWM_MODE = 2  # Automatic
DEFAULT_FAN2_PWM_MODE = 0  # Disabled/Manual
DEFAULT_CHARGE_MODE = 0    # Standard charging

class ROGAllyController:
    """PowerDeck controller for ASUS ROG Ally devices"""
    
    def __init__(self):
        self.device_name = self._detect_device_variant()
        self.wmi_available = self._check_wmi_support()
        self.armoury_available = self._check_armoury_support()
        self.hwmon_path = self._find_hwmon_path()
        self.amd_gpu_available = self._check_amd_gpu_support()
        
        # Initialize with system defaults
        self._ensure_system_defaults()
    
    def _detect_device_variant(self) -> str:
        """Detect specific ROG Ally model"""
        try:
            with open('/sys/devices/virtual/dmi/id/product_name', 'r') as f:
                product_name = f.read().strip()
                if 'RC72' in product_name:
                    return 'ROG Ally X'
                elif 'RC71' in product_name:
                    return 'ROG Ally'
                else:
                    return 'Unknown ROG Device'
        except Exception as e:
            decky_plugin.logger.warning(f"Could not detect ROG Ally variant: {e}")
            return 'ROG Ally (Unknown)'
    
    def _check_wmi_support(self) -> bool:
        """Check if ASUS WMI power management is available"""
        return all(os.path.exists(path) for path in [
            WMI_FAST_LIMIT, WMI_SUSTAINED_LIMIT, WMI_STAPM_LIMIT
        ])
    
    def _check_armoury_support(self) -> bool:
        """Check if ASUS Armoury Crate interface is available"""
        return all(os.path.exists(path) for path in [
            ARMOURY_FAST_LIMIT, ARMOURY_SUSTAINED_LIMIT, ARMOURY_STAPM_LIMIT
        ])
    
    def _check_amd_gpu_support(self) -> bool:
        """Check if AMD GPU power management is available"""
        return os.path.exists(AMD_GPU_POWER_DPM_FORCE)
    
    def _find_hwmon_path(self) -> Optional[str]:
        """Find the correct hwmon path for ASUS WMI"""
        try:
            # Look for hwmon directory with fan controls
            for hwmon_dir in os.listdir(WMI_HWMON_BASE):
                hwmon_path = os.path.join(WMI_HWMON_BASE, hwmon_dir)
                
                # Check if this hwmon directory has fan controls
                fan1_input = os.path.join(hwmon_path, WMI_FAN1_INPUT)
                if os.path.exists(fan1_input):
                    return hwmon_path
                    
        except Exception as e:
            decky_plugin.logger.warning(f"Could not find ASUS hwmon path: {e}")
        return None
    
    def _ensure_system_defaults(self):
        """Ensure system starts with proper defaults"""
        try:
            # Only set defaults if values are not already configured properly
            current_mcu = self.get_mcu_powersave()
            if current_mcu is None:
                self.set_mcu_powersave(DEFAULT_MCU_POWERSAVE)
            
            current_profile = self.get_platform_profile()
            if current_profile is None:
                self.set_platform_profile(DEFAULT_PLATFORM_PROFILE)
                
        except Exception as e:
            decky_plugin.logger.warning(f"Could not ensure system defaults: {e}")
    
    def _write_sysfs_value(self, path: str, value: str) -> bool:
        """Safely write value to sysfs path"""
        try:
            if not os.path.exists(path):
                return False
            
            result = subprocess.run([
                'pkexec', 'bash', '-c', f'echo "{value}" > "{path}"'
            ], capture_output=True, text=True, timeout=10)
            
            return result.returncode == 0
        except Exception as e:
            decky_plugin.logger.error(f"Failed to write {value} to {path}: {e}")
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
    
    def set_power_limits(self, fast_limit: int, sustained_limit: int, stapm_limit: int) -> bool:
        """Set ROG Ally power limits via preferred interface"""
        success = True
        
        # Convert watts to milliwatts for interfaces that need it
        fast_mw = str(fast_limit * 1000)
        sustained_mw = str(sustained_limit * 1000)
        stapm_mw = str(stapm_limit * 1000)
        
        if self.armoury_available:
            # Use Armoury Crate interface first (more reliable on newer firmware)
            # Note: Armoury interface expects watts, not milliwatts
            success &= self._write_sysfs_value(ARMOURY_FAST_LIMIT, str(fast_limit))
            success &= self._write_sysfs_value(ARMOURY_SUSTAINED_LIMIT, str(sustained_limit))
            success &= self._write_sysfs_value(ARMOURY_STAPM_LIMIT, str(stapm_limit))
        elif self.wmi_available:
            # Fallback to standard WMI interface (expects milliwatts)
            success &= self._write_sysfs_value(WMI_FAST_LIMIT, fast_mw)
            success &= self._write_sysfs_value(WMI_SUSTAINED_LIMIT, sustained_mw)
            success &= self._write_sysfs_value(WMI_STAPM_LIMIT, stapm_mw)
        else:
            decky_plugin.logger.error("No ROG Ally power interface available")
            return False
        
        if success:
            decky_plugin.logger.info(f"ROG Ally power limits set: Fast={fast_limit}W, Sustained={sustained_limit}W, STAPM={stapm_limit}W")
        
        return success
    
    def get_power_limits(self) -> Dict[str, Optional[int]]:
        """Get current ROG Ally power limits"""
        limits = {
            'fast_limit': None,
            'sustained_limit': None,
            'stapm_limit': None
        }
        
        try:
            if self.armoury_available:
                # Armoury interface returns watts directly
                fast_raw = self._read_sysfs_value(ARMOURY_FAST_LIMIT)
                sustained_raw = self._read_sysfs_value(ARMOURY_SUSTAINED_LIMIT)
                stapm_raw = self._read_sysfs_value(ARMOURY_STAPM_LIMIT)
                
                if fast_raw:
                    limits['fast_limit'] = int(fast_raw)
                if sustained_raw:
                    limits['sustained_limit'] = int(sustained_raw)
                if stapm_raw:
                    limits['stapm_limit'] = int(stapm_raw)
                    
            elif self.wmi_available:
                # WMI interface returns milliwatts
                fast_raw = self._read_sysfs_value(WMI_FAST_LIMIT)
                sustained_raw = self._read_sysfs_value(WMI_SUSTAINED_LIMIT)
                stapm_raw = self._read_sysfs_value(WMI_STAPM_LIMIT)
                
                if fast_raw and int(fast_raw) > 0:
                    limits['fast_limit'] = int(fast_raw) // 1000
                if sustained_raw and int(sustained_raw) > 0:
                    limits['sustained_limit'] = int(sustained_raw) // 1000
                if stapm_raw and int(stapm_raw) > 0:
                    limits['stapm_limit'] = int(stapm_raw) // 1000
                    
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read ROG Ally power limits: {e}")
        
        return limits
    
    def set_extended_power_limits(self, apu_sppt: Optional[int] = None, 
                                platform_sppt: Optional[int] = None) -> bool:
        """Set extended ROG Ally power limits (APU and Platform SPPT)"""
        success = True
        
        if apu_sppt is not None:
            apu_mw = str(apu_sppt * 1000)
            success &= self._write_sysfs_value(WMI_APU_SPPT, apu_mw)
            
        if platform_sppt is not None:
            platform_mw = str(platform_sppt * 1000)
            success &= self._write_sysfs_value(WMI_PLATFORM_SPPT, platform_mw)
        
        if success and (apu_sppt is not None or platform_sppt is not None):
            decky_plugin.logger.info(f"ROG Ally extended power limits set: APU SPPT={apu_sppt}W, Platform SPPT={platform_sppt}W")
        
        return success
    
    def get_extended_power_limits(self) -> Dict[str, Optional[int]]:
        """Get extended ROG Ally power limits"""
        limits = {
            'apu_sppt': None,
            'platform_sppt': None
        }
        
        try:
            apu_raw = self._read_sysfs_value(WMI_APU_SPPT)
            platform_raw = self._read_sysfs_value(WMI_PLATFORM_SPPT)
            
            if apu_raw and int(apu_raw) > 0:
                limits['apu_sppt'] = int(apu_raw) // 1000
            if platform_raw and int(platform_raw) > 0:
                limits['platform_sppt'] = int(platform_raw) // 1000
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read ROG Ally extended power limits: {e}")
        
        return limits
    
    def set_platform_profile(self, profile: str) -> bool:
        """Set ACPI platform profile for thermal management"""
        # Map PowerDeck profiles to system profiles
        profile_map = {
            'power-saver': 'low-power',
            'balanced': 'balanced', 
            'performance': 'performance'
        }
        
        # Use mapped profile or original if not in map
        system_profile = profile_map.get(profile, profile)
        
        # Validate against available choices
        choices = self.get_platform_profile_choices()
        if choices and system_profile not in choices:
            decky_plugin.logger.error(f"Invalid platform profile: {system_profile}. Available: {choices}")
            return False
        
        success = self._write_sysfs_value(ACPI_PLATFORM_PROFILE, system_profile)
        if success:
            decky_plugin.logger.info(f"ROG Ally platform profile set to: {system_profile}")
        
        return success
    
    def get_platform_profile(self) -> Optional[str]:
        """Get current ACPI platform profile"""
        return self._read_sysfs_value(ACPI_PLATFORM_PROFILE)
    
    def get_platform_profile_choices(self) -> Optional[List[str]]:
        """Get available ACPI platform profile choices"""
        choices_str = self._read_sysfs_value(ACPI_PLATFORM_PROFILE_CHOICES)
        if choices_str:
            return choices_str.split()
        return None
    
    def set_battery_charge_limit(self, limit: int) -> bool:
        """Set battery charge limit (20-100%)"""
        if not 20 <= limit <= 100:
            decky_plugin.logger.error(f"Invalid charge limit: {limit}% (must be 20-100%)")
            return False
        
        success = self._write_sysfs_value(BATTERY_CHARGE_LIMIT, str(limit))
        if success:
            decky_plugin.logger.info(f"ROG Ally battery charge limit set to: {limit}%")
        
        return success
    
    def get_battery_charge_limit(self) -> Optional[int]:
        """Get current battery charge limit"""
        limit_str = self._read_sysfs_value(BATTERY_CHARGE_LIMIT)
        if limit_str:
            try:
                return int(limit_str)
            except ValueError:
                pass
        return None
    
    def set_mcu_powersave(self, enabled: bool) -> bool:
        """Enable/disable MCU power saving mode"""
        value = "1" if enabled else "0"
        
        # Try Armoury interface first, then WMI
        success = False
        if self.armoury_available:
            success = self._write_sysfs_value(ARMOURY_MCU_POWERSAVE, value)
        
        if not success and self.wmi_available:
            success = self._write_sysfs_value(WMI_MCU_POWERSAVE, value)
        
        if success:
            state = "enabled" if enabled else "disabled"
            decky_plugin.logger.info(f"ROG Ally MCU power save {state}")
        
        return success
    
    def get_mcu_powersave(self) -> Optional[bool]:
        """Get MCU power saving mode status"""
        value = None
        
        # Try Armoury interface first, then WMI
        if self.armoury_available:
            value = self._read_sysfs_value(ARMOURY_MCU_POWERSAVE)
        
        if value is None and self.wmi_available:
            value = self._read_sysfs_value(WMI_MCU_POWERSAVE)
        
        if value is not None:
            try:
                return bool(int(value))
            except ValueError:
                pass
        return None
    
    def set_thermal_throttle_policy(self, policy: int) -> bool:
        """Set thermal throttling policy (0-3)"""
        if not 0 <= policy <= 3:
            decky_plugin.logger.error(f"Invalid thermal throttle policy: {policy} (must be 0-3)")
            return False
        
        success = self._write_sysfs_value(WMI_THERMAL_THROTTLE_POLICY, str(policy))
        if success:
            decky_plugin.logger.info(f"ROG Ally thermal throttle policy set to: {policy}")
        
        return success
    
    def get_thermal_throttle_policy(self) -> Optional[int]:
        """Get current thermal throttling policy"""
        value = self._read_sysfs_value(WMI_THERMAL_THROTTLE_POLICY)
        if value is not None:
            try:
                return int(value)
            except ValueError:
                pass
        return None
    
    def set_nv_temp_target(self, temp: int) -> bool:
        """Set NV (GPU) temperature target in Celsius"""
        if not 60 <= temp <= 95:
            decky_plugin.logger.error(f"Invalid NV temp target: {temp}°C (must be 60-95°C)")
            return False
        
        success = self._write_sysfs_value(WMI_NV_TEMP_TARGET, str(temp))
        if success:
            decky_plugin.logger.info(f"ROG Ally NV temperature target set to: {temp}°C")
        
        return success
    
    def get_nv_temp_target(self) -> Optional[int]:
        """Get current NV (GPU) temperature target"""
        value = self._read_sysfs_value(WMI_NV_TEMP_TARGET)
        if value is not None:
            try:
                return int(value)
            except ValueError:
                pass
        return None
    
    def set_boot_sound(self, enabled: bool) -> bool:
        """Enable/disable boot sound"""
        value = "1" if enabled else "0"
        
        # Try Armoury interface first, then WMI
        success = False
        if self.armoury_available:
            success = self._write_sysfs_value(ARMOURY_BOOT_SOUND, value)
        
        if not success and self.wmi_available:
            success = self._write_sysfs_value(WMI_BOOT_SOUND, value)
        
        if success:
            state = "enabled" if enabled else "disabled"
            decky_plugin.logger.info(f"ROG Ally boot sound {state}")
        
        return success
    
    def get_boot_sound(self) -> Optional[bool]:
        """Get boot sound status"""
        value = None
        
        # Try Armoury interface first, then WMI
        if self.armoury_available:
            value = self._read_sysfs_value(ARMOURY_BOOT_SOUND)
        
        if value is None and self.wmi_available:
            value = self._read_sysfs_value(WMI_BOOT_SOUND)
        
        if value is not None:
            try:
                return bool(int(value))
            except ValueError:
                pass
        return None
    
    def set_charge_mode(self, mode: int) -> bool:
        """Set battery charge mode 
        
        Note: Charge mode values may vary by firmware version.
        Common values: 0=Standard, 1=Balanced, 2=Maximum Lifespan
        """
        if self.armoury_available:
            success = self._write_sysfs_value(ARMOURY_CHARGE_MODE, str(mode))
            if success:
                decky_plugin.logger.info(f"ROG Ally charge mode set to: {mode}")
            return success
        else:
            decky_plugin.logger.error("Charge mode control requires Armoury Crate interface")
            return False
    
    def get_charge_mode(self) -> Optional[int]:
        """Get current battery charge mode
        
        Note: Return value may vary by firmware version.
        Check ROG Ally documentation for current firmware charge mode values.
        """
        if self.armoury_available:
            value = self._read_sysfs_value(ARMOURY_CHARGE_MODE)
            if value is not None:
                try:
                    return int(value)
                except ValueError:
                    pass
        return None
    
    def set_fan_mode(self, fan_id: int, mode: int) -> bool:
        """Set fan PWM mode (0=manual, 1=auto-low, 2=auto-normal, 3=auto-high)"""
        if fan_id not in [1, 2]:
            decky_plugin.logger.error(f"Invalid fan ID: {fan_id} (must be 1 or 2)")
            return False
        
        if not 0 <= mode <= 3:
            decky_plugin.logger.error(f"Invalid fan mode: {mode} (must be 0-3)")
            return False
        
        if not self.hwmon_path:
            decky_plugin.logger.error("No ASUS hwmon interface available")
            return False
        
        pwm_file = WMI_FAN1_PWM if fan_id == 1 else WMI_FAN2_PWM
        pwm_path = os.path.join(self.hwmon_path, pwm_file)
        
        success = self._write_sysfs_value(pwm_path, str(mode))
        if success:
            fan_name = "CPU" if fan_id == 1 else "GPU"
            mode_names = ['Manual', 'Auto Low', 'Auto Normal', 'Auto High']
            decky_plugin.logger.info(f"ROG Ally {fan_name} fan mode set to: {mode_names[mode]}")
        
        return success
    
    def get_fan_status(self) -> Dict[str, Any]:
        """Get comprehensive fan status"""
        status = {
            'cpu_fan': {'speed': None, 'mode': None, 'label': None},
            'gpu_fan': {'speed': None, 'mode': None, 'label': None}
        }
        
        if not self.hwmon_path:
            return status
        
        try:
            # CPU Fan (Fan 1)
            fan1_speed = self._read_sysfs_value(os.path.join(self.hwmon_path, WMI_FAN1_INPUT))
            fan1_mode = self._read_sysfs_value(os.path.join(self.hwmon_path, WMI_FAN1_PWM))
            fan1_label = self._read_sysfs_value(os.path.join(self.hwmon_path, WMI_FAN1_LABEL))
            
            if fan1_speed:
                status['cpu_fan']['speed'] = int(fan1_speed)
            if fan1_mode:
                status['cpu_fan']['mode'] = int(fan1_mode)
            if fan1_label:
                status['cpu_fan']['label'] = fan1_label
            
            # GPU Fan (Fan 2)
            fan2_speed = self._read_sysfs_value(os.path.join(self.hwmon_path, WMI_FAN2_INPUT))
            fan2_mode = self._read_sysfs_value(os.path.join(self.hwmon_path, WMI_FAN2_PWM))
            fan2_label = self._read_sysfs_value(os.path.join(self.hwmon_path, WMI_FAN2_LABEL))
            
            if fan2_speed:
                status['gpu_fan']['speed'] = int(fan2_speed)
            if fan2_mode:
                status['gpu_fan']['mode'] = int(fan2_mode)
            if fan2_label:
                status['gpu_fan']['label'] = fan2_label
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read fan status: {e}")
        
        return status
    
    def set_amd_gpu_power_mode(self, mode: str) -> bool:
        """Set AMD GPU power management mode"""
        valid_modes = ['auto', 'low', 'high', 'manual', 'profile_standard', 
                      'profile_min_sclk', 'profile_min_mclk', 'profile_peak']
        
        if mode not in valid_modes:
            decky_plugin.logger.error(f"Invalid AMD GPU power mode: {mode}. Valid: {valid_modes}")
            return False
        
        if not self.amd_gpu_available:
            decky_plugin.logger.error("AMD GPU power management not available")
            return False
        
        success = self._write_sysfs_value(AMD_GPU_POWER_DPM_FORCE, mode)
        if success:
            decky_plugin.logger.info(f"AMD GPU power mode set to: {mode}")
        
        return success
    
    def get_amd_gpu_power_mode(self) -> Optional[str]:
        """Get current AMD GPU power management mode"""
        if self.amd_gpu_available:
            return self._read_sysfs_value(AMD_GPU_POWER_DPM_FORCE)
        return None
    
    def get_amd_gpu_status(self) -> Dict[str, Any]:
        """Get AMD GPU power and thermal status"""
        status = {
            'power_mode': None,
            'power_state': None,
            'thermal_throttling_enabled': None
        }
        
        if not self.amd_gpu_available:
            return status
        
        try:
            status['power_mode'] = self._read_sysfs_value(AMD_GPU_POWER_DPM_FORCE)
            status['power_state'] = self._read_sysfs_value(AMD_GPU_POWER_DPM_STATE)
            
            # Parse thermal throttling logging output
            thermal_raw = self._read_sysfs_value(AMD_GPU_THERMAL_THROTTLING)
            if thermal_raw:
                # Expected format: "0000:64:00.0: thermal throttling logging enabled, with interval 60 seconds"
                if 'enabled' in thermal_raw.lower():
                    status['thermal_throttling_enabled'] = True
                elif 'disabled' in thermal_raw.lower():
                    status['thermal_throttling_enabled'] = False
                    
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read AMD GPU status: {e}")
        
        return status
    def set_cpu_fv_override(self, override_data: str) -> bool:
        """Set CPU frequency/voltage override (advanced users only)"""
        if not override_data:
            decky_plugin.logger.error("CPU FV override data cannot be empty")
            return False
        
        success = self._write_sysfs_value(WMI_CPUFV, override_data)
        if success:
            decky_plugin.logger.info("CPU frequency/voltage override applied")
            decky_plugin.logger.warning("CPU FV override is experimental - monitor system stability")
        
        return success
    
    def get_device_info(self) -> Dict[str, Any]:
        """Get comprehensive ROG Ally device information"""
        info = {
            'device_name': self.device_name,
            'available_controls': {
                'platform_profiles': True,
                'thermal_policy': True,
                'fan_control': True,
                'battery_management': True,
                'mcu_powersave': True,
                'power_limits': True,
                'boot_sound': True,
                'amd_gpu_control': self.amd_gpu_available
            },
            'interfaces': {
                'wmi_available': self.wmi_available,
                'armoury_available': self.armoury_available,
                'amd_gpu_available': self.amd_gpu_available,
                'hwmon_path': self.hwmon_path
            },
            'power_management': {
                'platform_profile': self.get_platform_profile(),
                'platform_profile_choices': self.get_platform_profile_choices(),
                'power_limits': self.get_power_limits(),
                'extended_power_limits': self.get_extended_power_limits(),
                'mcu_powersave': self.get_mcu_powersave(),
                'thermal_throttle_policy': self.get_thermal_throttle_policy(),
                'nv_temp_target': self.get_nv_temp_target()
            },
            'battery': {
                'charge_limit': self.get_battery_charge_limit(),
                'charge_mode': self.get_charge_mode()
            },
            'thermal': {
                'fan_status': self.get_fan_status(),
                'amd_gpu_status': self.get_amd_gpu_status()
            },
            'system': {
                'boot_sound': self.get_boot_sound()
            }
        }
        
        return info
    
    def restore_defaults(self) -> bool:
        """Restore all ROG Ally settings to system defaults"""
        success = True
        
        try:
            # Restore power management defaults
            success &= self.set_mcu_powersave(DEFAULT_MCU_POWERSAVE)
            success &= self.set_platform_profile(DEFAULT_PLATFORM_PROFILE)
            success &= self.set_thermal_throttle_policy(DEFAULT_THERMAL_THROTTLE_POLICY)
            success &= self.set_nv_temp_target(DEFAULT_NV_TEMP_TARGET)
            
            # Restore battery defaults
            success &= self.set_battery_charge_limit(DEFAULT_BATTERY_CHARGE_LIMIT)
            success &= self.set_charge_mode(DEFAULT_CHARGE_MODE)
            
            # Restore system defaults
            success &= self.set_boot_sound(DEFAULT_BOOT_SOUND)
            
            # Restore fan defaults
            success &= self.set_fan_mode(1, DEFAULT_FAN1_PWM_MODE)  # CPU fan
            success &= self.set_fan_mode(2, DEFAULT_FAN2_PWM_MODE)  # GPU fan
            
            # Restore AMD GPU defaults
            if self.amd_gpu_available:
                success &= self.set_amd_gpu_power_mode('auto')
            
            if success:
                decky_plugin.logger.info("ROG Ally settings restored to defaults")
            else:
                decky_plugin.logger.warning("Some ROG Ally default settings could not be restored")
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to restore ROG Ally defaults: {e}")
            success = False
        
        return success

# Global controller instance
_rog_ally_controller = None

def get_rog_ally_controller():
    """Get global ROG Ally controller instance"""
    global _rog_ally_controller
    if _rog_ally_controller is None:
        _rog_ally_controller = ROGAllyController()
    return _rog_ally_controller

# Convenience functions for backward compatibility
def set_tdp(tdp: int) -> bool:
    """Set ROG Ally TDP (convenience function)"""
    controller = get_rog_ally_controller()
    # Set all power limits to TDP value for simplicity
    return controller.set_power_limits(tdp, tdp, tdp)

def get_current_tdp() -> Optional[int]:
    """Get current ROG Ally TDP (convenience function)"""
    controller = get_rog_ally_controller()
    limits = controller.get_power_limits()
    return limits.get('stapm_limit')

def set_mcu_powersave(enabled: bool) -> bool:
    """Legacy function for MCU power save control"""
    controller = get_rog_ally_controller()
    return controller.set_mcu_powersave(enabled)

def get_mcu_powersave() -> Optional[bool]:
    """Legacy function for MCU power save status"""
    controller = get_rog_ally_controller()
    return controller.get_mcu_powersave()

# Enhanced convenience functions
def set_performance_mode(mode: str) -> bool:
    """Set comprehensive performance mode (low-power/balanced/performance)"""
    controller = get_rog_ally_controller()
    success = True
    
    if mode == 'low-power':
        success &= controller.set_platform_profile('low-power')
        success &= controller.set_mcu_powersave(True)
        success &= controller.set_thermal_throttle_policy(1)  # Conservative
        success &= controller.set_fan_mode(1, 1)  # CPU fan auto-low
        if controller.amd_gpu_available:
            success &= controller.set_amd_gpu_power_mode('low')
    elif mode == 'balanced':
        success &= controller.set_platform_profile('balanced')
        success &= controller.set_mcu_powersave(True)
        success &= controller.set_thermal_throttle_policy(0)  # Auto
        success &= controller.set_fan_mode(1, 2)  # CPU fan auto-normal
        if controller.amd_gpu_available:
            success &= controller.set_amd_gpu_power_mode('auto')
    elif mode == 'performance':
        success &= controller.set_platform_profile('performance')
        success &= controller.set_mcu_powersave(False)
        success &= controller.set_thermal_throttle_policy(0)  # Auto
        success &= controller.set_fan_mode(1, 3)  # CPU fan auto-high
        if controller.amd_gpu_available:
            success &= controller.set_amd_gpu_power_mode('high')
    else:
        decky_plugin.logger.error(f"Invalid performance mode: {mode}")
        return False
    
    return success

def get_comprehensive_status() -> Dict[str, Any]:
    """Get complete ROG Ally system status"""
    controller = get_rog_ally_controller()
    return controller.get_device_info()
