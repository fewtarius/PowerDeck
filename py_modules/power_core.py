"""
Modern Power Management Core
Handles all power-related operations with proper abstraction and device detection
"""
import os
import subprocess
import shutil
import decky_plugin
from enum import Enum, IntEnum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Tuple
from abc import ABC, abstractmethod
import json
import time

class PowerProfile(IntEnum):
    """Standard power profiles for easy user selection"""
    BATTERY_SAVER = 0
    BALANCED = 1
    PERFORMANCE = 2
    GAMING = 3
    CUSTOM = 4

class TDPMethod(Enum):
    """Methods for setting TDP on different devices"""
    RYZENADJ = "ryzenadj"
    INTEL_RAPL = "intel_rapl"
    STEAM_DECK = "steam_deck"
    ASUS_WMI = "asus_wmi"
    LENOVO_WMI = "lenovo_wmi"

class CPUVendor(Enum):
    """CPU Vendor detection"""
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"

class ScalingDriver(Enum):
    """CPU scaling drivers"""
    INTEL_PSTATE = "intel_pstate"
    INTEL_CPUFREQ = "intel_cpufreq"
    AMD_PSTATE_EPP = "amd-pstate-epp"
    AMD_PSTATE = "amd-pstate"
    ACPI_CPUFREQ = "acpi-cpufreq"

@dataclass
class PowerLimits:
    """Power limit configuration for ryzenadj"""
    stapm_limit: Optional[int] = None          # Sustained Power Limit (mW)
    fast_limit: Optional[int] = None           # PPT LIMIT FAST (mW)
    slow_limit: Optional[int] = None           # PPT LIMIT SLOW (mW)
    slow_time: Optional[int] = None            # Slow PPT Constant Time (s)
    stapm_time: Optional[int] = None           # STAPM constant time (s)
    apu_slow_limit: Optional[int] = None       # APU PPT Slow Power limit (mW)

@dataclass
class TemperatureLimits:
    """Temperature limit configuration"""
    tctl_temp: Optional[int] = None            # Tctl Temperature Limit (°C)
    apu_skin_temp: Optional[int] = None        # APU Skin Temperature Limit (°C)
    dgpu_skin_temp: Optional[int] = None       # dGPU Skin Temperature Limit (°C)
    skin_temp_limit: Optional[int] = None      # Skin Temperature Power Limit (mW)

@dataclass
class CurrentLimits:
    """Current limit configuration"""
    vrm_current: Optional[int] = None          # VRM Current Limit - TDC LIMIT VDD (mA)
    vrmsoc_current: Optional[int] = None       # VRM SoC Current Limit - TDC LIMIT SoC (mA)
    vrmgfx_current: Optional[int] = None       # VRM GFX Current Limit - TDC LIMIT GFX (mA)
    vrmcvip_current: Optional[int] = None      # VRM CVIP Current Limit - TDC LIMIT CVIP (mA)
    vrmmax_current: Optional[int] = None       # VRM Maximum Current Limit - EDC LIMIT VDD (mA)
    vrmsocmax_current: Optional[int] = None    # VRM SoC Maximum Current Limit - EDC LIMIT SoC (mA)
    vrmgfxmax_current: Optional[int] = None    # VRM GFX Maximum Current Limit - EDC LIMIT GFX (mA)
    psi0_current: Optional[int] = None         # PSI0 VDD Current Limit (mA)
    psi3cpu_current: Optional[int] = None      # PSI3 CPU Current Limit (mA)
    psi0soc_current: Optional[int] = None      # PSI0 SoC Current Limit (mA)
    psi3gfx_current: Optional[int] = None      # PSI3 GFX Current Limit (mA)

@dataclass
class ClockLimits:
    """Clock frequency limits configuration"""
    max_socclk_frequency: Optional[int] = None    # Maximum SoC Clock Frequency (MHz)
    min_socclk_frequency: Optional[int] = None    # Minimum SoC Clock Frequency (MHz)
    max_fclk_frequency: Optional[int] = None      # Maximum Transmission (CPU-GPU) Frequency (MHz)
    min_fclk_frequency: Optional[int] = None      # Minimum Transmission (CPU-GPU) Frequency (MHz)
    max_vcn: Optional[int] = None                 # Maximum Video Core Next (VCE) (MHz)
    min_vcn: Optional[int] = None                 # Minimum Video Core Next (VCE) (MHz)
    max_lclk: Optional[int] = None                # Maximum Data Launch Clock (MHz)
    min_lclk: Optional[int] = None                # Minimum Data Launch Clock (MHz)
    max_gfxclk: Optional[int] = None              # Maximum GFX Clock (MHz)
    min_gfxclk: Optional[int] = None              # Minimum GFX Clock (MHz)

