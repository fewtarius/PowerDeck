"""
Device Detection and Management
Provides unified device detection with proper capability mapping
"""
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import decky_plugin
from power_core import DeviceCapabilities, CPUVendor, TDPMethod, ScalingDriver

@dataclass
class DeviceProfile:
    """Device-specific configuration profile"""
    name: str
    cpu_vendor: CPUVendor
    tdp_method: TDPMethod
    min_tdp: int
    max_tdp: int
    scaling_driver: Optional[ScalingDriver] = None
    supports_gpu_control: bool = True
    supports_cpu_boost: bool = True
    supports_smt: bool = True
    supports_epp: bool = False
    gpu_frequency_range: Optional[Tuple[int, int]] = None
    device_specific_features: Dict[str, bool] = None

class DeviceDetector:
    """Detects device capabilities and hardware features"""
    
    def __init__(self):
        self._device_profiles = self._load_device_profiles()
        self._detected_device = None
        self._cpu_vendor = self._detect_cpu_vendor()
        self._scaling_driver = self._detect_scaling_driver()
    
    def _load_device_profiles(self) -> Dict[str, DeviceProfile]:
        """Load known device profiles"""
        profiles = {}
        
        # Steam Deck
        profiles['steam_deck'] = DeviceProfile(
            name="Valve Steam Deck",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.STEAM_DECK,
            min_tdp=3,
            max_tdp=25,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(200, 1600),
            device_specific_features={
                'custom_bios_tdp': False,
                'custom_bios_gpu': False
            }
        )
        
        # ASUS ROG Ally
        profiles['rog_ally'] = DeviceProfile(
            name="ASUS ROG Ally",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.ASUS_WMI,
            min_tdp=5,
            max_tdp=30,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700),
            device_specific_features={
                'platform_profile': True,
                'mcu_powersave': True,
                'wmi_tdp': True
            }
        )
        
        # ASUS ROG Ally X
        profiles['rog_ally_x'] = DeviceProfile(
            name="ASUS ROG Ally X",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.ASUS_WMI,
            min_tdp=5,
            max_tdp=30,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700),
            device_specific_features={
                'platform_profile': True,
                'mcu_powersave': True,
                'wmi_tdp': True
            }
        )
        
        # Lenovo Legion Go
        profiles['legion_go'] = DeviceProfile(
            name="Lenovo Legion Go",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.LENOVO_WMI,
            min_tdp=5,
            max_tdp=30,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700),
            device_specific_features={
                'wmi_tdp': True,
                'custom_tdp_mode': True
            }
        )
        
        # ASUS Flow Z13
        profiles['flow_z13'] = DeviceProfile(
            name="ASUS Flow Z13",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=5,
            max_tdp=54,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700)   # Pre-2025 models (6900HX/7745HX)
        )

        # AYANEO FLIP KB / FLIP DS / FLIP 1S — Ryzen 7 7840U / Radeon 780M 12 CU
        # DMI sys_vendor: "AYANEO", product_name: "FLIP KB", "FLIP-KB", "FLIP DS", "FLIP 1S"
        # Confirmed SMU ceiling: STAPM 30W, fast-limit 45W, slow-limit 43W
        profiles['ayaneo_flip_kb'] = DeviceProfile(
            name="AYANEO FLIP KB",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=5,
            max_tdp=30,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(800, 2700),   # Min 800MHz avoids low-clock stutter
            device_specific_features={
                'handheld_device': True,
                'ac_power_detection': True,
                'thermal_protection': True,
                'fclk_control': True,
                'nvme_power_control': True,
            }
        )

        # AYANEO 2S
        profiles['ayaneo_2s'] = DeviceProfile(
            name="AYANEO 2S",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=15,  # Use processor DB ctdp_min
            max_tdp=30,  # Use processor DB ctdp_max
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700),
            device_specific_features={
                'handheld_device': True,
                'ac_power_detection': True,
                'thermal_protection': True
            }
        )
        
        # Generic AYANEO device
        profiles['ayaneo_generic'] = DeviceProfile(
            name="AYANEO Device",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=3,
            max_tdp=20,  # Conservative for unknown models
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700),
            device_specific_features={
                'handheld_device': True,
                'ac_power_detection': True
            }
        )
        
        # Generic Intel device
        profiles['intel_generic'] = DeviceProfile(
            name="Intel Device",
            cpu_vendor=CPUVendor.INTEL,
            tdp_method=TDPMethod.INTEL_RAPL,
            min_tdp=4,
            max_tdp=40,
            scaling_driver=ScalingDriver.INTEL_PSTATE,
            supports_gpu_control=False,  # Limited iGPU control
            supports_epp=True,
            gpu_frequency_range=None
        )
        
        # Generic AMD device (fallback)
        profiles['amd_generic'] = DeviceProfile(
            name="AMD Device",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=5,
            max_tdp=40,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2700)
        )

        # ── Strix Halo (Ryzen AI MAX 300 series) desktop / mini-PC profiles ──
        # Strix Halo is the high-power desktop-class APU with 12-16 Zen 5
        # cores and Radeon 8060S/8050S (40/32 CUs). cTDP per AMD spec is
        # 45-120W but motherboard configs range from ~55W (Strix Point
        # laptop boards) to 130+W (Beelink GTR9 / Framework Desktop).
        # The Radeon 8060S peaks ~2.9 GHz SCLK, the 8050S ~2.8 GHz.
        # All Strix Halo SKUs share one operational caveat: no APU skin
        # temperature sensor (tctl only), and TDC/EDC values come back
        # as NaN from ryzenadj. main.py handles both automatically.

        # Nimo Axis N161L - Strix Halo mini-PC
        # DMI product_name: "N161L", sys_vendor: "Nimo Direct INC."
        # Confirmed: 16C/32T Ryzen AI MAX+ 395, default STAPM/PPT 105W,
        # SMU BIOS interface v25. Battery-powered with MediaTek MT7925.
        profiles['nimo_n161l'] = DeviceProfile(
            name="Nimo Axis N161L (Strix Halo)",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=45,
            max_tdp=120,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2900),
            device_specific_features={
                'handheld_device': False,
                'desktop_apu': False,
                'strix_halo': True,
                'tctl_only_thermal': True,   # no apu-skin-temp sensor
                'fclk_control': True,
                'nvme_power_control': True,
                'platform_profile': True,
                'wifi_pcie_pm': True,
                'pcie_l1ss_control': True,
            }
        )

        # ASUS ROG Flow Z13 (2025) - GZ302, AMD Ryzen AI Max+ 395 (Strix Halo, 40 CU)
        # DMI product_name: "GZ302*", sys_vendor: "ASUSTeK COMPUTER INC."
        # cTDP: 45W-120W; sweet spot 55-70W confirmed on hardware.
        # Note: Z13 is technically a tablet/2-in-1 rather than a handheld,
        # so it does not get the handheld_device flag (no AC/battery split).
        profiles['flow_z13_2025'] = DeviceProfile(
            name="ASUS ROG Flow Z13 (2025)",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=15,
            max_tdp=120,
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2900),
            device_specific_features={
                'handheld_device': False,
                'desktop_apu': False,
                'strix_halo': True,
                'tctl_only_thermal': True,
                'fclk_control': True,
                'nvme_power_control': True,
                'platform_profile': True,
            }
        )

        # Generic Strix Halo desktop / mini-PC fallback
        # Covers Framework Desktop, Beelink SER9 / GTR9, Minisforum AI X1
        # / MS-A2, HP Z2 Mini G1a, and any other board we don't have
        # explicit DMI for yet. New boards: send product_name + ryzenadj
        # -i output and we'll add explicit profiles.
        profiles['strix_halo_desktop'] = DeviceProfile(
            name="AMD Strix Halo Desktop",
            cpu_vendor=CPUVendor.AMD,
            tdp_method=TDPMethod.RYZENADJ,
            min_tdp=45,    # AMD cTDP min for the family
            max_tdp=130,   # some boards (Beelink GTR9 PRO, Framework Desktop OC)
                           # allow cTDP up to 130W; raise ceiling so users on
                           # those boards aren't artificially capped.
            scaling_driver=ScalingDriver.AMD_PSTATE_EPP,
            supports_gpu_control=True,
            supports_epp=True,
            gpu_frequency_range=(400, 2900),
            device_specific_features={
                'handheld_device': False,
                'desktop_apu': True,
                'strix_halo': True,
                'tctl_only_thermal': True,
                'fclk_control': True,
                'platform_profile': True,
            }
        )

        return profiles
    
    def _detect_cpu_vendor(self) -> CPUVendor:
        """Detect CPU vendor from /proc/cpuinfo"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read().lower()
                
            if 'intel' in cpuinfo:
                return CPUVendor.INTEL
            elif 'amd' in cpuinfo:
                return CPUVendor.AMD
            else:
                return CPUVendor.UNKNOWN
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to detect CPU vendor: {e}")
            return CPUVendor.UNKNOWN
    
    def _detect_scaling_driver(self) -> Optional[ScalingDriver]:
        """Detect current CPU scaling driver"""
        try:
            driver_path = "/sys/devices/system/cpu/cpufreq/policy0/scaling_driver"
            if os.path.exists(driver_path):
                with open(driver_path, 'r') as f:
                    driver_name = f.read().strip()
                    
                # Map driver names to enum values
                driver_mapping = {
                    'intel_pstate': ScalingDriver.INTEL_PSTATE,
                    'intel_cpufreq': ScalingDriver.INTEL_CPUFREQ,
                    'amd-pstate-epp': ScalingDriver.AMD_PSTATE_EPP,
                    'amd-pstate': ScalingDriver.AMD_PSTATE,
                    'acpi-cpufreq': ScalingDriver.ACPI_CPUFREQ
                }
                
                return driver_mapping.get(driver_name)
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to detect scaling driver: {e}")
            
        return None
    
    def detect_device(self) -> str:
        """Detect specific device model"""
        if self._detected_device:
            return self._detected_device
        
        device_id = self._detect_device_from_dmi()
        if not device_id:
            device_id = self._detect_device_from_characteristics()
        
        self._detected_device = device_id
        return device_id
    
    def _detect_device_from_dmi(self) -> Optional[str]:
        """Detect device from DMI information"""
        try:
            # Check various DMI sources
            dmi_sources = [
                '/sys/class/dmi/id/product_name',
                '/sys/class/dmi/id/board_name',
                '/sys/class/dmi/id/sys_vendor'
            ]
            
            dmi_info = {}
            for source in dmi_sources:
                if os.path.exists(source):
                    with open(source, 'r') as f:
                        key = os.path.basename(source)
                        dmi_info[key] = f.read().strip().lower()
            
            # Device detection patterns
            product_name = dmi_info.get('product_name', '')
            board_name = dmi_info.get('board_name', '')
            sys_vendor = dmi_info.get('sys_vendor', '')
            
            # Steam Deck detection
            if 'jupiter' in product_name or 'steamdeck' in product_name:
                return 'steam_deck'
            
            # ASUS devices
            if 'asus' in sys_vendor:
                if 'rc71l' in product_name or 'rog ally' in product_name:
                    if 'x1e' in product_name:
                        return 'rog_ally_x'
                    return 'rog_ally'
                elif 'gv301' in product_name or 'flow z13' in product_name:
                    return 'flow_z13'

            # ASUS Flow Z13 2025 (GZ302) — must check before generic flow_z13
            if 'asus' in sys_vendor:
                if 'gz302' in product_name:
                    return 'flow_z13_2025'
            
            # Lenovo devices
            if 'lenovo' in sys_vendor:
                if '83e1' in product_name or 'legion go' in product_name:
                    return 'legion_go'
            
            # AYANEO devices
            if 'ayaneo' in sys_vendor:
                if '2s' in product_name or 'ayaneo 2s' in product_name:
                    return 'ayaneo_2s'
                if any(x in product_name for x in ['flip kb', 'flip-kb', 'flip ds', 'flip-ds', 'flip 1s', 'flip1s']):
                    return 'ayaneo_flip_kb'
                # Other AYANEO models — conservative fallback
                return 'ayaneo_generic'

            # Nimo Axis N161L — Strix Halo mini-PC
            # DMI product_name: "N161L", sys_vendor: "Nimo Direct INC."
            if 'nimo' in sys_vendor and 'n161' in product_name:
                return 'nimo_n161l'

            # Generic Strix Halo desktop / mini-PC patterns by DMI board_name.
            # Framework Desktop uses "FRANDMD-*", Beelink SER9/GTR9 use product
            # names like "SER9"/"GTR9"+"PRO", Minisforum AI X1 is "MS-A2",
            # HP Z2 Mini G1a uses "Z2 Mini G1a" family. We don't enumerate
            # every variant here; the characteristics-based fallback picks up
            # Strix Halo systems we haven't DMI-matched yet.
            strix_halo_indicators = [
                'frandmd',           # Framework Desktop
                'beelink ser9', 'beelink gtr9', 'beelink ai',
                'minisforum ai x1', 'minisforum ms-a2', 'minisforum um890',
                'z2 mini g1a',
            ]
            if any(ind in (product_name + ' ' + board_name) for ind in strix_halo_indicators):
                return 'strix_halo_desktop'

            return None
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to detect device from DMI: {e}")
            return None
    
    def _detect_device_from_characteristics(self) -> str:
        """Fallback device detection based on CPU characteristics"""
        # Strix Halo has its own operational profile (tctl-only thermal,
        # 12-16 cores, no apu-skin-temp, high-power desktop APU) so detect
        # it explicitly even when DMI didn't match a known board.
        try:
            from processor_detection import is_strix_halo
            if is_strix_halo():
                return 'strix_halo_desktop'
        except Exception:
            pass

        if self._cpu_vendor == CPUVendor.INTEL:
            return 'intel_generic'
        elif self._cpu_vendor == CPUVendor.AMD:
            return 'amd_generic'
        else:
            return 'amd_generic'  # Default fallback
    
    def get_device_capabilities(self) -> DeviceCapabilities:
        """Get device capabilities based on detection"""
        device_id = self.detect_device()
        profile = self._device_profiles.get(device_id, self._device_profiles['amd_generic'])
        
        # Create capabilities from profile
        capabilities = DeviceCapabilities(
            name=profile.name,
            cpu_vendor=profile.cpu_vendor,
            tdp_method=profile.tdp_method,
            min_tdp=profile.min_tdp,
            max_tdp=profile.max_tdp,
            supports_gpu_control=profile.supports_gpu_control,
            supports_cpu_boost=profile.supports_cpu_boost,
            supports_smt=profile.supports_smt,
            supports_epp=profile.supports_epp,
            scaling_driver=profile.scaling_driver or self._scaling_driver,
            gpu_frequency_range=profile.gpu_frequency_range
        )
        
        # Enhance with runtime detection
        self._enhance_capabilities_runtime(capabilities)
        
        return capabilities
    
    def _enhance_capabilities_runtime(self, capabilities: DeviceCapabilities):
        """Enhance capabilities with runtime detection"""
        # Check if SMT is actually supported
        if os.path.exists('/sys/devices/system/cpu/smt/control'):
            capabilities.supports_smt = True
        else:
            capabilities.supports_smt = False
        
        # Check CPU boost support
        boost_paths = [
            '/sys/devices/system/cpu/cpufreq/boost',
            '/sys/devices/system/cpu/intel_pstate/no_turbo',
            '/sys/devices/system/cpu/cpufreq/policy0/boost'
        ]
        
        capabilities.supports_cpu_boost = any(os.path.exists(path) for path in boost_paths)
        
        # Check EPP support
        epp_path = '/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference'
        capabilities.supports_epp = os.path.exists(epp_path)
        
        # Update scaling driver if detected
        if self._scaling_driver:
            capabilities.scaling_driver = self._scaling_driver
    
    def get_device_profile(self, device_id: Optional[str] = None) -> DeviceProfile:
        """Get device profile by ID or detected device"""
        if not device_id:
            device_id = self.detect_device()
        
        return self._device_profiles.get(device_id, self._device_profiles['amd_generic'])
    
    def is_steam_deck(self) -> bool:
        """Check if device is Steam Deck"""
        return self.detect_device() == 'steam_deck'
    
    def is_rog_ally(self) -> bool:
        """Check if device is ROG Ally (any variant)"""
        device_id = self.detect_device()
        return device_id in ['rog_ally', 'rog_ally_x']
    
    def is_legion_go(self) -> bool:
        """Check if device is Legion Go"""
        return self.detect_device() == 'legion_go'
    
    def is_intel(self) -> bool:
        """Check if device has Intel CPU"""
        return self._cpu_vendor == CPUVendor.INTEL
    
    def is_amd(self) -> bool:
        """Check if device has AMD CPU"""
        return self._cpu_vendor == CPUVendor.AMD

# Global device detector instance
_device_detector = None

def get_device_detector() -> DeviceDetector:
    """Get global device detector instance"""
    global _device_detector
    if _device_detector is None:
        _device_detector = DeviceDetector()
    return _device_detector

def get_device_capabilities() -> DeviceCapabilities:
    """Get current device capabilities"""
    return get_device_detector().get_device_capabilities()

def get_device_name() -> str:
    """Get current device name"""
    return get_device_capabilities().name

class DeviceManager:
    """Legacy DeviceManager class for backward compatibility"""
    
    def __init__(self):
        self.detector = get_device_detector()
    
    def get_device_capabilities(self) -> DeviceCapabilities:
        """Get device capabilities"""
        return self.detector.get_device_capabilities()
    
    def get_device_name(self) -> str:
        """Get device name"""
        return self.detector.get_device_capabilities().name
    
    def is_handheld(self) -> bool:
        """Check if device is a handheld"""
        # For now, consider specific known handhelds. Strix Halo desktops
        # (nimo_n161l, strix_halo_desktop) and the Flow Z13 (tablet/2-in-1)
        # are deliberately excluded — they run on AC power and don't have a
        # battery profile split.
        device_id = self.detector.detect_device()
        handheld_devices = ['steam_deck', 'rog_ally', 'rog_ally_x', 'legion_go',
                            'flow_z13', 'ayaneo_2s', 'ayaneo_flip_kb', 'ayaneo_generic']
        return device_id in handheld_devices
    
    def get_tdp_limits(self) -> tuple:
        """Get TDP limits for the device"""
        caps = self.detector.get_device_capabilities()
        return (caps.min_tdp, caps.max_tdp)
