"""
CPU Management Module
Handles CPU-related controls including governors, EPP, boost, and SMT
"""
import os
import subprocess
import time
import glob
from typing import List, Optional, Dict, Any
from enum import Enum
import decky_plugin
from power_core import ScalingDriver

class CPUGovernor(Enum):
    """Available CPU governors"""
    POWERSAVE = "powersave"
    SCHEDUTIL = "schedutil"  # Balanced
    PERFORMANCE = "performance"
    ONDEMAND = "ondemand"
    CONSERVATIVE = "conservative"
    USERSPACE = "userspace"

class EPPMode(Enum):
    """Energy Performance Preference modes"""
    PERFORMANCE = "performance"
    BALANCE_PERFORMANCE = "balance_performance"
    BALANCE_POWER = "balance_power"
    POWER = "power"

class CPUManager:
    """Manages CPU-related controls and optimizations."""
    
    def __init__(self):
        self.logger = decky_plugin.logger
        self._possible_cpus = []
        self._primary_cpus_cache = None  # Cache for topology-aware primary CPUs
        self._cpu_siblings_map = {}  # Maps CPU ID to list of sibling CPU IDs (for SMT)
        self._topology_initialized = False
        self._detect_possible_cpus()
        # Initialize online CPUs list for boost/governor management
        self._online_cpus = self._get_online_cpus()
        
    def _detect_possible_cpus(self):
        """Detect all possible CPUs on the system"""
        try:
            # Read from /sys/devices/system/cpu/possible
            with open('/sys/devices/system/cpu/possible', 'r') as f:
                possible_range = f.read().strip()
                if '-' in possible_range:
                    start, end = map(int, possible_range.split('-'))
                    self._possible_cpus = list(range(start, end + 1))
                else:
                    self._possible_cpus = [int(possible_range)]
        except:
            # Fallback: scan cpu directories
            cpu_dirs = glob.glob('/sys/devices/system/cpu/cpu[0-9]*')
            self._possible_cpus = sorted([int(d.split('cpu')[-1]) for d in cpu_dirs])
        
        self.logger.info(f"Detected {len(self._possible_cpus)} possible CPUs: {self._possible_cpus}")
    
    def initialize_cpu_topology(self):
        """Initialize CPU topology map at startup for efficiency"""
        if self._topology_initialized:
            return
            
        try:
            self.logger.info("Initializing CPU topology map...")
            
            # Get current online state to restore later
            original_online_cpus = []
            try:
                with open('/sys/devices/system/cpu/online', 'r') as f:
                    online_range = f.read().strip()
                    if '-' in online_range:
                        start, end = map(int, online_range.split('-'))
                        original_online_cpus = list(range(start, end + 1))
                    elif ',' in online_range:
                        original_online_cpus = [int(x) for x in online_range.split(',')]
                    else:
                        original_online_cpus = [int(online_range)]
            except:
                original_online_cpus = [0]
            
            self.logger.info(f"Original online CPUs: {original_online_cpus}")
            
            # Temporarily bring all CPUs online to read complete topology
            cpus_brought_online = []
            for cpu_id in self._possible_cpus:
                if cpu_id == 0:  # CPU 0 cannot be offlined
                    continue
                if cpu_id not in original_online_cpus:
                    try:
                        with open(f'/sys/devices/system/cpu/cpu{cpu_id}/online', 'w') as f:
                            f.write('1')
                        cpus_brought_online.append(cpu_id)
                        self.logger.debug(f"Brought CPU {cpu_id} online for topology mapping")
                    except Exception as e:
                        self.logger.debug(f"Could not bring CPU {cpu_id} online: {e}")
            
            # Brief pause for topology files to appear
            if cpus_brought_online:
                time.sleep(0.2)
            
            # Build topology map including sibling relationships
            physical_cores = {}
            self._cpu_siblings_map = {}  # Maps CPU ID to list of sibling CPU IDs
            
            for cpu_id in self._possible_cpus:
                try:
                    core_id_path = f'/sys/devices/system/cpu/cpu{cpu_id}/topology/core_id'
                    pkg_id_path = f'/sys/devices/system/cpu/cpu{cpu_id}/topology/physical_package_id'
                    siblings_path = f'/sys/devices/system/cpu/cpu{cpu_id}/topology/thread_siblings_list'
                    
                    if os.path.exists(core_id_path) and os.path.exists(pkg_id_path):
                        with open(core_id_path, 'r') as f:
                            core_id = int(f.read().strip())
                        with open(pkg_id_path, 'r') as f:
                            pkg_id = int(f.read().strip())
                        
                        phys_core_key = (pkg_id, core_id)
                        
                        if phys_core_key not in physical_cores:
                            physical_cores[phys_core_key] = cpu_id
                        
                        # Read sibling information for SMT awareness
                        if os.path.exists(siblings_path):
                            with open(siblings_path, 'r') as f:
                                siblings_str = f.read().strip()
                                siblings = []
                                if '-' in siblings_str:
                                    start, end = map(int, siblings_str.split('-'))
                                    siblings = list(range(start, end + 1))
                                elif ',' in siblings_str:
                                    siblings = [int(x) for x in siblings_str.split(',')]
                                else:
                                    siblings = [int(siblings_str)]
                                self._cpu_siblings_map[cpu_id] = siblings
                                self.logger.debug(f"CPU {cpu_id}: physical core {phys_core_key}, siblings: {siblings}")
                        
                except Exception as e:
                    self.logger.debug(f"Could not read topology for CPU {cpu_id}: {e}")
            
            # Restore original CPU online state
            for cpu_id in cpus_brought_online:
                if cpu_id not in original_online_cpus:
                    try:
                        with open(f'/sys/devices/system/cpu/cpu{cpu_id}/online', 'w') as f:
                            f.write('0')
                        self.logger.debug(f"Restored CPU {cpu_id} to offline state")
                    except Exception as e:
                        self.logger.debug(f"Could not restore CPU {cpu_id} to offline: {e}")
            
            # Cache the primary CPUs list
            self._primary_cpus_cache = sorted(physical_cores.values())
            self._topology_initialized = True
            
            # Log SMT detection
            smt_detected = any(len(siblings) > 1 for siblings in self._cpu_siblings_map.values() if siblings)
            self.logger.info(f"CPU topology initialized. Primary CPUs by physical core: {self._primary_cpus_cache}")
            self.logger.info(f"SMT detected: {smt_detected}")
            if smt_detected:
                self.logger.info(f"Sibling CPU mapping: {self._cpu_siblings_map}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize CPU topology: {e}")
            # Use fallback topology
            self._primary_cpus_cache = [0, 2, 4, 6] if len(self._possible_cpus) > 8 else [0, 1]
            self._cpu_siblings_map = {}
            self._topology_initialized = True
    
    def update_online_cpus(self):
        """Update the online CPUs list and refresh CPU settings if needed"""
        self._online_cpus = self._get_online_cpus()
        decky_plugin.logger.debug(f"Updated online CPUs list: {self._online_cpus}")
    
    def reapply_cpu_settings(self, current_boost: Optional[bool] = None, current_governor: Optional[str] = None, current_epp: Optional[str] = None):
        """Reapply CPU settings after topology changes (SMT toggle, core changes)"""
        try:
            # Update online CPUs first
            self.update_online_cpus()
            
            # Reapply boost setting if provided
            if current_boost is not None:
                decky_plugin.logger.info(f"Reapplying CPU boost: {current_boost} after topology change")
                self.set_cpu_boost(current_boost)
            
            # Reapply governor if provided
            if current_governor is not None:
                decky_plugin.logger.info(f"Reapplying CPU governor: {current_governor} after topology change")
                self.set_governor(current_governor)
                
            # Reapply EPP if provided
            if current_epp is not None:
                decky_plugin.logger.info(f"Reapplying EPP: {current_epp} after topology change")
                self.set_epp(current_epp)
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to reapply CPU settings after topology change: {e}")
    
    def _get_online_cpus(self) -> List[int]:
        """Get list of online CPU cores"""
        try:
            with open('/sys/devices/system/cpu/online', 'r') as f:
                online_str = f.read().strip()
            
            # Parse ranges like "0-7" or "0-3,6-7"
            cpus = []
            for part in online_str.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    cpus.extend(range(start, end + 1))
                else:
                    cpus.append(int(part))
            
            return cpus
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get online CPUs: {e}")
            return [0]  # Fallback to CPU 0
    
    def _detect_scaling_driver(self) -> Optional[ScalingDriver]:
        """Detect current scaling driver"""
        try:
            with open('/sys/devices/system/cpu/cpufreq/policy0/scaling_driver', 'r') as f:
                driver = f.read().strip()
            
            driver_map = {
                'intel_pstate': ScalingDriver.INTEL_PSTATE,
                'intel_cpufreq': ScalingDriver.INTEL_CPUFREQ,
                'amd-pstate-epp': ScalingDriver.AMD_PSTATE_EPP,
                'amd-pstate': ScalingDriver.AMD_PSTATE,
                'acpi-cpufreq': ScalingDriver.ACPI_CPUFREQ
            }
            
            return driver_map.get(driver)
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to detect scaling driver: {e}")
            return None
    
    def get_scaling_driver(self) -> Optional[str]:
        """Get scaling driver name"""
        return self._scaling_driver.value if self._scaling_driver else None
    
    # CPU Governor Management
    def get_available_governors(self) -> List[str]:
        """Get list of available CPU governors"""
        try:
            path = f"/sys/devices/system/cpu/cpu{self._online_cpus[0]}/cpufreq/scaling_available_governors"
            if os.path.exists(path):
                with open(path, 'r') as f:
                    governors = f.read().strip().split()
                return list(reversed(governors))  # Reverse for better UI ordering
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get available governors: {e}")
        
        return []
    
    def get_current_governor(self) -> Optional[str]:
        """Get current CPU governor"""
        try:
            path = f"/sys/devices/system/cpu/cpu{self._online_cpus[0]}/cpufreq/scaling_governor"
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return f.read().strip()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get current governor: {e}")
        
        return None
    
    def set_governor(self, governor: str) -> bool:
        """Set CPU governor for all cores"""
        if governor not in self.get_available_governors():
            decky_plugin.logger.error(f"Governor {governor} not available")
            return False
        
        try:
            success_count = 0
            for cpu in self._online_cpus:
                path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
                if os.path.exists(path):
                    try:
                        with open(path, 'w') as f:
                            f.write(governor)
                        success_count += 1
                    except Exception as e:
                        decky_plugin.logger.error(f"Failed to set governor for CPU {cpu}: {e}")
            
            decky_plugin.logger.info(f"Set governor {governor} for {success_count}/{len(self._online_cpus)} CPUs")
            return success_count > 0
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set governor: {e}")
            return False
    
    # Energy Performance Preference (EPP) Management
    def get_available_epp_options(self) -> List[str]:
        """Get available EPP options"""
        try:
            path = f"/sys/devices/system/cpu/cpu{self._online_cpus[0]}/cpufreq/energy_performance_available_preferences"
            if os.path.exists(path):
                with open(path, 'r') as f:
                    options = f.read().strip().split()
                # Remove 'default' if present and reverse for better ordering
                if 'default' in options:
                    options.remove('default')
                return list(reversed(options))
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get available EPP options: {e}")
        
        return []
    
    def get_current_epp(self) -> Optional[str]:
        """Get current EPP setting"""
        try:
            path = f"/sys/devices/system/cpu/cpu{self._online_cpus[0]}/cpufreq/energy_performance_preference"
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return f.read().strip()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get current EPP: {e}")
        
        return None
    
    def set_epp(self, epp: str) -> bool:
        """Set Energy Performance Preference for all cores"""
        available_options = self.get_available_epp_options()
        if epp not in available_options:
            decky_plugin.logger.error(f"EPP {epp} not available. Available: {available_options}")
            return False
        
        # Check if EPP can be changed (not blocked by performance governor)
        current_governor = self.get_current_governor()
        if (current_governor == "performance" and 
            self._scaling_driver in [ScalingDriver.AMD_PSTATE_EPP, ScalingDriver.INTEL_PSTATE]):
            decky_plugin.logger.warning("EPP cannot be changed while governor is set to performance")
            return False
        
        try:
            success_count = 0
            for cpu in self._online_cpus:
                path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/energy_performance_preference"
                if os.path.exists(path):
                    try:
                        with open(path, 'w') as f:
                            f.write(epp)
                        success_count += 1
                    except OSError as e:
                        if e.errno == 16:  # Device or resource busy
                            decky_plugin.logger.warning(f"CPU {cpu} busy, skipping EPP change")
                        else:
                            decky_plugin.logger.error(f"Failed to set EPP for CPU {cpu}: {e}")
                    except Exception as e:
                        decky_plugin.logger.error(f"Failed to set EPP for CPU {cpu}: {e}")
            
            decky_plugin.logger.info(f"Set EPP {epp} for {success_count}/{len(self._online_cpus)} CPUs")
            return success_count > 0
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set EPP: {e}")
            return False
    
    def supports_epp(self) -> bool:
        """Check if EPP is supported"""
        path = f"/sys/devices/system/cpu/cpu{self._online_cpus[0]}/cpufreq/energy_performance_preference"
        return os.path.exists(path)
    
    # CPU Boost Management
    def supports_cpu_boost(self) -> bool:
        """Check if CPU boost is supported"""
        intel_path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
        amd_legacy_path = "/sys/devices/system/cpu/cpufreq/boost"
        per_cpu_boost = f"/sys/devices/system/cpu/cpufreq/policy{self._online_cpus[0]}/boost"
        
        return any(os.path.exists(path) for path in [intel_path, amd_legacy_path, per_cpu_boost])
    
    def get_cpu_boost_enabled(self) -> Optional[bool]:
        """Get current CPU boost status"""
        try:
            # Intel: no_turbo (inverted logic)
            intel_path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
            if os.path.exists(intel_path):
                with open(intel_path, 'r') as f:
                    return f.read().strip() == "0"  # 0 = turbo enabled
            
            # AMD per-CPU boost
            per_cpu_boost = f"/sys/devices/system/cpu/cpufreq/policy{self._online_cpus[0]}/boost"
            if os.path.exists(per_cpu_boost):
                with open(per_cpu_boost, 'r') as f:
                    return f.read().strip() == "1"
            
            # AMD legacy boost
            amd_legacy_path = "/sys/devices/system/cpu/cpufreq/boost"
            if os.path.exists(amd_legacy_path):
                with open(amd_legacy_path, 'r') as f:
                    return f.read().strip() == "1"
                    
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get CPU boost status: {e}")
        
        return None
    
    def set_cpu_boost(self, enabled: bool) -> bool:
        """Set CPU boost enabled/disabled with proper AMD/Intel handling and frequency limits"""
        try:
            boost_success = False
            
            # Intel: no_turbo (inverted logic)
            intel_path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
            if os.path.exists(intel_path):
                with open(intel_path, 'w') as f:
                    f.write("0" if enabled else "1")
                decky_plugin.logger.info(f"Set Intel turbo boost: {enabled}")
                boost_success = True
            
            # AMD: Try global boost first (more reliable)
            amd_legacy_path = "/sys/devices/system/cpu/cpufreq/boost"
            if os.path.exists(amd_legacy_path):
                try:
                    with open(amd_legacy_path, 'w') as f:
                        f.write("1" if enabled else "0")
                    decky_plugin.logger.info(f"Set AMD global CPU boost: {enabled}")
                    boost_success = True
                except Exception as e:
                    decky_plugin.logger.warning(f"AMD global boost failed, trying per-CPU: {e}")
            
            # AMD per-CPU boost (fallback only)
            if not boost_success:
                success_count = 0
                total_attempts = 0
                for cpu in self._online_cpus:
                    per_cpu_boost = f"/sys/devices/system/cpu/cpufreq/policy{cpu}/boost"
                    if os.path.exists(per_cpu_boost):
                        total_attempts += 1
                        try:
                            with open(per_cpu_boost, 'w') as f:
                                f.write("1" if enabled else "0")
                            success_count += 1
                        except Exception as e:
                            decky_plugin.logger.warning(f"Failed to set per-CPU boost for CPU {cpu}: {e}")
                
                if total_attempts > 0 and success_count == total_attempts:
                    decky_plugin.logger.info(f"Set per-CPU boost {enabled} for {success_count}/{total_attempts} CPUs")
                    boost_success = True
                elif total_attempts > 0:
                    decky_plugin.logger.error(f"Per-CPU boost partially failed: {success_count}/{total_attempts} CPUs succeeded")
                    return False
            
            # Enforce frequency limits based on boost state
            if boost_success:
                freq_range = self.get_cpu_frequency_range()
                if freq_range:
                    if enabled:
                        # Boost enabled: Allow full frequency range
                        limit_success = self.set_cpu_frequency_limits(
                            min_freq_khz=freq_range['min_freq_khz'],
                            max_freq_khz=freq_range['max_freq_khz']
                        )
                        if limit_success:
                            decky_plugin.logger.info(f"Set frequency limits to full range for boost enabled")
                    else:
                        # Boost disabled: Limit to base frequency (cpuinfo_max_freq)
                        base_freq = freq_range['max_freq_khz']  # This is the base frequency when boost is disabled
                        limit_success = self.set_cpu_frequency_limits(
                            min_freq_khz=freq_range['min_freq_khz'],
                            max_freq_khz=base_freq
                        )
                        if limit_success:
                            decky_plugin.logger.info(f"Set frequency limits to base frequency {base_freq//1000}MHz for boost disabled")
                        else:
                            decky_plugin.logger.warning(f"Failed to set frequency limits for boost disabled")
                else:
                    decky_plugin.logger.warning("Could not determine frequency range for boost-based limits")
            
            return boost_success
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set CPU boost: {e}")
        
        decky_plugin.logger.error("No working CPU boost control method found")
        return False
    
    # SMT (Simultaneous Multithreading) Management
    def supports_smt(self) -> bool:
        """Check if SMT control is supported"""
        return os.path.exists("/sys/devices/system/cpu/smt/control")
    
    def get_smt_enabled(self) -> Optional[bool]:
        """Get current SMT status"""
        try:
            with open("/sys/devices/system/cpu/smt/control", 'r') as f:
                status = f.read().strip()
                return status == "on"
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get SMT status: {e}")
        
        return None
    
    def set_smt(self, enabled: bool) -> bool:
        """Set SMT enabled/disabled"""
        try:
            with open("/sys/devices/system/cpu/smt/control", 'w') as f:
                f.write("on" if enabled else "off")
            decky_plugin.logger.info(f"Set SMT: {enabled}")
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set SMT: {e}")
            return False
    
    # P-State Management
    def get_pstate_status(self) -> Optional[str]:
        """Get P-State driver status"""
        try:
            # AMD P-State
            amd_path = "/sys/devices/system/cpu/amd_pstate/status"
            if os.path.exists(amd_path):
                with open(amd_path, 'r') as f:
                    return f.read().strip()
            
            # Intel P-State
            intel_path = "/sys/devices/system/cpu/intel_pstate/status"
            if os.path.exists(intel_path):
                with open(intel_path, 'r') as f:
                    return f.read().strip()
                    
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get P-State status: {e}")
        
        return None
    
    def get_pstate_active(self) -> bool:
        """Set P-State to active mode"""
        try:
            # AMD P-State
            amd_path = "/sys/devices/system/cpu/amd_pstate/status"
            if os.path.exists(amd_path):
                with open(amd_path, 'w') as f:
                    f.write("active")
                return True
            
            # Intel P-State
            intel_path = "/sys/devices/system/cpu/intel_pstate/status"
            if os.path.exists(intel_path):
                with open(intel_path, 'w') as f:
                    f.write("active")
                return True
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set P-State active: {e}")
        
        return False
    
    # Core Management with C-State Optimization
    def get_available_cstates(self, cpu: int = 0) -> List[Dict[str, str]]:
        """Get available C-states for a CPU core"""
        cstates = []
        try:
            cpuidle_path = f"/sys/devices/system/cpu/cpu{cpu}/cpuidle"
            if os.path.exists(cpuidle_path):
                for state_dir in sorted(os.listdir(cpuidle_path)):
                    if state_dir.startswith('state'):
                        state_path = os.path.join(cpuidle_path, state_dir)
                        try:
                            with open(os.path.join(state_path, 'name'), 'r') as f:
                                name = f.read().strip()
                            with open(os.path.join(state_path, 'desc'), 'r') as f:
                                desc = f.read().strip()
                            
                            cstates.append({
                                'state': state_dir,
                                'name': name,
                                'description': desc,
                                'path': state_path
                            })
                        except Exception as e:
                            decky_plugin.logger.warning(f"Failed to read C-state {state_dir}: {e}")
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get C-states for CPU {cpu}: {e}")
        
        return cstates
    
    def get_deepest_available_cstate(self, cpu: int = 0) -> Optional[str]:
        """Find the deepest available C-state for a CPU core"""
        try:
            available_states = self.get_available_cstates(cpu)
            if not available_states:
                decky_plugin.logger.warning(f"No C-states available for CPU {cpu}")
                return None
            
            # Priority order for deepest C-states (prefer deeper states for better power savings)
            preferred_states = ['C10', 'C9', 'C8', 'C7', 'C6', 'C3', 'C2', 'C1']
            
            for preferred in preferred_states:
                for state in available_states:
                    if state['name'] == preferred:
                        decky_plugin.logger.info(f"Found deepest available C-state: {preferred} for CPU {cpu}")
                        return preferred
            
            # Fallback to the last available state (should be deepest)
            if available_states:
                deepest = available_states[-1]['name']
                decky_plugin.logger.info(f"Using fallback deepest C-state: {deepest} for CPU {cpu}")
                return deepest
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to find deepest C-state for CPU {cpu}: {e}")
        
        return None
    
    def force_cpu_to_cstate(self, cpu: int, target_state: str = None) -> bool:
        """Force a CPU core into a specific C-state before offlining"""
        try:
            # Auto-detect deepest available C-state if not specified
            if target_state is None:
                target_state = self.get_deepest_available_cstate(cpu)
                if target_state is None:
                    decky_plugin.logger.warning(f"No suitable C-state found for CPU {cpu}")
                    return False
            
            cpuidle_path = f"/sys/devices/system/cpu/cpu{cpu}/cpuidle"
            if not os.path.exists(cpuidle_path):
                decky_plugin.logger.warning(f"CPU {cpu} doesn't support cpuidle")
                return False
            
            # Find the target C-state
            target_state_path = None
            available_states = self.get_available_cstates(cpu)
            
            for state in available_states:
                if state['name'] == target_state:
                    target_state_path = state['path']
                    break
            
            if not target_state_path:
                decky_plugin.logger.warning(f"Target C-state {target_state} not found for CPU {cpu}")
                return False
            
            # Disable all deeper C-states temporarily to force CPU into target state
            deeper_states = []
            for state in available_states:
                if state['name'] in ['C6', 'C7', 'C8', 'C9', 'C10']:  # Deeper than C3
                    disable_path = os.path.join(state['path'], 'disable')
                    if os.path.exists(disable_path):
                        try:
                            # Read current state
                            with open(disable_path, 'r') as f:
                                current_disabled = f.read().strip()
                            deeper_states.append((disable_path, current_disabled))
                            
                            # Temporarily disable deeper states
                            with open(disable_path, 'w') as f:
                                f.write('1')
                        except Exception as e:
                            decky_plugin.logger.warning(f"Failed to disable deeper C-state {state['name']}: {e}")
            
            # Force CPU into idle state by setting CPU frequency to minimum temporarily
            try:
                freq_min_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_min_freq"
                freq_max_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_max_freq"
                
                original_min_freq = None
                original_max_freq = None
                
                if os.path.exists(freq_min_path) and os.path.exists(freq_max_path):
                    # Read original frequencies
                    with open(freq_min_path, 'r') as f:
                        original_min_freq = f.read().strip()
                    with open(freq_max_path, 'r') as f:
                        original_max_freq = f.read().strip()
                    
                    # Set to minimum frequency to encourage idle state
                    with open(freq_max_path, 'w') as f:
                        f.write(original_min_freq)
                    
                    # Give the CPU time to enter the target C-state
                    import time
                    time.sleep(0.1)  # 100ms should be enough
                    
                    # Restore original frequency settings
                    with open(freq_max_path, 'w') as f:
                        f.write(original_max_freq)
                        
            except Exception as e:
                decky_plugin.logger.warning(f"Failed to temporarily adjust CPU {cpu} frequency: {e}")
            
            # Restore deeper C-state settings
            for disable_path, original_state in deeper_states:
                try:
                    with open(disable_path, 'w') as f:
                        f.write(original_state)
                except Exception as e:
                    decky_plugin.logger.warning(f"Failed to restore C-state setting: {e}")
            
            decky_plugin.logger.info(f"Forced CPU {cpu} into {target_state} before offlining")
            return True
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to force CPU {cpu} to C-state {target_state}: {e}")
            return False
    
    def offline_cpu_with_cstate_prep(self, cpu: int, target_cstate: str = None) -> bool:
        """Offline a CPU core after forcing it into a deep C-state for better power savings"""
        if cpu == 0:
            decky_plugin.logger.warning("Cannot offline CPU 0 (bootstrap processor)")
            return False
        
        try:
            online_path = f"/sys/devices/system/cpu/cpu{cpu}/online"
            if not os.path.exists(online_path):
                decky_plugin.logger.warning(f"CPU {cpu} cannot be controlled (no online file)")
                return False
            
            # Check if CPU is already offline
            with open(online_path, 'r') as f:
                current_state = f.read().strip()
            
            if current_state == "0":
                decky_plugin.logger.info(f"CPU {cpu} is already offline")
                return True
            
            # Auto-detect or use specified C-state
            if target_cstate is None:
                target_cstate = self.get_deepest_available_cstate(cpu)
                if target_cstate is None:
                    decky_plugin.logger.warning(f"No suitable C-state found for CPU {cpu}, proceeding without C-state prep")
                    # Continue with offline without C-state preparation
                else:
                    decky_plugin.logger.info(f"Auto-detected target C-state: {target_cstate} for CPU {cpu}")
            
            # Force CPU into target C-state before offlining (if available)
            if target_cstate:
                decky_plugin.logger.info(f"Preparing CPU {cpu} for offline by forcing into {target_cstate}")
                self.force_cpu_to_cstate(cpu, target_cstate)
            
            # Now offline the CPU
            with open(online_path, 'w') as f:
                f.write("0")
            
            decky_plugin.logger.info(f"Successfully offlined CPU {cpu} after C-state preparation")
            return True
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to offline CPU {cpu} with C-state prep: {e}")
            return False
    
    def online_cpu(self, cpu: int) -> bool:
        """Bring a CPU core online"""
        if cpu == 0:
            decky_plugin.logger.info("CPU 0 is always online (bootstrap processor)")
            return True
        
        try:
            online_path = f"/sys/devices/system/cpu/cpu{cpu}/online"
            if not os.path.exists(online_path):
                decky_plugin.logger.warning(f"CPU {cpu} cannot be controlled (no online file)")
                return False
            
            # Check if CPU is already online
            with open(online_path, 'r') as f:
                current_state = f.read().strip()
            
            if current_state == "1":
                decky_plugin.logger.info(f"CPU {cpu} is already online")
                return True
            
            # Bring CPU online
            with open(online_path, 'w') as f:
                f.write("1")
            
            decky_plugin.logger.info(f"Successfully brought CPU {cpu} online")
            return True
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to bring CPU {cpu} online: {e}")
            return False
    
    def get_cpu_topology(self) -> Dict[int, Dict[str, Any]]:
        """Get CPU topology mapping physical cores to logical CPUs using sysfs"""
        topology = {}
        try:
            # Use sysfs to get topology for all possible CPUs (not just online ones)
            for cpu in self._possible_cpus:
                core_id_path = f"/sys/devices/system/cpu/cpu{cpu}/topology/core_id"
                physical_id_path = f"/sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id"
                
                if os.path.exists(core_id_path):
                    try:
                        with open(core_id_path, 'r') as f:
                            core_id = int(f.read().strip())
                        
                        physical_id = 0  # Default to 0
                        if os.path.exists(physical_id_path):
                            with open(physical_id_path, 'r') as f:
                                physical_id = int(f.read().strip())
                        
                        topology[cpu] = {
                            'physical_id': physical_id,
                            'core_id': core_id,
                            'logical_cpu': cpu
                        }
                    except Exception as e:
                        decky_plugin.logger.warning(f"Failed to read topology for CPU {cpu}: {e}")
        
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get CPU topology: {e}")
        
        return topology
    
    def get_primary_cpus_by_physical_core(self) -> List[int]:
        """Get list of primary CPU IDs for each physical core (uses cached topology)."""
        # Initialize topology if not done yet
        if not self._topology_initialized:
            self.initialize_cpu_topology()
        
        # Return cached primary CPUs
        return self._primary_cpus_cache if self._primary_cpus_cache else [0]
    
    def get_cpu_siblings(self, cpu_id: int) -> List[int]:
        """Get list of sibling logical CPUs for a given CPU (including itself)."""
        if not self._topology_initialized:
            self.initialize_cpu_topology()
        
        return self._cpu_siblings_map.get(cpu_id, [cpu_id])
    
    def is_smt_enabled(self) -> bool:
        """Check if SMT (Simultaneous Multithreading) is enabled."""
        try:
            with open('/sys/devices/system/cpu/smt/active', 'r') as f:
                return f.read().strip() == '1'
        except:
            # Fallback: check if any CPU has multiple siblings
            if not self._topology_initialized:
                self.initialize_cpu_topology()
            return any(len(siblings) > 1 for siblings in self._cpu_siblings_map.values() if siblings)
    
    def online_physical_core(self, primary_cpu: int) -> bool:
        """Bring online a complete physical core (primary + all sibling logical CPUs)."""
        try:
            siblings = self.get_cpu_siblings(primary_cpu)
            decky_plugin.logger.debug(f"Bringing online physical core with primary CPU {primary_cpu}, siblings: {siblings}")
            
            success = True
            for cpu in siblings:
                if cpu == 0:
                    # CPU 0 is always online, just log it
                    decky_plugin.logger.debug(f"CPU 0 is always online (part of physical core {primary_cpu})")
                    continue
                if not self.online_cpu(cpu):
                    decky_plugin.logger.warning(f"Failed to bring online sibling CPU {cpu}")
                    success = False
                    
            return success
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to online physical core {primary_cpu}: {e}")
            return False
    
    def offline_physical_core(self, primary_cpu: int) -> bool:
        """Offline a complete physical core (primary + all sibling logical CPUs)."""
        try:
            siblings = self.get_cpu_siblings(primary_cpu)
            decky_plugin.logger.debug(f"Offlining physical core with primary CPU {primary_cpu}, siblings: {siblings}")
            
            success = True
            for cpu in siblings:
                if cpu == 0:
                    continue  # Never offline CPU 0
                if not self.offline_cpu_with_cstate_prep(cpu):
                    decky_plugin.logger.warning(f"Failed to offline sibling CPU {cpu}")
                    success = False
                    
            return success
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to offline physical core {primary_cpu}: {e}")
            return False
    
    def set_cpu_cores_with_cstate_optimization(self, target_cores: int) -> bool:
        """Set number of active CPU cores with SMT-aware topology and C-state optimization"""
        try:
            # Get topology-aware CPU list (primary CPUs for each physical core)
            primary_cpus = self.get_primary_cpus_by_physical_core()
            max_physical_cores = len(primary_cpus)
            smt_enabled = self.is_smt_enabled()
            
            if target_cores < 1:
                target_cores = 1
            if target_cores > max_physical_cores:
                target_cores = max_physical_cores
            
            decky_plugin.logger.info(f"Setting CPU cores to {target_cores} with SMT-aware C-state optimization")
            decky_plugin.logger.info(f"Available primary CPUs: {primary_cpus}, SMT enabled: {smt_enabled}")
            
            success = True
            
            # First, bring online the needed physical cores (including all sibling logical CPUs)
            for i in range(target_cores):
                primary_cpu = primary_cpus[i]
                
                if smt_enabled:
                    # With SMT, manage the entire physical core (primary + siblings)
                    if not self.online_physical_core(primary_cpu):
                        decky_plugin.logger.warning(f"Failed to bring online physical core {i} (primary CPU {primary_cpu})")
                        success = False
                else:
                    # Without SMT, just manage the primary CPU
                    if primary_cpu != 0 and not self.online_cpu(primary_cpu):
                        decky_plugin.logger.warning(f"Failed to bring online primary CPU {primary_cpu} for physical core {i}")
                        success = False
            
            # Then, offline excess physical cores (including all sibling logical CPUs)
            for i in range(target_cores, max_physical_cores):
                primary_cpu = primary_cpus[i]
                if primary_cpu == 0:
                    continue  # Never offline CPU 0 or its siblings
                
                if smt_enabled:
                    # With SMT, offline the entire physical core (primary + siblings)
                    if not self.offline_physical_core(primary_cpu):
                        decky_plugin.logger.warning(f"Failed to offline physical core {i} (primary CPU {primary_cpu})")
                        success = False
                else:
                    # Without SMT, just offline the primary CPU
                    if not self.offline_cpu_with_cstate_prep(primary_cpu):
                        decky_plugin.logger.warning(f"Failed to offline primary CPU {primary_cpu} for physical core {i}")
                        success = False
            
            # Update internal state
            self.update_online_cpus()
            
            if success:
                decky_plugin.logger.info(f"Successfully configured {target_cores} CPU cores with SMT-aware C-state optimization")
            else:
                decky_plugin.logger.warning(f"Some operations failed while configuring CPU cores")
            
            return success
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set CPU cores with C-state optimization: {e}")
            return False
    
    def get_cpu_cstate_info(self) -> Dict[str, Any]:
        """Get comprehensive C-state information for all CPUs"""
        cstate_info = {}
        
        try:
            for cpu in self._online_cpus:
                cpu_info = {
                    'available_cstates': self.get_available_cstates(cpu),
                    'current_usage': {}
                }
                
                # Get usage statistics for each C-state
                cpuidle_path = f"/sys/devices/system/cpu/cpu{cpu}/cpuidle"
                if os.path.exists(cpuidle_path):
                    for state_dir in os.listdir(cpuidle_path):
                        if state_dir.startswith('state'):
                            try:
                                usage_path = os.path.join(cpuidle_path, state_dir, 'usage')
                                time_path = os.path.join(cpuidle_path, state_dir, 'time')
                                
                                usage = "0"
                                time_spent = "0"
                                
                                if os.path.exists(usage_path):
                                    with open(usage_path, 'r') as f:
                                        usage = f.read().strip()
                                
                                if os.path.exists(time_path):
                                    with open(time_path, 'r') as f:
                                        time_spent = f.read().strip()
                                
                                cpu_info['current_usage'][state_dir] = {
                                    'usage_count': int(usage),
                                    'time_microseconds': int(time_spent)
                                }
                            except Exception as e:
                                decky_plugin.logger.warning(f"Failed to read C-state usage for CPU {cpu} {state_dir}: {e}")
                
                cstate_info[f'cpu{cpu}'] = cpu_info
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get C-state info: {e}")
        
        return cstate_info
    
    def get_online_cpu_cores(self) -> int:
        """Get current number of online CPU cores"""
        return len(self._online_cpus)
    
    # CPU Frequency Management
    def get_cpu_frequency_range(self) -> Optional[Dict[str, int]]:
        """Get CPU frequency range (min/max in kHz)"""
        try:
            cpu0_path = "/sys/devices/system/cpu/cpu0/cpufreq"
            min_freq_path = f"{cpu0_path}/cpuinfo_min_freq"
            max_freq_path = f"{cpu0_path}/cpuinfo_max_freq"
            
            if os.path.exists(min_freq_path) and os.path.exists(max_freq_path):
                with open(min_freq_path, 'r') as f:
                    min_freq = int(f.read().strip())
                with open(max_freq_path, 'r') as f:
                    max_freq = int(f.read().strip())
                
                return {
                    'min_freq_khz': min_freq,
                    'max_freq_khz': max_freq,
                    'min_freq_mhz': min_freq // 1000,
                    'max_freq_mhz': max_freq // 1000
                }
        except Exception as e:
            decky_plugin.logger.error(f"Failed to get CPU frequency range: {e}")
        
        return None
    
    def get_current_cpu_frequencies(self) -> Dict[int, int]:
        """Get current CPU frequencies for all online cores (in kHz)"""
        frequencies = {}
        for cpu in self._online_cpus:
            try:
                freq_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq"
                if os.path.exists(freq_path):
                    with open(freq_path, 'r') as f:
                        frequencies[cpu] = int(f.read().strip())
            except Exception as e:
                decky_plugin.logger.warning(f"Failed to get frequency for CPU {cpu}: {e}")
        
        return frequencies
    
    def get_cpu_frequency_limits(self) -> Dict[int, Dict[str, int]]:
        """Get current frequency limits for all online cores (in kHz)"""
        limits = {}
        for cpu in self._online_cpus:
            try:
                cpu_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq"
                min_path = f"{cpu_path}/scaling_min_freq"
                max_path = f"{cpu_path}/scaling_max_freq"
                
                if os.path.exists(min_path) and os.path.exists(max_path):
                    with open(min_path, 'r') as f:
                        min_freq = int(f.read().strip())
                    with open(max_path, 'r') as f:
                        max_freq = int(f.read().strip())
                    
                    limits[cpu] = {
                        'min_freq_khz': min_freq,
                        'max_freq_khz': max_freq
                    }
            except Exception as e:
                decky_plugin.logger.warning(f"Failed to get frequency limits for CPU {cpu}: {e}")
        
        return limits
    
    def set_cpu_frequency_limits(self, min_freq_khz: Optional[int] = None, max_freq_khz: Optional[int] = None) -> bool:
        """Set CPU frequency limits for all online cores
        
        Args:
            min_freq_khz: Minimum frequency in kHz (None to skip)
            max_freq_khz: Maximum frequency in kHz (None to skip)
        
        Returns:
            True if all changes succeeded, False otherwise
        """
        if min_freq_khz is None and max_freq_khz is None:
            decky_plugin.logger.warning("No frequency limits specified")
            return False
        
        # Validate frequency range
        freq_range = self.get_cpu_frequency_range()
        if not freq_range:
            decky_plugin.logger.error("Could not determine CPU frequency range")
            return False
        
        if min_freq_khz is not None:
            if min_freq_khz < freq_range['min_freq_khz'] or min_freq_khz > freq_range['max_freq_khz']:
                decky_plugin.logger.error(f"Invalid min frequency {min_freq_khz}kHz. Range: {freq_range['min_freq_khz']}-{freq_range['max_freq_khz']}kHz")
                return False
        
        if max_freq_khz is not None:
            if max_freq_khz < freq_range['min_freq_khz'] or max_freq_khz > freq_range['max_freq_khz']:
                decky_plugin.logger.error(f"Invalid max frequency {max_freq_khz}kHz. Range: {freq_range['min_freq_khz']}-{freq_range['max_freq_khz']}kHz")
                return False
        
        if min_freq_khz is not None and max_freq_khz is not None and min_freq_khz > max_freq_khz:
            decky_plugin.logger.error(f"Min frequency {min_freq_khz}kHz cannot be greater than max frequency {max_freq_khz}kHz")
            return False
        
        success_count = 0
        total_attempts = 0
        
        for cpu in self._online_cpus:
            cpu_path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq"
            min_path = f"{cpu_path}/scaling_min_freq"
            max_path = f"{cpu_path}/scaling_max_freq"
            
            # Check if frequency control files exist
            if not (os.path.exists(min_path) and os.path.exists(max_path)):
                decky_plugin.logger.warning(f"Frequency control not available for CPU {cpu}")
                continue
            
            total_attempts += 1
            cpu_success = True
            
            try:
                # Read current limits
                with open(min_path, 'r') as f:
                    current_min = int(f.read().strip())
                with open(max_path, 'r') as f:
                    current_max = int(f.read().strip())
                
                # For AMD P-state driver, we need to be careful about the order
                # Always set max frequency first when increasing limits
                # Always set min frequency first when decreasing limits
                
                if max_freq_khz is not None:
                    # If we're lowering the max frequency, we might need to lower min first
                    if max_freq_khz < current_max and current_min > max_freq_khz:
                        # Lower min frequency first to avoid conflicts
                        try:
                            with open(min_path, 'w') as f:
                                f.write(str(max_freq_khz))
                            decky_plugin.logger.debug(f"CPU {cpu}: Temporarily set min freq to {max_freq_khz}kHz")
                        except Exception as e:
                            decky_plugin.logger.warning(f"CPU {cpu}: Failed to temporarily adjust min frequency: {e}")
                    
                    # Set max frequency
                    try:
                        with open(max_path, 'w') as f:
                            f.write(str(max_freq_khz))
                        decky_plugin.logger.debug(f"CPU {cpu}: Set max frequency to {max_freq_khz}kHz")
                    except Exception as e:
                        decky_plugin.logger.error(f"CPU {cpu}: Failed to set max frequency to {max_freq_khz}kHz: {e}")
                        cpu_success = False
                
                if min_freq_khz is not None and cpu_success:
                    # Set min frequency
                    try:
                        with open(min_path, 'w') as f:
                            f.write(str(min_freq_khz))
                        decky_plugin.logger.debug(f"CPU {cpu}: Set min frequency to {min_freq_khz}kHz")
                    except Exception as e:
                        decky_plugin.logger.error(f"CPU {cpu}: Failed to set min frequency to {min_freq_khz}kHz: {e}")
                        cpu_success = False
                
                if cpu_success:
                    success_count += 1
                    
            except Exception as e:
                decky_plugin.logger.error(f"CPU {cpu}: Failed to set frequency limits: {e}")
        
        if success_count == total_attempts and total_attempts > 0:
            limits_str = []
            if min_freq_khz is not None:
                limits_str.append(f"min: {min_freq_khz}kHz")
            if max_freq_khz is not None:
                limits_str.append(f"max: {max_freq_khz}kHz")
            decky_plugin.logger.info(f"Set CPU frequency limits ({', '.join(limits_str)}) for {success_count} CPUs")
            return True
        elif total_attempts > 0:
            decky_plugin.logger.error(f"CPU frequency limits partially failed: {success_count}/{total_attempts} CPUs succeeded")
            return False
        else:
            decky_plugin.logger.error("No CPUs available for frequency limit control")
            return False
    
    def reset_cpu_frequency_limits(self) -> bool:
        """Reset CPU frequency limits to hardware defaults"""
        freq_range = self.get_cpu_frequency_range()
        if not freq_range:
            decky_plugin.logger.error("Could not determine CPU frequency range for reset")
            return False
        
        return self.set_cpu_frequency_limits(
            min_freq_khz=freq_range['min_freq_khz'],
            max_freq_khz=freq_range['max_freq_khz']
        )
    
    def get_cpu_info(self) -> Dict[str, Any]:
        """Get comprehensive CPU information"""
        info = {
            'scaling_driver': self.get_scaling_driver(),
            'available_governors': self.get_available_governors(),
            'current_governor': self.get_current_governor(),
            'available_epp_options': self.get_available_epp_options(),
            'current_epp': self.get_current_epp(),
            'supports_cpu_boost': self.supports_cpu_boost(),
            'cpu_boost_enabled': self.get_cpu_boost_enabled(),
            'supports_smt': self.supports_smt(),
            'smt_enabled': self.get_smt_enabled(),
            'supports_epp': self.supports_epp(),
            'pstate_status': self.get_pstate_status(),
            'online_cpus': len(self._online_cpus),
            'total_cpus': len(self._possible_cpus),
            'max_cpu_cores': len(self._possible_cpus),  # For backward compatibility
            'frequency_range': self.get_cpu_frequency_range(),
            'current_frequencies': self.get_current_cpu_frequencies(),
            'frequency_limits': self.get_cpu_frequency_limits()
        }
        return info

# Global CPU manager instance
_cpu_manager = None

def get_cpu_manager() -> CPUManager:
    """Get global CPU manager instance"""
    global _cpu_manager
    if _cpu_manager is None:
        _cpu_manager = CPUManager()
    return _cpu_manager