@dataclass
class AdvancedControls:
    """Advanced ryzenadj controls"""
    prochot_deassertion_ramp: Optional[int] = None  # Ramp Time After Prochot
    gfx_clk: Optional[int] = None                   # Forced Clock Speed MHz (Renoir Only)
    oc_clk: Optional[int] = None                    # Forced Core Clock Speed MHz
    oc_volt: Optional[int] = None                   # Forced Core VID
    enable_oc: bool = False                         # Enable OC
    set_coall: Optional[int] = None                 # All core Curve Optimiser
    set_coper: Optional[int] = None                 # Per core Curve Optimiser
    set_cogfx: Optional[int] = None                 # iGPU Curve Optimiser
    power_saving: bool = False                      # Power efficiency mode
    max_performance: bool = False                   # Performance mode

@dataclass
class RyzenadjConfiguration:
    """Complete ryzenadj configuration"""
    power_limits: PowerLimits = field(default_factory=PowerLimits)
    temperature_limits: TemperatureLimits = field(default_factory=TemperatureLimits)
    current_limits: CurrentLimits = field(default_factory=CurrentLimits)
    clock_limits: ClockLimits = field(default_factory=ClockLimits)
    advanced_controls: AdvancedControls = field(default_factory=AdvancedControls)

@dataclass
class DeviceCapabilities:
    """Device-specific capabilities and limits"""
    name: str
    cpu_vendor: CPUVendor
    tdp_method: TDPMethod
    min_tdp: int = 3
    max_tdp: int = 15
    supports_gpu_control: bool = False
    supports_cpu_boost: bool = True
    supports_smt: bool = True
    supports_epp: bool = False
    supports_governor: bool = True
    scaling_driver: Optional[ScalingDriver] = None
    gpu_frequency_range: Optional[Tuple[int, int]] = None
    ryzenadj_path: Optional[str] = None

class PowerManager(ABC):
    """Abstract base class for power management implementations"""
    
    @abstractmethod
    def set_tdp(self, watts: int) -> bool:
        """Set TDP in watts"""
        pass
    
    @abstractmethod
    def get_current_tdp(self) -> Optional[int]:
        """Get current TDP setting"""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> DeviceCapabilities:
        """Get device capabilities"""
        pass

