#!/usr/bin/env python3
"""
Sysfs-based Power Management for PowerDeck Plugin

Dynamically detects power management capabilities from sysfs instead of 
relying on processor databases. Works for both Intel and AMD systems.
"""

import os
import re
import subprocess
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class PowerCapabilities:
    """Detected power management capabilities from sysfs"""
    cpu_vendor: str
    cpu_model: str
    cpu_cores: int
    cpu_threads: int
    
    # TDP/Power management
    supports_rapl: bool
    rapl_domains: List[str]
    tdp_min_uw: Optional[int]  # Microwatts
    tdp_max_uw: Optional[int]  # Microwatts
    tdp_current_uw: Optional[int]  # Microwatts
    
    # CPU frequency management
    supports_pstate: bool
    supports_cpufreq: bool
    available_governors: List[str]
    current_governor: str
    
    # CPU boost/turbo
    supports_boost: bool
    boost_enabled: bool
    
    # Energy performance preference
    supports_epp: bool
    available_epp: List[str]
    current_epp: str
    
    # Core count management
    max_cores: int
    online_cores: int
    
    # GPU capabilities (Intel integrated graphics)
    supports_intel_gpu: bool
    intel_gpu_path: Optional[str]
    gpu_min_freq_mhz: Optional[int]
    gpu_max_freq_mhz: Optional[int] 
    gpu_current_freq_mhz: Optional[int]
    
    # Additional capabilities
    supports_smt: bool
    smt_enabled: bool


