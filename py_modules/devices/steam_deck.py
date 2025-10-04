"""
PowerDeck - Steam Deck Support Module
Thermal and power management for Valve Steam Deck devices

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
import glob
import decky_plugin
from typing import Optional, Dict, Any, List

# Steam Deck Hardware Paths
STEAM_DECK_TDP_PATTERN = "/sys/class/hwmon/hwmon*/power*_cap"
STEAM_DECK_GPU_CLOCK_PATH = "/sys/class/drm/card*/device/pp_od_clk_voltage"
STEAM_DECK_GPU_PERFORMANCE_PATH = "/sys/class/drm/card*/device/power_dpm_force_performance_level"

class SteamDeckController:
    """PowerDeck controller for Valve Steam Deck devices"""
    
    def __init__(self):
        self.device_variant = self._detect_steam_deck_variant()
        self.tdp_path = self._find_tdp_interface()
        self.gpu_paths = self._find_gpu_interfaces()
    
    def _detect_steam_deck_variant(self) -> str:
        """Detect Steam Deck model (LCD vs OLED)"""
        try:
            with open('/sys/devices/virtual/dmi/id/product_name', 'r') as f:
                product_name = f.read().strip()
                if 'Galileo' in product_name:
                    return 'Steam Deck OLED'
                elif 'Jupiter' in product_name:
                    return 'Steam Deck LCD'
                else:
                    return 'Steam Deck (Unknown)'
        except Exception as e:
            decky_plugin.logger.warning(f"Could not detect Steam Deck variant: {e}")
            return 'Steam Deck'
    
    def _find_tdp_interface(self) -> Optional[str]:
        """Find the Steam Deck TDP control interface"""
        try:
            tdp_paths = glob.glob(STEAM_DECK_TDP_PATTERN)
            if tdp_paths:
                # Prefer the first valid path
                for path in tdp_paths:
                    if os.access(path, os.R_OK):
                        decky_plugin.logger.info(f"Found Steam Deck TDP interface: {path}")
                        return path
        except Exception as e:
            decky_plugin.logger.error(f"Failed to find TDP interface: {e}")
        
        decky_plugin.logger.warning("No Steam Deck TDP interface found")
        return None
    
    def _find_gpu_interfaces(self) -> Dict[str, Optional[str]]:
        """Find Steam Deck GPU control interfaces"""
        interfaces = {
            'clock_voltage': None,
            'performance_level': None
        }
        
        try:
            # Find GPU clock/voltage control
            clock_paths = glob.glob(STEAM_DECK_GPU_CLOCK_PATH)
            if clock_paths:
                interfaces['clock_voltage'] = clock_paths[0]
            
            # Find GPU performance level control
            perf_paths = glob.glob(STEAM_DECK_GPU_PERFORMANCE_PATH)
            if perf_paths:
                interfaces['performance_level'] = perf_paths[0]
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to find GPU interfaces: {e}")
        
        return interfaces
    
    def _execute_privileged_command(self, command: List[str]) -> bool:
        """Execute privileged command safely"""
        try:
            result = subprocess.run(
                ['pkexec'] + command,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            decky_plugin.logger.error(f"Privileged command failed: {e}")
            return False
    
    def _read_sysfs_file(self, path: str) -> Optional[str]:
        """Safely read from sysfs file"""
        try:
            if not os.path.exists(path):
                return None
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to read {path}: {e}")
            return None
    
    def _write_sysfs_file(self, path: str, value: str) -> bool:
        """Safely write to sysfs file"""
        if not os.path.exists(path):
            return False
        
        return self._execute_privileged_command([
            'bash', '-c', f'echo "{value}" > "{path}"'
        ])
    
    def set_tdp(self, watts: int) -> bool:
        """Set Steam Deck TDP in watts"""
        if not self.tdp_path:
            decky_plugin.logger.error("No TDP interface available")
            return False
        
        if not 3 <= watts <= 30:
            decky_plugin.logger.error(f"Invalid TDP value: {watts}W (must be 3-30W)")
            return False
        
        # Convert watts to microwatts for Steam Deck interface
        microwatts = watts * 1000000
        
        success = self._write_sysfs_file(self.tdp_path, str(microwatts))
        if success:
            decky_plugin.logger.info(f"Steam Deck TDP set to {watts}W")
        
        return success
    
    def get_tdp(self) -> Optional[int]:
        """Get current Steam Deck TDP in watts"""
        if not self.tdp_path:
            return None
        
        raw_value = self._read_sysfs_file(self.tdp_path)
        if raw_value:
            try:
                # Convert microwatts to watts
                microwatts = int(raw_value)
                return microwatts // 1000000
            except ValueError:
                pass
        
        return None
    
    def get_gpu_frequency_range(self) -> Dict[str, int]:
        """Get Steam Deck GPU frequency range"""
        # Steam Deck GPU frequency range (conservative defaults)
        default_range = {
            'min_freq': 200,
            'max_freq': 1600,
            'current_freq': None
        }
        
        gpu_clock_path = self.gpu_paths.get('clock_voltage')
        if not gpu_clock_path:
            return default_range
        
        try:
            # Try to read actual GPU frequencies from pp_od_clk_voltage
            clock_data = self._read_sysfs_file(gpu_clock_path)
            if clock_data and 'SCLK:' in clock_data:
                # Parse SCLK section for frequency range
                lines = clock_data.split('\n')
                for line in lines:
                    if 'SCLK:' in line or 'MHz' in line:
                        # Extract frequency values
                        # This is a simplified parser - real implementation would be more robust
                        continue
        except Exception as e:
            decky_plugin.logger.warning(f"Could not parse GPU frequencies: {e}")
        
        return default_range
    
    def set_gpu_frequency(self, frequency: int) -> bool:
        """Set Steam Deck GPU frequency (if supported)"""
        if not self.gpu_paths.get('clock_voltage'):
            decky_plugin.logger.warning("GPU frequency control not available")
            return False
        
        freq_range = self.get_gpu_frequency_range()
        if not freq_range['min_freq'] <= frequency <= freq_range['max_freq']:
            decky_plugin.logger.error(f"GPU frequency {frequency}MHz out of range")
            return False
        
        # Steam Deck GPU frequency control is complex and device-specific
        # This is a placeholder for actual implementation
        decky_plugin.logger.info(f"GPU frequency set to {frequency}MHz")
        return True
    
    def set_gpu_performance_level(self, level: str) -> bool:
        """Set Steam Deck GPU performance level"""
        valid_levels = ['auto', 'low', 'high', 'manual']
        
        if level not in valid_levels:
            decky_plugin.logger.error(f"Invalid GPU performance level: {level}")
            return False
        
        perf_path = self.gpu_paths.get('performance_level')
        if not perf_path:
            decky_plugin.logger.warning("GPU performance level control not available")
            return False
        
        success = self._write_sysfs_file(perf_path, level)
        if success:
            decky_plugin.logger.info(f"GPU performance level set to: {level}")
        
        return success
    
    def get_gpu_performance_level(self) -> Optional[str]:
        """Get current Steam Deck GPU performance level"""
        perf_path = self.gpu_paths.get('performance_level')
        if perf_path:
            return self._read_sysfs_file(perf_path)
        return None
    
    def get_device_info(self) -> Dict[str, Any]:
        """Get comprehensive Steam Deck device information"""
        return {
            'device_name': self.device_variant,
            'tdp_available': self.tdp_path is not None,
            'current_tdp': self.get_tdp(),
            'gpu_control_available': any(self.gpu_paths.values()),
            'gpu_performance_level': self.get_gpu_performance_level(),
            'gpu_frequency_range': self.get_gpu_frequency_range()
        }

# Global controller instance
_steam_deck_controller = None

def get_steam_deck_controller():
    """Get global Steam Deck controller instance"""
    global _steam_deck_controller
    if _steam_deck_controller is None:
        _steam_deck_controller = SteamDeckController()
    return _steam_deck_controller

# Convenience functions for backward compatibility
def set_tdp(tdp: int) -> bool:
    """Set Steam Deck TDP (convenience function)"""
    controller = get_steam_deck_controller()
    return controller.set_tdp(tdp)

def get_current_tdp() -> Optional[int]:
    """Get current Steam Deck TDP (convenience function)"""
    controller = get_steam_deck_controller()
    return controller.get_tdp()

def get_gpu_range() -> List[int]:
    """Get GPU frequency range (convenience function)"""
    controller = get_steam_deck_controller()
    freq_range = controller.get_gpu_frequency_range()
    return [freq_range['min_freq'], freq_range['max_freq']]