class RyzenadjManager(PowerManager):
    """Ryzenadj-based power management"""
    
    def __init__(self):
        self._ryzenadj_path = self._find_ryzenadj()
        self._capabilities = self._detect_capabilities()
    
    def _find_ryzenadj(self) -> Optional[str]:
        """Find ryzenadj executable"""
        search_paths = [
            f'{decky_plugin.DECKY_USER_HOME}/.local/bin/ryzenadj',
            f'{decky_plugin.DECKY_USER_HOME}/.nix-profile/bin/ryzenadj',
            f'{decky_plugin.DECKY_USER_HOME}/homebrew/plugins/PowerDeck/bin/ryzenadj'
        ]
        
        # Check local paths first
        for path in search_paths:
            if os.path.exists(path):
                return path
        
        # Check system PATH
        path = shutil.which('ryzenadj')
        if path:
            return path
        
        return None
    
    def _detect_capabilities(self) -> DeviceCapabilities:
        """Detect device capabilities"""
        # This would be enhanced with proper device detection
        return DeviceCapabilities(
            name="Generic AMD Device",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=3,
            max_tdp=40,
            supports_gpu_control=True,
            ryzenadj_path=self._ryzenadj_path
        )
    
    def set_tdp(self, watts: int) -> bool:
        """Set TDP using ryzenadj"""
        if not self._ryzenadj_path:
            decky_plugin.logger.error("ryzenadj not found")
            return False
        
        # Basic TDP configuration with new architecture
        config = RyzenadjConfiguration()
        
        # Convert watts to milliwatts
        milliwatts = watts * 1000
        
        # Set primary power limits
        config.power_limits.stapm_limit = milliwatts
        config.power_limits.fast_limit = milliwatts
        config.power_limits.slow_limit = milliwatts
        
        # Set safe temperature limits
        config.temperature_limits.tctl_temp = 95
        config.temperature_limits.apu_skin_temp = 95
        config.temperature_limits.dgpu_skin_temp = 95
        
        return self._execute_ryzenadj(config)
    
    def _execute_ryzenadj(self, config: RyzenadjConfiguration) -> bool:
        """Execute ryzenadj with configuration"""
        if not self._ryzenadj_path:
            return False
        
        cmd = [self._ryzenadj_path]
        
        # Build command arguments from configuration
        self._add_power_limits(cmd, config.power_limits)
        self._add_temperature_limits(cmd, config.temperature_limits)
        self._add_current_limits(cmd, config.current_limits)
        self._add_clock_limits(cmd, config.clock_limits)
        self._add_advanced_controls(cmd, config.advanced_controls)
        
        try:
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = ""
            
            result = subprocess.run(
                cmd, 
                check=True, 
                text=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                env=env,
                timeout=10
            )
            
            decky_plugin.logger.info(f"ryzenadj executed successfully: {' '.join(cmd)}")
            return True
            
        except subprocess.CalledProcessError as e:
            decky_plugin.logger.error(f"ryzenadj failed: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            decky_plugin.logger.error("ryzenadj timed out")
            return False
        except Exception as e:
            decky_plugin.logger.error(f"ryzenadj execution error: {e}")
            return False
    
    def _add_power_limits(self, cmd: List[str], limits: PowerLimits):
        """Add power limit arguments"""
        if limits.stapm_limit:
            cmd.extend(['--stapm-limit', str(limits.stapm_limit)])
        if limits.fast_limit:
            cmd.extend(['--fast-limit', str(limits.fast_limit)])
        if limits.slow_limit:
            cmd.extend(['--slow-limit', str(limits.slow_limit)])
        if limits.slow_time:
            cmd.extend(['--slow-time', str(limits.slow_time)])
        if limits.stapm_time:
            cmd.extend(['--stapm-time', str(limits.stapm_time)])
        if limits.apu_slow_limit:
            cmd.extend(['--apu-slow-limit', str(limits.apu_slow_limit)])
    
    def _add_temperature_limits(self, cmd: List[str], limits: TemperatureLimits):
        """Add temperature limit arguments"""
        if limits.tctl_temp:
            cmd.extend(['--tctl-temp', str(limits.tctl_temp)])
        if limits.apu_skin_temp:
            cmd.extend(['--apu-skin-temp', str(limits.apu_skin_temp)])
        if limits.dgpu_skin_temp:
            cmd.extend(['--dgpu-skin-temp', str(limits.dgpu_skin_temp)])
        if limits.skin_temp_limit:
            cmd.extend(['--skin-temp-limit', str(limits.skin_temp_limit)])
    
    def _add_current_limits(self, cmd: List[str], limits: CurrentLimits):
        """Add current limit arguments"""
        if limits.vrm_current:
            cmd.extend(['--vrm-current', str(limits.vrm_current)])
        if limits.vrmsoc_current:
            cmd.extend(['--vrmsoc-current', str(limits.vrmsoc_current)])
        if limits.vrmgfx_current:
            cmd.extend(['--vrmgfx-current', str(limits.vrmgfx_current)])
        if limits.vrmcvip_current:
            cmd.extend(['--vrmcvip-current', str(limits.vrmcvip_current)])
        if limits.vrmmax_current:
            cmd.extend(['--vrmmax-current', str(limits.vrmmax_current)])
        if limits.vrmsocmax_current:
            cmd.extend(['--vrmsocmax-current', str(limits.vrmsocmax_current)])
        if limits.vrmgfxmax_current:
            cmd.extend(['--vrmgfxmax_current', str(limits.vrmgfxmax_current)])
        if limits.psi0_current:
            cmd.extend(['--psi0-current', str(limits.psi0_current)])
        if limits.psi3cpu_current:
            cmd.extend(['--psi3cpu_current', str(limits.psi3cpu_current)])
        if limits.psi0soc_current:
            cmd.extend(['--psi0soc-current', str(limits.psi0soc_current)])
        if limits.psi3gfx_current:
            cmd.extend(['--psi3gfx_current', str(limits.psi3gfx_current)])
    
    def _add_clock_limits(self, cmd: List[str], limits: ClockLimits):
        """Add clock limit arguments"""
        if limits.max_socclk_frequency:
            cmd.extend(['--max-socclk-frequency', str(limits.max_socclk_frequency)])
        if limits.min_socclk_frequency:
            cmd.extend(['--min-socclk-frequency', str(limits.min_socclk_frequency)])
        if limits.max_fclk_frequency:
            cmd.extend(['--max-fclk-frequency', str(limits.max_fclk_frequency)])
        if limits.min_fclk_frequency:
            cmd.extend(['--min-fclk-frequency', str(limits.min_fclk_frequency)])
        if limits.max_vcn:
            cmd.extend(['--max-vcn', str(limits.max_vcn)])
        if limits.min_vcn:
            cmd.extend(['--min-vcn', str(limits.min_vcn)])
        if limits.max_lclk:
            cmd.extend(['--max-lclk', str(limits.max_lclk)])
        if limits.min_lclk:
            cmd.extend(['--min-lclk', str(limits.min_lclk)])
        if limits.max_gfxclk:
            cmd.extend(['--max-gfxclk', str(limits.max_gfxclk)])
        if limits.min_gfxclk:
            cmd.extend(['--min-gfxclk', str(limits.min_gfxclk)])
    
    def _add_advanced_controls(self, cmd: List[str], controls: AdvancedControls):
        """Add advanced control arguments"""
        if controls.prochot_deassertion_ramp:
            cmd.extend(['--prochot-deassertion-ramp', str(controls.prochot_deassertion_ramp)])
        if controls.gfx_clk:
            cmd.extend(['--gfx-clk', str(controls.gfx_clk)])
        if controls.oc_clk:
            cmd.extend(['--oc-clk', str(controls.oc_clk)])
        if controls.oc_volt:
            cmd.extend(['--oc-volt', str(controls.oc_volt)])
        if controls.enable_oc:
            cmd.append('--enable-oc')
        if controls.set_coall:
            cmd.extend(['--set-coall', str(controls.set_coall)])
        if controls.set_coper:
            cmd.extend(['--set-coper', str(controls.set_coper)])
        if controls.set_cogfx:
            cmd.extend(['--set-cogfx', str(controls.set_cogfx)])
        if controls.power_saving:
            cmd.append('--power-saving')
        if controls.max_performance:
            cmd.append('--max-performance')
    
    def get_current_tdp(self) -> Optional[int]:
        """Get current TDP (not directly available from ryzenadj)"""
        return None
    
    def get_capabilities(self) -> DeviceCapabilities:
        """Get device capabilities"""
        return self._capabilities
    
    def configure_advanced(self, config: RyzenadjConfiguration) -> bool:
        """Apply advanced ryzenadj configuration"""
        return self._execute_ryzenadj(config)

class IntelRAPLManager(PowerManager):
    """Intel RAPL-based power management"""
    
    def __init__(self):
        self._capabilities = self._detect_capabilities()
        self._tdp_path = self._find_tdp_path()
    
    def _find_tdp_path(self) -> Optional[str]:
        """Find Intel RAPL TDP control path"""
        paths = [
            "/sys/devices/virtual/powercap/intel-rapl-mmio/intel-rapl-mmio:0/constraint_*_power_limit_uw",
            "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/constraint_*_power_limit_uw"
        ]
        
        for path_pattern in paths:
            # Check if the pattern exists (would need glob expansion in real implementation)
            base_path = path_pattern.replace('/constraint_*_power_limit_uw', '')
            if os.path.exists(base_path):
                return path_pattern
        
        return None
    
    def _detect_capabilities(self) -> DeviceCapabilities:
        """Detect Intel device capabilities"""
        return DeviceCapabilities(
            name="Intel Device",
            cpu_vendor=CPUVendor.INTEL,
            tdp_method=TDPMethod.INTEL_RAPL,
            min_tdp=4,
            max_tdp=40,
            supports_gpu_control=False,  # Limited iGPU control
            supports_epp=True,
            scaling_driver=ScalingDriver.INTEL_PSTATE
        )
    
    def set_tdp(self, watts: int) -> bool:
        """Set TDP using Intel RAPL"""
        if not self._tdp_path:
            decky_plugin.logger.error("Intel RAPL TDP path not found")
            return False
        
        microwatts = watts * 1_000_000
        
        try:
            # In real implementation, would use glob to find actual constraint files
            # For now, this is a placeholder
            decky_plugin.logger.info(f"Would set Intel TDP to {watts}W ({microwatts}μW)")
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set Intel TDP: {e}")
            return False
    
    def get_current_tdp(self) -> Optional[int]:
        """Get current TDP from Intel RAPL"""
        # Implementation would read from RAPL files
        return None
    
    def get_capabilities(self) -> DeviceCapabilities:
        """Get device capabilities"""
        return self._capabilities

def get_power_manager() -> PowerManager:
    """Factory function to get appropriate power manager"""
    # Detect CPU vendor
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read().lower()
            
        if 'intel' in cpuinfo:
            return IntelRAPLManager()
        elif 'amd' in cpuinfo:
            return RyzenadjManager()
        else:
            # Default to ryzenadj for unknown
            return RyzenadjManager()
            
    except Exception as e:
        decky_plugin.logger.error(f"Failed to detect CPU vendor: {e}")
        return RyzenadjManager()