class SysfsPowerManager:
    """Dynamic power management using sysfs detection"""
    
    def __init__(self):
        self._capabilities = None
        self._rapl_base = "/sys/class/powercap"
        self._cpu_base = "/sys/devices/system/cpu"
    
    def get_capabilities(self) -> PowerCapabilities:
        """Detect and return power management capabilities"""
        if self._capabilities is None:
            self._capabilities = self._detect_capabilities()
        return self._capabilities
    
    def _detect_capabilities(self) -> PowerCapabilities:
        """Detect all power management capabilities from sysfs"""
        # Basic CPU information
        cpu_vendor, cpu_model = self._get_cpu_info()
        cpu_cores, cpu_threads = self._get_cpu_topology()
        
        # RAPL/TDP capabilities
        rapl_support, rapl_domains, tdp_info = self._detect_rapl_capabilities()
        
        # CPU frequency management
        pstate_support, cpufreq_support, governors, current_gov = self._detect_freq_management()
        
        # CPU boost capabilities
        boost_support, boost_enabled = self._detect_boost_capabilities()
        
        # EPP capabilities
        epp_support, available_epp, current_epp = self._detect_epp_capabilities()
        
        # Core management
        max_cores, online_cores = self._detect_core_capabilities()
        
        # SMT capabilities
        smt_support, smt_enabled = self._detect_smt_capabilities()
        
        # Intel GPU capabilities
        intel_gpu_support, gpu_path, gpu_min_freq, gpu_max_freq, gpu_cur_freq = self._detect_intel_gpu_capabilities()
        
        return PowerCapabilities(
            cpu_vendor=cpu_vendor,
            cpu_model=cpu_model,
            cpu_cores=cpu_cores,
            cpu_threads=cpu_threads,
            supports_rapl=rapl_support,
            rapl_domains=rapl_domains,
            tdp_min_uw=tdp_info[0],
            tdp_max_uw=tdp_info[1],
            tdp_current_uw=tdp_info[2],
            supports_pstate=pstate_support,
            supports_cpufreq=cpufreq_support,
            available_governors=governors,
            current_governor=current_gov,
            supports_boost=boost_support,
            boost_enabled=boost_enabled,
            supports_epp=epp_support,
            available_epp=available_epp,
            current_epp=current_epp,
            max_cores=max_cores,
            online_cores=online_cores,
            supports_intel_gpu=intel_gpu_support,
            intel_gpu_path=gpu_path,
            gpu_min_freq_mhz=gpu_min_freq,
            gpu_max_freq_mhz=gpu_max_freq,
            gpu_current_freq_mhz=gpu_cur_freq,
            supports_smt=smt_support,
            smt_enabled=smt_enabled
        )
    
    def _get_cpu_info(self) -> Tuple[str, str]:
        """Get CPU vendor and model from /proc/cpuinfo"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                content = f.read()
            
            vendor_match = re.search(r'vendor_id\s*:\s*(.+)', content)
            model_match = re.search(r'model name\s*:\s*(.+)', content)
            
            vendor = vendor_match.group(1).strip() if vendor_match else "Unknown"
            model = model_match.group(1).strip() if model_match else "Unknown"
            
            # Normalize vendor names
            if vendor in ["GenuineIntel", "Intel"]:
                vendor = "Intel"
            elif vendor in ["AuthenticAMD", "AMD"]:
                vendor = "AMD"
            
            return vendor, model
            
        except Exception:
            return "Unknown", "Unknown"
    
    def _get_cpu_topology(self) -> Tuple[int, int]:
        """Get CPU core and thread count from sysfs"""
        try:
            # Get physical core count
            cores = 0
            threads = 0
            
            # Count online CPUs
            with open(f'{self._cpu_base}/online', 'r') as f:
                online_cpus = f.read().strip()
            
            # Parse CPU range (e.g., "0-7" or "0,2-7")
            cpu_count = 0
            for cpu_range in online_cpus.split(','):
                if '-' in cpu_range:
                    start, end = map(int, cpu_range.split('-'))
                    cpu_count += end - start + 1
                else:
                    cpu_count += 1
            
            threads = cpu_count
            
            # Try to get physical core count from topology
            try:
                core_ids = set()
                for cpu_id in range(cpu_count):
                    core_id_file = f'{self._cpu_base}/cpu{cpu_id}/topology/core_id'
                    if os.path.exists(core_id_file):
                        with open(core_id_file, 'r') as f:
                            core_ids.add(int(f.read().strip()))
                cores = len(core_ids) if core_ids else cpu_count
            except Exception:
                cores = cpu_count // 2  # Assume hyperthreading
            
            return cores, threads
            
        except Exception:
            return 4, 8  # Fallback
    
    def _detect_rapl_capabilities(self) -> Tuple[bool, List[str], Tuple[Optional[int], Optional[int], Optional[int]]]:
        """Detect RAPL power management capabilities"""
        domains = []
        tdp_min = None
        tdp_max = None
        tdp_current = None
        
        try:
            # Check for RAPL domains
            rapl_dirs = [d for d in os.listdir(self._rapl_base) if d.startswith('intel-rapl:')]
            
            for domain in rapl_dirs:
                domain_path = os.path.join(self._rapl_base, domain)
                if os.path.isdir(domain_path):
                    # Get domain name
                    name_file = os.path.join(domain_path, 'name')
                    if os.path.exists(name_file):
                        with open(name_file, 'r') as f:
                            domain_name = f.read().strip()
                        domains.append(domain_name)
                    
                    # Check for power constraints (Intel-style)
                    constraint_0_max = os.path.join(domain_path, 'constraint_0_max_power_uw')
                    constraint_0_current = os.path.join(domain_path, 'constraint_0_power_limit_uw')
                    
                    if os.path.exists(constraint_0_max) and os.path.exists(constraint_0_current):
                        try:
                            with open(constraint_0_max, 'r') as f:
                                max_val = int(f.read().strip())
                            with open(constraint_0_current, 'r') as f:
                                current_val = int(f.read().strip())
                            
                            if domain_name == 'package-0':  # Primary package
                                tdp_max = max_val
                                tdp_current = current_val
                                # For Intel, min is typically a fraction of max
                                tdp_min = max_val // 4  # 25% of max as minimum
                                
                        except Exception:
                            pass
            
            return len(domains) > 0, domains, (tdp_min, tdp_max, tdp_current)
            
        except Exception:
            return False, [], (None, None, None)
    
    def _detect_freq_management(self) -> Tuple[bool, bool, List[str], str]:
        """Detect CPU frequency management capabilities"""
        pstate_support = os.path.exists(f'{self._cpu_base}/intel_pstate')
        cpufreq_support = os.path.exists(f'{self._cpu_base}/cpu0/cpufreq')
        
        governors = []
        current_governor = "unknown"
        
        if cpufreq_support:
            try:
                # Get available governors
                with open(f'{self._cpu_base}/cpu0/cpufreq/scaling_available_governors', 'r') as f:
                    governors = f.read().strip().split()
                
                # Get current governor
                with open(f'{self._cpu_base}/cpu0/cpufreq/scaling_governor', 'r') as f:
                    current_governor = f.read().strip()
                    
            except Exception:
                pass
        
        return pstate_support, cpufreq_support, governors, current_governor
    
    def _detect_boost_capabilities(self) -> Tuple[bool, bool]:
        """Detect CPU boost/turbo capabilities"""
        boost_support = False
        boost_enabled = False
        
        # Intel P-State boost
        intel_turbo_file = f'{self._cpu_base}/intel_pstate/no_turbo'
        if os.path.exists(intel_turbo_file):
            boost_support = True
            try:
                with open(intel_turbo_file, 'r') as f:
                    boost_enabled = f.read().strip() == '0'  # no_turbo=0 means turbo enabled
            except Exception:
                pass
        
        # AMD boost
        amd_boost_file = f'{self._cpu_base}/cpufreq/boost'
        if os.path.exists(amd_boost_file):
            boost_support = True
            try:
                with open(amd_boost_file, 'r') as f:
                    boost_enabled = f.read().strip() == '1'
            except Exception:
                pass
        
        return boost_support, boost_enabled
    
    def _detect_epp_capabilities(self) -> Tuple[bool, List[str], str]:
        """Detect Energy Performance Preference capabilities"""
        epp_support = False
        available_epp = []
        current_epp = "unknown"
        
        # Check for EPP support
        epp_file = f'{self._cpu_base}/cpu0/cpufreq/energy_performance_preference'
        available_epp_file = f'{self._cpu_base}/cpu0/cpufreq/energy_performance_available_preferences'
        
        if os.path.exists(epp_file):
            epp_support = True
            try:
                with open(epp_file, 'r') as f:
                    current_epp = f.read().strip()
            except Exception:
                pass
        
        if os.path.exists(available_epp_file):
            try:
                with open(available_epp_file, 'r') as f:
                    available_epp = f.read().strip().split()
            except Exception:
                # Common EPP values if file doesn't exist
                available_epp = ["power", "balance_power", "balance_performance", "performance"]
        
        return epp_support, available_epp, current_epp
    
    def _detect_core_capabilities(self) -> Tuple[int, int]:
        """Detect CPU core management capabilities"""
        try:
            # Get maximum possible cores
            with open(f'{self._cpu_base}/possible', 'r') as f:
                possible = f.read().strip()
            
            # Parse range (e.g., "0-15")
            if '-' in possible:
                max_cores = int(possible.split('-')[1]) + 1
            else:
                max_cores = 1
            
            # Get currently online cores
            with open(f'{self._cpu_base}/online', 'r') as f:
                online = f.read().strip()
            
            online_count = 0
            for cpu_range in online.split(','):
                if '-' in cpu_range:
                    start, end = map(int, cpu_range.split('-'))
                    online_count += end - start + 1
                else:
                    online_count += 1
            
            return max_cores, online_count
            
        except Exception:
            return 8, 8  # Fallback
    
    def _detect_smt_capabilities(self) -> Tuple[bool, bool]:
        """Detect SMT/Hyperthreading capabilities"""
        smt_file = f'{self._cpu_base}/smt/control'
        
        if os.path.exists(smt_file):
            try:
                with open(smt_file, 'r') as f:
                    smt_status = f.read().strip()
                return True, smt_status == 'on'
            except Exception:
                pass
        
        # Fallback: check if threads > cores
        cores, threads = self._get_cpu_topology()
        return threads > cores, threads > cores
    
    def _detect_intel_gpu_capabilities(self) -> Tuple[bool, Optional[str], Optional[int], Optional[int], Optional[int]]:
        """Detect Intel integrated GPU capabilities via sysfs"""
        gpu_base_patterns = [
            '/sys/devices/pci*/*/drm/card*/gt_min_freq_mhz',
            '/sys/class/drm/card*/gt_min_freq_mhz'
        ]
        
        for pattern in gpu_base_patterns:
            try:
                import glob
                matching_paths = glob.glob(pattern)
                if matching_paths:
                    gpu_path = os.path.dirname(matching_paths[0])
                    min_freq_path = os.path.join(gpu_path, 'gt_min_freq_mhz')
                    max_freq_path = os.path.join(gpu_path, 'gt_max_freq_mhz')
                    cur_freq_path = os.path.join(gpu_path, 'gt_cur_freq_mhz')
                    
                    # Hardware capability paths (RPn = min, RP0 = max)
                    hw_min_path = os.path.join(gpu_path, 'gt_RPn_freq_mhz')
                    hw_max_path = os.path.join(gpu_path, 'gt_RP0_freq_mhz')
                    
                    if all(os.path.exists(p) for p in [min_freq_path, max_freq_path, cur_freq_path, hw_min_path, hw_max_path]):
                        try:
                            # Read hardware capabilities (for detection)
                            with open(hw_min_path, 'r') as f:
                                hw_min_freq = int(f.read().strip())
                            with open(hw_max_path, 'r') as f:
                                hw_max_freq = int(f.read().strip())
                            with open(cur_freq_path, 'r') as f:
                                cur_freq = int(f.read().strip())
                            
                            return True, gpu_path, hw_min_freq, hw_max_freq, cur_freq
                        except (ValueError, IOError):
                            continue
            except Exception:
                continue
        
        return False, None, None, None, None
    
    def get_optimal_tdp_limits(self) -> Tuple[int, int]:
        """Get optimal TDP limits in watts from sysfs detection"""
        caps = self.get_capabilities()
        
        if caps.supports_rapl and caps.tdp_max_uw:
            # Convert microwatts to watts
            max_watts = caps.tdp_max_uw // 1_000_000
            min_watts = 4  # Conservative minimum for underclocking
            
            # Apply safety limits based on vendor
            if caps.cpu_vendor == "Intel":
                # Intel mobile typically supports 2x base TDP
                safe_max = min(max_watts, 35)  # Intel mobile upper limit
            else:  # AMD
                # AMD handhelds typically have higher limits
                safe_max = min(max_watts, 30)  # AMD handheld upper limit
            
            return min_watts, safe_max
        
        # Fallback limits
        return 4, 25
    
    def get_current_tdp_watts(self) -> int:
        """Get current TDP setting in watts"""
        caps = self.get_capabilities()
        
        if caps.supports_rapl and caps.tdp_current_uw:
            return caps.tdp_current_uw // 1_000_000
        
        return 15  # Fallback
    
    def set_tdp_watts(self, watts: int) -> bool:
        """Set TDP in watts using RAPL interface"""
        caps = self.get_capabilities()
        
        if not caps.supports_rapl:
            return False
        
        microwatts = watts * 1_000_000
        
        try:
            # Find package-0 domain
            for domain in caps.rapl_domains:
                if domain == 'package-0':
                    # Try intel-rapl:0 first
                    constraint_file = f'{self._rapl_base}/intel-rapl:0/constraint_0_power_limit_uw'
                    if os.path.exists(constraint_file):
                        with open(constraint_file, 'w') as f:
                            f.write(str(microwatts))
                        return True
            
            return False
            
        except Exception:
            return False
    
    # Intel GPU Management Methods
    def get_intel_gpu_frequency_range(self) -> Tuple[int, int]:
        """Get current Intel GPU frequency range in MHz"""
        caps = self.get_capabilities()
        if caps.supports_intel_gpu and caps.intel_gpu_path:
            try:
                min_freq_path = os.path.join(caps.intel_gpu_path, 'gt_min_freq_mhz')
                max_freq_path = os.path.join(caps.intel_gpu_path, 'gt_max_freq_mhz')
                
                with open(min_freq_path, 'r') as f:
                    min_freq = int(f.read().strip())
                with open(max_freq_path, 'r') as f:
                    max_freq = int(f.read().strip())
                    
                return min_freq, max_freq
            except (IOError, ValueError):
                pass
        return 0, 0
    
    def get_intel_gpu_current_frequency(self) -> int:
        """Get current Intel GPU frequency in MHz"""
        caps = self.get_capabilities()
        if caps.supports_intel_gpu and caps.intel_gpu_path:
            try:
                cur_freq_path = os.path.join(caps.intel_gpu_path, 'gt_cur_freq_mhz')
                with open(cur_freq_path, 'r') as f:
                    return int(f.read().strip())
            except (IOError, ValueError):
                pass
        return 0
    
    def set_intel_gpu_frequency_range(self, min_freq_mhz: int, max_freq_mhz: int) -> bool:
        """Set Intel GPU frequency range in MHz with gradual stepping for large changes"""
        caps = self.get_capabilities()
        if not caps.supports_intel_gpu or not caps.intel_gpu_path:
            return False
            
        try:
            min_freq_path = os.path.join(caps.intel_gpu_path, 'gt_min_freq_mhz')
            max_freq_path = os.path.join(caps.intel_gpu_path, 'gt_max_freq_mhz')
            
            import decky_plugin
            
            # Validate frequency range against hardware capabilities
            hw_min = caps.gpu_min_freq_mhz or 300
            hw_max = caps.gpu_max_freq_mhz or 3000
            
            target_min = max(min_freq_mhz, hw_min)
            target_max = min(max_freq_mhz, hw_max)
            
            # Ensure min <= max
            if target_min > target_max:
                target_min = hw_min
                target_max = hw_max
            
            decky_plugin.logger.info(f"GPU FREQ: Setting Intel GPU to {target_min}-{target_max}MHz")
            
            # Simple approach: Try direct setting first
            try:
                # Set max first, then min
                with open(max_freq_path, 'w') as f:
                    f.write(str(target_max))
                with open(min_freq_path, 'w') as f:
                    f.write(str(target_min))
                    
                decky_plugin.logger.info(f"GPU FREQ: Direct setting successful: {target_min}-{target_max}MHz")
                return True
                
            except Exception as direct_error:
                decky_plugin.logger.info(f"GPU FREQ: Direct setting failed ({direct_error}), trying gradual approach")
                
                # If direct fails, use gradual stepping
                return self._step_intel_gpu_frequency(min_freq_path, max_freq_path, target_min, target_max)
                
        except Exception as e:
            decky_plugin.logger.error(f"GPU FREQ ERROR: {e}")
            return False
    
    def _step_intel_gpu_frequency(self, min_freq_path: str, max_freq_path: str, target_min: int, target_max: int) -> bool:
        """Step Intel GPU frequency gradually when direct setting fails"""
        import decky_plugin
        
        try:
            # Get current frequencies
            with open(min_freq_path, 'r') as f:
                current_min = int(f.read().strip())
            with open(max_freq_path, 'r') as f:
                current_max = int(f.read().strip())
        except Exception:
            decky_plugin.logger.error("Failed to read current frequencies for stepping")
            return False
        
        decky_plugin.logger.info(f"GPU FREQ STEP: From {current_min}-{current_max} to {target_min}-{target_max}")
        
        # Use smaller steps to avoid hardware rejection
        step_size = 100  # MHz per step
        max_attempts = 30
        attempts = 0
        
        while attempts < max_attempts and (current_min != target_min or current_max != target_max):
            # Calculate next frequencies
            next_min = current_min
            next_max = current_max
            
            # Move max first if we need to increase it, or if min is already correct
            if current_max != target_max and (target_max > current_max or current_min == target_min):
                if target_max > current_max:
                    next_max = min(current_max + step_size, target_max)
                else:
                    next_max = max(current_max - step_size, target_max)
                    
            # Move min if max is correct or if we need to decrease min
            elif current_min != target_min:
                if target_min > current_min:
                    next_min = min(current_min + step_size, target_min, next_max)  # Don't exceed max
                else:
                    next_min = max(current_min - step_size, target_min)
            
            # Apply the step
            try:
                decky_plugin.logger.info(f"GPU FREQ STEP {attempts+1}: {current_min}-{current_max} → {next_min}-{next_max}")
                
                # Order matters: set the one that creates more room first
                if next_max >= current_max:  # Increasing or maintaining max
                    with open(max_freq_path, 'w') as f:
                        f.write(str(next_max))
                    with open(min_freq_path, 'w') as f:
                        f.write(str(next_min))
                else:  # Decreasing max
                    with open(min_freq_path, 'w') as f:
                        f.write(str(next_min))
                    with open(max_freq_path, 'w') as f:
                        f.write(str(next_max))
                
                current_min = next_min
                current_max = next_max
                
            except Exception as e:
                decky_plugin.logger.warning(f"GPU FREQ STEP {attempts+1} failed: {e}")
                # Try smaller steps
                step_size = max(25, step_size // 2)
                
            attempts += 1
        
        if current_min == target_min and current_max == target_max:
            decky_plugin.logger.info(f"GPU FREQ: Successfully stepped to {target_min}-{target_max}MHz in {attempts} steps")
            return True
        else:
            decky_plugin.logger.error(f"GPU FREQ: Failed to reach target after {attempts} attempts")
            return False


# Global instance for use by PowerDeck
sysfs_power_manager = SysfsPowerManager()


def get_sysfs_power_capabilities() -> Dict[str, Any]:
    """Get power capabilities detected from sysfs for PowerDeck"""
    caps = sysfs_power_manager.get_capabilities()
    
    return {
        "detected": True,
        "processor_name": caps.cpu_model,
        "cpu_vendor": caps.cpu_vendor,
        "cpu_cores": caps.cpu_cores,
        "cpu_threads": caps.cpu_threads,
        "supports_rapl": caps.supports_rapl,
        "rapl_domains": caps.rapl_domains,
        "supports_pstate": caps.supports_pstate,
        "supports_cpufreq": caps.supports_cpufreq,
        "available_governors": caps.available_governors,
        "current_governor": caps.current_governor,
        "supports_boost": caps.supports_boost,
        "boost_enabled": caps.boost_enabled,
        "supports_epp": caps.supports_epp,
        "available_epp": caps.available_epp,
        "current_epp": caps.current_epp,
        "max_cores": caps.max_cores,
        "online_cores": caps.online_cores,
        "supports_smt": caps.supports_smt,
        "smt_enabled": caps.smt_enabled,
        "tdp_info": {
            "min_watts": sysfs_power_manager.get_optimal_tdp_limits()[0],
            "max_watts": sysfs_power_manager.get_optimal_tdp_limits()[1],
            "current_watts": sysfs_power_manager.get_current_tdp_watts(),
            "supports_tdp_control": caps.supports_rapl
        }
    }


def get_sysfs_tdp_limits() -> Tuple[int, int]:
    """Get TDP limits from sysfs detection"""
    return sysfs_power_manager.get_optimal_tdp_limits()


def set_sysfs_tdp(watts: int) -> bool:
    """Set TDP using sysfs RAPL interface"""
    return sysfs_power_manager.set_tdp_watts(watts)
