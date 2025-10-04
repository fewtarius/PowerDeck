"""
Enhanced Sleep/Wake Manager for PowerDeck - Event-Driven Detection

This module provides PROPER sleep/wake detection using real system events:
1. Monitors /sys/power/suspend_stats/success counter for suspend cycles
2. Uses systemd journal monitoring for immediate event detection  
3. Event-driven triggers instead of unreliable polling timers

Author: PowerDeck Development Team
"""

import asyncio
import json
import os
import time
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Callable
import tempfile

# Decky plugin imports
import decky


@dataclass
class SleepWakeEvent:
    """Sleep/wake event data structure"""
    timestamp: float
    event_type: str  # 'sleep' or 'wake'
    detection_method: str  # 'suspend_counter', 'journal_monitor', 'manual'
    ac_power_before: Optional[bool] = None
    ac_power_after: Optional[bool] = None
    profile_before: Optional[str] = None
    profile_after: Optional[str] = None
    gpu_mode_before: Optional[str] = None
    gpu_mode_after: Optional[str] = None
    hardware_reinitialized: bool = False
    settings_restored: bool = False
    error_message: Optional[str] = None


class EnhancedSleepWakeManager:
    """PROPER event-driven sleep/wake detection and handling"""
    
    def __init__(self, plugin_instance):
        self.plugin = plugin_instance
        
        # Event detection state
        self.monitoring_active = False
        self.last_suspend_count = None
        self.suspend_stats_file = "/sys/power/suspend_stats/success"
        
        # State tracking
        self.pre_sleep_state = {}
        self.pre_sleep_state_file = "/tmp/powerdeck_pre_sleep_state.json"
        
        # Event callbacks
        self.sleep_wake_callbacks: List[Callable] = []
        
        # Monitoring tasks
        self.monitor_tasks = []
        
        decky.logger.info("Enhanced Sleep/Wake Manager initialized (Event-Driven)")
    
    async def start_monitoring(self):
        """Start event-driven sleep/wake monitoring"""
        if self.monitoring_active:
            return
            
        self.monitoring_active = True
        decky.logger.info("Starting event-driven sleep/wake monitoring")
        
        # Initialize suspend counter
        await self._initialize_suspend_counter()
        
        # Start monitoring tasks
        self.monitor_tasks = [
            asyncio.create_task(self._suspend_counter_monitor()),
            asyncio.create_task(self._journal_monitor()),
        ]
        
        decky.logger.info("Event-driven sleep/wake monitoring started")
    
    async def stop_monitoring(self):
        """Stop all monitoring"""
        self.monitoring_active = False
        
        # Cancel all monitoring tasks
        for task in self.monitor_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.monitor_tasks.clear()
        decky.logger.info("Event-driven sleep/wake monitoring stopped")
    
    async def _initialize_suspend_counter(self):
        """Initialize the suspend success counter"""
        try:
            if os.path.exists(self.suspend_stats_file):
                with open(self.suspend_stats_file, 'r') as f:
                    self.last_suspend_count = int(f.read().strip())
                    decky.logger.info(f"Initial suspend count: {self.last_suspend_count}")
            else:
                decky.logger.warning("Suspend stats file not found - counter monitoring disabled")
                self.last_suspend_count = None
        except Exception as e:
            decky.logger.error(f"Failed to initialize suspend counter: {e}")
            self.last_suspend_count = None
    
    async def _suspend_counter_monitor(self):
        """Monitor /sys/power/suspend_stats/success for changes"""
        decky.logger.info("Starting suspend counter monitoring")
        
        while self.monitoring_active:
            try:
                if os.path.exists(self.suspend_stats_file):
                    with open(self.suspend_stats_file, 'r') as f:
                        current_count = int(f.read().strip())
                    
                    if self.last_suspend_count is not None and current_count > self.last_suspend_count:
                        # Suspend cycle completed - wake detected
                        decky.logger.info(f"Wake detected: suspend count {self.last_suspend_count} -> {current_count}")
                        await self._handle_wake_event("suspend_counter")
                    
                    self.last_suspend_count = current_count
                
                # Check every 5 seconds (much faster than old polling)
                await asyncio.sleep(5)
                
            except Exception as e:
                decky.logger.error(f"Suspend counter monitoring error: {e}")
                await asyncio.sleep(30)
    
    async def _journal_monitor(self):
        """Monitor systemd journal for suspend/resume events"""
        decky.logger.info("Starting journal monitoring for sleep/wake events")
        
        while self.monitoring_active:
            process = None
            try:
                # Use journalctl to monitor for suspend/resume events
                cmd = [
                    'journalctl', 
                    '--follow', 
                    '--no-pager',
                    '--output=short-iso',
                    '--since', '5 seconds ago'
                ]
                
                # Start journalctl process with suppressed stderr to prevent NVMe wake
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL  # Suppress stderr to prevent NVMe wake
                )
                
                # Read journal entries
                while self.monitoring_active and process.returncode is None:
                    try:
                        line_bytes = await asyncio.wait_for(
                            process.stdout.readline(), 
                            timeout=10.0
                        )
                        
                        if not line_bytes:
                            break
                            
                        line = line_bytes.decode('utf-8', errors='ignore').strip()
                        
                        # Check for resume indicators
                        if any(indicator in line.lower() for indicator in [
                            'resuming', 'resumed', 'wake', 'psp is resuming', 
                            'smu is resuming', 'finished preparing resuming'
                        ]):
                            decky.logger.info(f"Journal wake detection: {line}")
                            await self._handle_wake_event("journal_monitor")
                            break  # Exit to restart monitoring
                        
                    except asyncio.TimeoutError:
                        # No new journal entries - continue monitoring
                        continue
                    except Exception:
                        # Silently handle journal reading errors to prevent NVMe wake
                        break
                
            except Exception:
                # Silently handle journal monitoring errors to prevent NVMe wake
                pass
            finally:
                # Clean up process without logging to prevent NVMe wake
                if process and process.returncode is None:
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except (asyncio.TimeoutError, ProcessLookupError):
                        try:
                            process.kill()
                            await asyncio.wait_for(process.wait(), timeout=1.0)
                        except (asyncio.TimeoutError, ProcessLookupError):
                            pass  # Process cleanup handled silently
                
                # Brief pause before restarting monitoring
                if self.monitoring_active:
                    await asyncio.sleep(1)
    
    async def _handle_wake_event(self, detection_method: str):
        """Handle detected wake event with comprehensive parameter restoration"""
        try:
            decky.logger.info(f"WAKE EVENT DETECTED via {detection_method}")
            
            # Create event record
            event = SleepWakeEvent(
                timestamp=time.time(),
                event_type='wake',
                detection_method=detection_method
            )
            
            # Get current AC power state
            try:
                current_ac_power = await self.plugin.get_ac_power()
                event.ac_power_after = current_ac_power
                decky.logger.info(f"Current AC power state: {current_ac_power}")
            except Exception as e:
                decky.logger.error(f"Failed to get AC power state: {e}")
            
            # Load pre-sleep state if available
            await self._load_pre_sleep_state()
            if self.pre_sleep_state:
                event.ac_power_before = self.pre_sleep_state.get('ac_power')
                event.profile_before = self.pre_sleep_state.get('current_profile_id')
                event.gpu_mode_before = self.pre_sleep_state.get('gpu_mode')
            
            # Capture current state for comparison
            current_state = await self._capture_comprehensive_state()
            
            # Compare pre-sleep vs post-wake state
            state_differences = await self._compare_states(self.pre_sleep_state, current_state)
            
            # Only log differences if there are significant ones (to minimize NVMe wake)
            if state_differences and len(state_differences) > 3:  # Only log if substantial differences
                decky.logger.warning(f"DETECTED {len(state_differences)} STATE DIFFERENCES AFTER WAKE")
                # Log only first few differences to minimize disk activity
                for diff in state_differences[:3]:
                    decky.logger.warning(f"  {diff}")
                if len(state_differences) > 3:
                    decky.logger.warning(f"  ... and {len(state_differences) - 3} more differences")
            
            # Get current profile for restoration
            current_profile = None
            try:
                if hasattr(self.plugin, 'current_profile') and self.plugin.current_profile:
                    current_profile = self.plugin.current_profile
                    event.profile_after = current_profile.get('profileId', 'unknown')
                    decky.logger.info(f"Current profile: {event.profile_after}")
            except Exception as e:
                decky.logger.error(f"Failed to get current profile: {e}")
            
            # COMPREHENSIVE PARAMETER RESTORATION
            restoration_success = await self._restore_comprehensive_state(current_profile)
            event.settings_restored = restoration_success
            
            # Hardware reinitialization
            try:
                hardware_success = await self._reinitialize_hardware_after_wake()
                event.hardware_reinitialized = hardware_success
                
                if hardware_success:
                    decky.logger.info("Hardware reinitialization completed successfully")
                else:
                    decky.logger.warning("Hardware reinitialization failed or incomplete")
                    
            except Exception as e:
                decky.logger.error(f"Hardware reinitialization failed: {e}")
                if event.error_message:
                    event.error_message += f"; Hardware reinit failed: {e}"
                else:
                    event.error_message = f"Hardware reinit failed: {e}"
            
            # Final validation and comparison
            try:
                final_state = await self._capture_comprehensive_state()
                final_differences = await self._compare_states(self.pre_sleep_state, final_state)
                
                # Only log if there are remaining issues (minimize NVMe wake)
                if final_differences and len(final_differences) > 0:
                    decky.logger.warning(f"REMAINING DIFFERENCES AFTER RESTORATION ({len(final_differences)})")
                    # Log only critical differences to minimize disk activity
                    for diff in final_differences[:2]:
                        decky.logger.warning(f"  STILL DIFFERENT: {diff}")
                
                # Save comparison for analysis (but reduce frequency to minimize NVMe wake)
                if len(state_differences) > 0 or len(final_differences) > 0:
                    await self._save_state_comparison(self.pre_sleep_state, current_state, final_state, state_differences, final_differences)
                    
            except Exception as e:
                # Silently handle final validation errors to prevent NVMe wake
                pass
            
            # Log the event
            self._log_event(event)
            
            # Notify callbacks
            for callback in self.sleep_wake_callbacks:
                try:
                    await callback('wake_detected', event)
                except Exception as e:
                    decky.logger.error(f"Wake callback {callback.__name__} failed: {e}")
            
            decky.logger.info(f"Wake event handling completed - AC: {event.ac_power_after}, Profile: {event.profile_after}, Restoration: {restoration_success}")
            
        except Exception as e:
            decky.logger.error(f"Wake event handling failed: {e}")
    
    async def _compare_states(self, pre_state: Dict[str, Any], post_state: Dict[str, Any]) -> List[str]:
        """Compare pre-sleep and post-wake states to identify differences"""
        differences = []
        
        if not pre_state or not post_state:
            return differences
        
        # Compare all parameters
        all_keys = set(pre_state.keys()) | set(post_state.keys())
        
        for key in all_keys:
            if key in ['timestamp', 'capture_method', 'capture_error']:
                continue  # Skip metadata fields
                
            pre_value = pre_state.get(key)
            post_value = post_state.get(key)
            
            if pre_value != post_value:
                differences.append(f"{key}: {pre_value} → {post_value}")
        
        return differences
    
    async def _restore_comprehensive_state(self, current_profile: Dict[str, Any]) -> bool:
        """Restore all PowerDeck managed parameters after wake"""
        restoration_success = True
        
        try:
            # Only log start of restoration (not every parameter to minimize NVMe wake)
            decky.logger.info("Starting comprehensive parameter restoration")
            
            if not current_profile:
                return False
            
            # 1. GPU Mode Restoration (highest priority for power consumption)
            if 'gpuMode' in current_profile:
                try:
                    gpu_mode = current_profile['gpuMode']
                    success = await self.plugin.set_gpu_mode(gpu_mode)
                    if success:
                        # Only log success, not details (minimize NVMe wake)
                        decky.logger.info(f"GPU mode restored: {gpu_mode}")
                        
                        # Also apply GPU frequency limits if specified
                        if 'gpuFreqMin' in current_profile and 'gpuFreqMax' in current_profile:
                            freq_min = current_profile['gpuFreqMin']
                            freq_max = current_profile['gpuFreqMax']
                            
                            # Apply frequency limits
                            if hasattr(self.plugin, 'set_gpu_frequency_range'):
                                await self.plugin.set_gpu_frequency_range(freq_min, freq_max)
                    else:
                        restoration_success = False
                except Exception:
                    restoration_success = False
            
            # 2. TDP Restoration (critical for power consumption)
            if 'tdp' in current_profile:
                try:
                    tdp = current_profile['tdp']
                    success = await self.plugin.set_tdp(tdp)
                    if success:
                        decky.logger.info(f"TDP restored: {tdp}W")
                    else:
                        restoration_success = False
                except Exception:
                    restoration_success = False
            
            # 3. CPU Parameters Restoration
            await self._restore_cpu_parameters(current_profile)
            
            # 4. Power Management Features Restoration
            await self._restore_power_management_features(current_profile)
            
            # 5. Force profile application
            try:
                if hasattr(self.plugin, 'apply_profile'):
                    profile_success = await self.plugin.apply_profile(current_profile)
                    if profile_success:
                        decky.logger.info("Complete profile restoration successful")
                    else:
                        restoration_success = False
            except Exception:
                restoration_success = False
        
        except Exception:
            restoration_success = False
        
        return restoration_success
    
    async def _restore_cpu_parameters(self, current_profile: Dict[str, Any]):
        """Restore CPU performance parameters (minimal logging to prevent NVMe wake)"""
        try:
            # CPU Boost
            if 'cpuBoost' in current_profile:
                boost_enabled = current_profile['cpuBoost']
                if hasattr(self.plugin, 'set_cpu_boost'):
                    await self.plugin.set_cpu_boost(boost_enabled)
            
            # SMT (Simultaneous Multithreading)
            if 'smt' in current_profile:
                smt_enabled = current_profile['smt']
                if hasattr(self.plugin, 'set_smt'):
                    await self.plugin.set_smt(smt_enabled)
            
            # CPU Cores
            if 'cpuCores' in current_profile:
                cpu_cores = current_profile['cpuCores']
                if hasattr(self.plugin, 'set_cpu_cores'):
                    await self.plugin.set_cpu_cores(cpu_cores)
            
            # CPU Governor
            if 'governor' in current_profile:
                governor = current_profile['governor']
                if hasattr(self.plugin, 'set_cpu_governor'):
                    await self.plugin.set_cpu_governor(governor)
            
            # Energy Performance Preference
            if 'epp' in current_profile:
                epp = current_profile['epp']
                if hasattr(self.plugin, 'set_epp'):
                    await self.plugin.set_epp(epp)
                    
        except Exception:
            # Silently handle CPU parameter restoration errors to prevent NVMe wake
            pass
    
    async def _restore_power_management_features(self, current_profile: Dict[str, Any]):
        """Restore power management features (minimal logging to prevent NVMe wake)"""
        try:
            # USB Autosuspend
            if 'usbAutosuspend' in current_profile:
                usb_autosuspend = current_profile['usbAutosuspend']
                if hasattr(self.plugin, 'set_usb_autosuspend'):
                    await self.plugin.set_usb_autosuspend(usb_autosuspend)
            
            # PCIe ASPM
            if 'pcieAspm' in current_profile:
                pcie_aspm = current_profile['pcieAspm']
                if hasattr(self.plugin, 'set_pcie_aspm'):
                    await self.plugin.set_pcie_aspm(pcie_aspm)
                    
        except Exception:
            # Silently handle power management restoration errors to prevent NVMe wake
            pass
    
    async def _save_state_comparison(self, pre_state: Dict, current_state: Dict, final_state: Dict, 
                                  initial_differences: List[str], final_differences: List[str]):
        """Save detailed state comparison for analysis"""
        try:
            comparison_data = {
                'timestamp': time.time(),
                'pre_sleep_state': pre_state,
                'immediate_wake_state': current_state,
                'post_restoration_state': final_state,
                'initial_differences': initial_differences,
                'remaining_differences': final_differences,
                'restoration_successful': len(final_differences) == 0
            }
            
            comparison_file = "/tmp/powerdeck_state_comparison.json"
            with open(comparison_file, 'w') as f:
                json.dump(comparison_data, f, indent=2)
                
            decky.logger.info(f"State comparison saved to {comparison_file}")
            
        except Exception as e:
            decky.logger.error(f"Failed to save state comparison: {e}")
    
    async def _prepare_for_sleep(self):
        """Prepare system for sleep - save critical state"""
        try:
            decky.logger.info("Preparing for sleep - saving comprehensive state")
            
            # Capture comprehensive system state
            state = await self._capture_comprehensive_state()
            
            # Save to disk
            await self._save_pre_sleep_state(state)
            decky.logger.info(f"Pre-sleep comprehensive state saved with {len(state)} parameters")
            
        except Exception as e:
            decky.logger.error(f"Failed to prepare for sleep: {e}")
    
    async def _capture_comprehensive_state(self) -> Dict[str, Any]:
        """Capture all PowerDeck managed parameters"""
        state = {
            'timestamp': time.time(),
            'capture_method': 'comprehensive'
        }
        
        try:
            # Basic PowerDeck state
            if hasattr(self.plugin, 'get_ac_power'):
                state['ac_power'] = await self.plugin.get_ac_power()
            
            if hasattr(self.plugin, 'current_profile') and self.plugin.current_profile:
                profile = self.plugin.current_profile
                state['current_profile_id'] = profile.get('profileId')
                state['profile_data'] = dict(profile)  # Full profile snapshot
                
                # Extract specific parameters from profile
                state['profile_tdp'] = profile.get('tdp')
                state['profile_cpu_boost'] = profile.get('cpuBoost')
                state['profile_smt'] = profile.get('smt')
                state['profile_cpu_cores'] = profile.get('cpuCores')
                state['profile_governor'] = profile.get('governor')
                state['profile_epp'] = profile.get('epp')
                state['profile_gpu_mode'] = profile.get('gpuMode')
                state['profile_gpu_freq_min'] = profile.get('gpuFreqMin')
                state['profile_gpu_freq_max'] = profile.get('gpuFreqMax')
                state['profile_usb_autosuspend'] = profile.get('usbAutosuspend')
                state['profile_pcie_aspm'] = profile.get('pcieAspm')
                state['profile_fan_profile'] = profile.get('fanProfile')
            
            # Hardware TDP state via RyzenAdj
            try:
                import subprocess
                result = subprocess.run(['ryzenadj', '--info'], 
                                      capture_output=True, text=True, timeout=10,
                                      stderr=subprocess.DEVNULL)  # Suppress stderr to prevent NVMe wake
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if '|' in line and 'LIMIT' in line:
                            parts = line.split('|')
                            if len(parts) >= 3:
                                key = parts[1].strip().lower().replace(' ', '_')
                                value = parts[2].strip()
                                try:
                                    state[f'ryzenadj_{key}'] = float(value)
                                except ValueError:
                                    state[f'ryzenadj_{key}'] = value
            except Exception:
                # Silently handle RyzenAdj errors to prevent NVMe wake from logging
                pass
            
            # CPU state
            await self._capture_cpu_state(state)
            
            # GPU state  
            await self._capture_gpu_state(state)
            
            # Power management state
            await self._capture_power_management_state(state)
            
        except Exception as e:
            decky.logger.error(f"Error capturing comprehensive state: {e}")
            state['capture_error'] = str(e)
        
        return state
    
    async def _capture_cpu_state(self, state: Dict[str, Any]):
        """Capture CPU performance state"""
        try:
            # CPU Governor
            try:
                with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor', 'r') as f:
                    state['cpu_governor'] = f.read().strip()
            except Exception:
                pass
            
            # Energy Performance Preference
            try:
                with open('/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference', 'r') as f:
                    state['cpu_epp'] = f.read().strip()
            except Exception:
                pass
            
            # CPU Boost status
            try:
                with open('/sys/devices/system/cpu/cpufreq/boost', 'r') as f:
                    state['cpu_boost'] = int(f.read().strip())
            except Exception:
                pass
            
            # SMT status
            try:
                with open('/sys/devices/system/cpu/smt/control', 'r') as f:
                    state['cpu_smt'] = f.read().strip()
            except Exception:
                pass
            
            # Count online CPUs
            import glob
            online_cpus = 0
            for cpu_file in glob.glob('/sys/devices/system/cpu/cpu*/online'):
                try:
                    with open(cpu_file, 'r') as f:
                        if f.read().strip() == '1':
                            online_cpus += 1
                except Exception:
                    pass
            state['cpu_online_count'] = online_cpus
            
        except Exception as e:
            decky.logger.warning(f"Error capturing CPU state: {e}")
    
    async def _capture_gpu_state(self, state: Dict[str, Any]):
        """Capture GPU performance state"""
        try:
            # GPU Performance level
            try:
                with open('/sys/class/drm/card0/device/power_dpm_force_performance_level', 'r') as f:
                    state['gpu_performance_level'] = f.read().strip()
            except Exception:
                pass
            
            # GPU DPM state
            try:
                with open('/sys/class/drm/card0/device/power_dpm_state', 'r') as f:
                    state['gpu_dpm_state'] = f.read().strip()
            except Exception:
                pass
            
            # GPU clock frequencies
            try:
                with open('/sys/class/drm/card0/device/pp_dpm_sclk', 'r') as f:
                    sclk_lines = f.read().strip().split('\n')
                    active_freq = None
                    for line in sclk_lines:
                        if '*' in line:
                            active_freq = line.strip()
                            break
                    state['gpu_active_freq'] = active_freq
            except Exception:
                pass
            
            # GPU power profile mode
            try:
                with open('/sys/class/drm/card0/device/pp_power_profile_mode', 'r') as f:
                    profile_lines = f.read().strip().split('\n')
                    active_profile = None
                    for line in profile_lines:
                        if '*' in line:
                            active_profile = line.strip()
                            break
                    state['gpu_power_profile'] = active_profile
            except Exception:
                pass
                
        except Exception as e:
            decky.logger.warning(f"Error capturing GPU state: {e}")
    
    async def _capture_power_management_state(self, state: Dict[str, Any]):
        """Capture power management features state"""
        try:
            # USB autosuspend status - check a few devices
            import glob
            import os
            usb_autosuspend_enabled = 0
            usb_devices_checked = 0
            for usb_device in glob.glob('/sys/bus/usb/devices/usb*/power/control')[:5]:  # Check first 5
                try:
                    with open(usb_device, 'r') as f:
                        control = f.read().strip()
                        usb_devices_checked += 1
                        if control == 'auto':
                            usb_autosuspend_enabled += 1
                except Exception:
                    pass
            state['usb_autosuspend_ratio'] = f"{usb_autosuspend_enabled}/{usb_devices_checked}" if usb_devices_checked > 0 else "0/0"
            
            # PCIe ASPM status
            try:
                import subprocess
                result = subprocess.run(['lspci', '-vv'], 
                                      capture_output=True, text=True, timeout=10,
                                      stderr=subprocess.DEVNULL)  # Suppress stderr to prevent NVMe wake
                if result.returncode == 0:
                    aspm_enabled_count = result.stdout.count('ASPM.*Enabled')
                    asmp_disabled_count = result.stdout.count('ASPM.*Disabled')
                    state['pcie_aspm_enabled_count'] = aspm_enabled_count
                    state['pcie_aspm_disabled_count'] = asmp_disabled_count
            except Exception:
                # Silently handle lspci errors to prevent NVMe wake from logging
                pass
            
            # Check platform profile (for devices that support it)
            try:
                with open('/sys/firmware/acpi/platform_profile', 'r') as f:
                    state['platform_profile'] = f.read().strip()
            except Exception:
                pass
                
        except Exception as e:
            decky.logger.warning(f"Error capturing power management state: {e}")
    
    async def _save_pre_sleep_state(self, state: Dict[str, Any]):
        """Save pre-sleep state to disk"""
        try:
            with open(self.pre_sleep_state_file, 'w') as f:
                json.dump(state, f, indent=2)
            self.pre_sleep_state = state
        except Exception as e:
            decky.logger.error(f"Failed to save pre-sleep state: {e}")
    
    async def _load_pre_sleep_state(self):
        """Load pre-sleep state from disk"""
        try:
            if os.path.exists(self.pre_sleep_state_file):
                with open(self.pre_sleep_state_file, 'r') as f:
                    self.pre_sleep_state = json.load(f)
                    decky.logger.info(f"Pre-sleep state loaded: {self.pre_sleep_state}")
            else:
                self.pre_sleep_state = {}
        except Exception as e:
            decky.logger.error(f"Failed to load pre-sleep state: {e}")
            self.pre_sleep_state = {}
    
    async def _reinitialize_hardware_after_wake(self) -> bool:
        """Reinitialize hardware components after wake"""
        success = True
        
        try:
            # GPU reinitialization
            if hasattr(self.plugin, 'device_manager'):
                gpu_success = await self.plugin.device_manager.reinitialize_gpu()
                if not gpu_success:
                    decky.logger.warning("GPU reinitialization failed")
                    success = False
            
            # CPU reinitialization
            if hasattr(self.plugin, 'device_manager'):
                cpu_success = await self.plugin.device_manager.reinitialize_cpu()
                if not cpu_success:
                    decky.logger.warning("CPU reinitialization failed")
                    success = False
            
            return success
            
        except Exception as e:
            decky.logger.error(f"Hardware reinitialization failed: {e}")
            return False
    
    async def _validate_post_wake_state(self):
        """Validate system state after wake"""
        try:
            # Check GPU mode
            if hasattr(self.plugin, 'get_gpu_mode'):
                current_gpu_mode = await self.plugin.get_gpu_mode()
                decky.logger.info(f"Post-wake GPU mode: {current_gpu_mode}")
            
            # Check AC power
            if hasattr(self.plugin, 'get_ac_power'):
                current_ac_power = await self.plugin.get_ac_power()
                decky.logger.info(f"Post-wake AC power: {current_ac_power}")
            
            # Validate profile consistency
            if hasattr(self.plugin, 'current_profile') and self.plugin.current_profile:
                profile_id = self.plugin.current_profile.get('profileId', 'unknown')
                decky.logger.info(f"Post-wake profile: {profile_id}")
                
        except Exception as e:
            decky.logger.warning(f"Post-wake validation error: {e}")
    
    def _log_event(self, event: SleepWakeEvent):
        """Log sleep/wake event"""
        try:
            event_dict = asdict(event)
            decky.logger.info(f"Sleep/Wake Event: {json.dumps(event_dict, indent=2)}")
            
            # Save to events log file
            events_file = "/tmp/powerdeck_sleep_wake_events.json"
            events = []
            
            if os.path.exists(events_file):
                try:
                    with open(events_file, 'r') as f:
                        events = json.load(f)
                except:
                    events = []
            
            events.append(event_dict)
            
            # Keep only last 50 events
            events = events[-50:]
            
            with open(events_file, 'w') as f:
                json.dump(events, f, indent=2)
                
        except Exception as e:
            decky.logger.error(f"Failed to log event: {e}")
    
    def add_callback(self, callback: Callable):
        """Add sleep/wake event callback"""
        self.sleep_wake_callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """Remove sleep/wake event callback"""
        if callback in self.sleep_wake_callbacks:
            self.sleep_wake_callbacks.remove(callback)
    
    async def manual_capture_pre_sleep_state(self):
        """Manually capture pre-sleep state for testing"""
        decky.logger.info("Manual pre-sleep state capture triggered")
        await self._prepare_for_sleep()
        return self.pre_sleep_state
    
    async def manual_test_wake_restoration(self):
        """Manually test wake restoration for debugging"""
        decky.logger.info("Manual wake restoration test triggered")
        await self._handle_wake_event("manual_test")
        return True


# Global manager instance
sleep_wake_manager = None


def get_sleep_wake_manager(plugin_instance=None):
    """Get or create sleep/wake manager instance"""
    global sleep_wake_manager
    
    if sleep_wake_manager is None and plugin_instance is not None:
        sleep_wake_manager = EnhancedSleepWakeManager(plugin_instance)
    
    return sleep_wake_manager


# Cleanup function
async def cleanup_sleep_wake_manager():
    """Clean up sleep/wake manager"""
    global sleep_wake_manager
    
    if sleep_wake_manager is not None:
        await sleep_wake_manager.stop_monitoring()
        sleep_wake_manager = None
