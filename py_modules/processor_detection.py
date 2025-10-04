#!/usr/bin/env python3
"""
PowerDeck Processor Detection Module

This module detects the current processor and provides comprehensive
specifications from the unified processor database.

Updated to use unified processor database with 1,278+ processors
and correct TDP values (Default TDP, not cTDP minimums).
"""

import re
import subprocess
from typing import Dict, Optional, Tuple

# Import handling for both module and standalone usage
try:
    from .unified_processor_db import get_processor_info, get_processor_tdp_info
except ImportError:
    from unified_processor_db import get_processor_info, get_processor_tdp_info

def get_processor_model() -> str:
    """Get the processor model from the system"""
    try:
        # Try to read from /proc/cpuinfo
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
        
        # Fallback: try lscpu
        result = subprocess.run(['lscpu'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if line.startswith('Model name:'):
                return line.split(':', 1)[1].strip()
                
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    
    return "Unknown Processor"

def detect_processor() -> Dict[str, any]:
    """
    Detect current processor and return comprehensive information
    
    Returns:
        Dictionary with processor specifications from unified database
    """
    model_name = get_processor_model()
    processor_info = get_processor_info(model_name)
    
    if processor_info:
        return {
            'model': processor_info['name'],
            'vendor': processor_info['vendor'],
            'family': processor_info['family'],
            'series': processor_info['series'],
            'cores': processor_info['cores'],
            'threads': processor_info['threads'],
            'base_freq_ghz': processor_info['base_freq_ghz'],
            'max_freq_ghz': processor_info['max_freq_ghz'],
            'default_tdp': processor_info['default_tdp'],
            'tdp_min': processor_info['tdp_min'],
            'tdp_max': processor_info['tdp_max'],
            'l3_cache_mb': processor_info['l3_cache_mb'],
            'gpu_model': processor_info['gpu_model'],
            'node_process': processor_info['node_process'],
            'launch_year': processor_info['launch_year'],
            'detected_model': processor_info.get('detected_model', model_name),
            'database_source': 'unified_db'
        }
    else:
        # Fallback for unknown processors
        return {
            'model': model_name,
            'vendor': 'Unknown',
            'family': 'Unknown',
            'series': 'Unknown',
            'cores': 0,
            'threads': 0,
            'base_freq_ghz': 0.0,
            'max_freq_ghz': 0.0,
            'default_tdp': 15,  # Safe fallback
            'tdp_min': 10,
            'tdp_max': 25,
            'l3_cache_mb': 0,
            'gpu_model': 'Unknown',
            'node_process': 'Unknown',
            'launch_year': 2020,
            'detected_model': model_name,
            'database_source': 'fallback'
        }

def get_tdp_limits() -> Tuple[int, int, int]:
    """
    Get TDP limits for the current processor
    
    Returns:
        (default_tdp, min_tdp, max_tdp) tuple
    """
    tdp_info = get_processor_tdp_info()
    return (
        tdp_info['default_tdp'],
        tdp_info['tdp_min'], 
        tdp_info['tdp_max']
    )

def is_amd_processor() -> bool:
    """Check if current processor is AMD"""
    processor = detect_processor()
    return processor['vendor'].lower() == 'amd'

def is_intel_processor() -> bool:
    """Check if current processor is Intel"""
    processor = detect_processor()
    return processor['vendor'].lower() == 'intel'

def get_safe_tdp_limits() -> Tuple[int, int]:
    """
    Get safe TDP limits based on processor specifications
    
    Returns:
        (min_safe_tdp, max_safe_tdp) tuple
    """
    default_tdp, min_tdp, max_tdp = get_tdp_limits()
    
    # Use database values directly - they already incorporate safety margins
    return (4, max_tdp)  # Hard-coded 4W minimum for underclocking

# Compatibility functions for main.py
def get_current_processor_info() -> Dict[str, any]:
    """Get current processor information and capabilities (CORRECTED)"""
    processor = detect_processor()
    
    return {
        "detected": processor['database_source'] != 'fallback',
        "model": processor['model'],
        "vendor": processor['vendor'],
        "family": processor['family'],
        "cores": processor['cores'],
        "threads": processor['threads'],
        "default_tdp": processor['default_tdp'],  # CORRECTED: Now from unified DB
        "tdp_min": processor['tdp_min'],
        "tdp_max": processor['tdp_max'],
        "base_freq_ghz": processor['base_freq_ghz'],
        "max_freq_ghz": processor['max_freq_ghz'],
        "gpu_model": processor['gpu_model'],
        "database_source": processor['database_source']
    }

def get_processor_tdp_limits() -> Tuple[int, int]:
    """Get TDP limits for the current processor (CORRECTED)"""
    default_tdp, min_tdp, max_tdp = get_tdp_limits()
    return (4, max_tdp)  # Hard-coded 4W minimum for underclocking

def get_processor_default_tdp() -> int:
    """Get default TDP for the current processor (CORRECTED)"""
    default_tdp, _, _ = get_tdp_limits()
    return default_tdp

def is_handheld_device() -> bool:
    """Check if running on a handheld gaming device"""
    processor = detect_processor()
    # Check for handheld-specific processors
    handheld_indicators = [
        'z1', 'z2', 'custom apu', 'van gogh',
        '5560u', '7840u', '7640u'
    ]
    model_lower = processor['model'].lower()
    return any(indicator in model_lower for indicator in handheld_indicators)

def refresh_processor_detection():
    """Refresh processor detection (clears unified DB cache)"""
    # The unified DB loads fresh each time, no cache to clear
    pass

# Legacy compatibility functions
def get_amd_safe_limits() -> Tuple[int, int]:
    """Legacy compatibility - get safe AMD TDP limits"""
    if is_amd_processor():
        return get_safe_tdp_limits()
    else:
        return (10, 25)  # Fallback

def get_intel_safe_limits() -> Tuple[int, int]:
    """Legacy compatibility - get safe Intel TDP limits"""
    if is_intel_processor():
        return get_safe_tdp_limits()
    else:
        return (15, 45)  # Fallback

if __name__ == "__main__":
    # Test the processor detection
    print("PowerDeck Processor Detection Test")
    print("=" * 40)
    
    processor = detect_processor()
    print(f"Detected Processor: {processor['model']}")
    print(f"Vendor: {processor['vendor']}")
    print(f"Default TDP: {processor['default_tdp']}W")
    print(f"TDP Range: {processor['tdp_min']}W - {processor['tdp_max']}W")
    print(f"Cores/Threads: {processor['cores']}/{processor['threads']}")
    print(f"Database Source: {processor['database_source']}")
    
    # Test TDP limits
    default, min_tdp, max_tdp = get_tdp_limits()
    print(f"\nTDP Limits:")
    print(f"  Default: {default}W")
    print(f"  Range: {min_tdp}W - {max_tdp}W")
    
    safe_min, safe_max = get_safe_tdp_limits()
    print(f"  Safe Range: {safe_min}W - {safe_max}W")
    
    # Test compatibility functions
    current_info = get_current_processor_info()
    print(f"\nCompatibility Info:")
    print(f"  Detected: {current_info['detected']}")
    print(f"  Default TDP: {current_info['default_tdp']}W")
    
    default_tdp = get_processor_default_tdp()
    print(f"  Default TDP Function: {default_tdp}W")

def get_tdp_limits() -> Tuple[int, int, int]:
    """
    Get TDP limits for the current processor
    
    Returns:
        (default_tdp, min_tdp, max_tdp) tuple
    """
    tdp_info = get_processor_tdp_info()
    return (
        tdp_info['default_tdp'],
        tdp_info['tdp_min'], 
        tdp_info['tdp_max']
    )

def is_amd_processor() -> bool:
    """Check if current processor is AMD"""
    processor = detect_processor()
    return processor['vendor'].lower() == 'amd'

def is_intel_processor() -> bool:
    """Check if current processor is Intel"""
    processor = detect_processor()
    return processor['vendor'].lower() == 'intel'

def get_safe_tdp_limits() -> Tuple[int, int]:
    """
    Get safe TDP limits based on processor specifications
    
    Returns:
        (min_safe_tdp, max_safe_tdp) tuple
    """
    default_tdp, min_tdp, max_tdp = get_tdp_limits()
    
    # Use database values directly - they already incorporate safety margins
    return (4, max_tdp)  # Hard-coded 4W minimum for underclocking

# Legacy compatibility functions
def get_amd_safe_limits() -> Tuple[int, int]:
    """Legacy compatibility - get safe AMD TDP limits"""
    if is_amd_processor():
        return get_safe_tdp_limits()
    else:
        return (10, 25)  # Fallback

def get_intel_safe_limits() -> Tuple[int, int]:
    """Legacy compatibility - get safe Intel TDP limits"""
    if is_intel_processor():
        return get_safe_tdp_limits()
    else:
        return (15, 45)  # Fallback

if __name__ == "__main__":
    # Test the processor detection
    print("PowerDeck Processor Detection Test")
    print("=" * 40)
    
    processor = detect_processor()
    print(f"Detected Processor: {processor['model']}")
    print(f"Vendor: {processor['vendor']}")
    print(f"Default TDP: {processor['default_tdp']}W")
    print(f"TDP Range: {processor['tdp_min']}W - {processor['tdp_max']}W")
    print(f"Cores/Threads: {processor['cores']}/{processor['threads']}")
    print(f"Database Source: {processor['database_source']}")
    
    # Test TDP limits
    default, min_tdp, max_tdp = get_tdp_limits()
    print(f"\nTDP Limits:")
    print(f"  Default: {default}W")
    print(f"  Range: {min_tdp}W - {max_tdp}W")
    
    safe_min, safe_max = get_safe_tdp_limits()
    print(f"  Safe Range: {safe_min}W - {safe_max}W")

import os
import re
import subprocess
from typing import Optional, Dict, Any
try:
    # Use unified processor database instead of separate AMD/Intel databases
    from .unified_processor_db import get_processor_info, get_processor_tdp_info
except ImportError:
    # Fallback for standalone execution
    from unified_processor_db import get_processor_info, get_processor_tdp_info


class ProcessorDetector:
    """Detects and manages processor information for PowerDeck"""
    
    def __init__(self):
        self._cached_processor = None
        self._cached_cpu_info = None
    
    def get_cpu_info(self) -> str:
        """Get CPU information from various sources"""
        if self._cached_cpu_info:
            return self._cached_cpu_info
        
        cpu_info = ""
        
        # Try /proc/cpuinfo first (Linux)
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo_content = f.read()
                
            # Extract model name
            model_match = re.search(r'model name\s*:\s*(.+)', cpuinfo_content)
            if model_match:
                cpu_info = model_match.group(1).strip()
        except (FileNotFoundError, PermissionError):
            pass
        
        # Fallback to lscpu command
        if not cpu_info:
            try:
                result = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    model_match = re.search(r'Model name:\s*(.+)', result.stdout)
                    if model_match:
                        cpu_info = model_match.group(1).strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                pass
        
        # Fallback to DMI information
        if not cpu_info:
            try:
                with open('/sys/devices/virtual/dmi/id/processor_version', 'r') as f:
                    cpu_info = f.read().strip()
            except (FileNotFoundError, PermissionError):
                pass
        
        # Final fallback - check for known device patterns
        if not cpu_info:
            cpu_info = self._detect_device_specific_cpu()
        
        self._cached_cpu_info = cpu_info
        return cpu_info
    
    def _detect_device_specific_cpu(self) -> str:
        """Detect CPU from device-specific indicators"""
        # Steam Deck detection
        try:
            with open('/sys/devices/virtual/dmi/id/product_name', 'r') as f:
                product_name = f.read().strip().lower()
                if 'jupiter' in product_name or 'steamdeck' in product_name:
                    return "AMD Custom APU 0405"
        except (FileNotFoundError, PermissionError):
            pass
        
        # ROG Ally detection
        try:
            with open('/sys/devices/virtual/dmi/id/product_name', 'r') as f:
                product_name = f.read().strip().lower()
                if 'ally' in product_name or 'rc71l' in product_name:
                    return "AMD Ryzen Z1 Extreme"  # Most common ROG Ally config
        except (FileNotFoundError, PermissionError):
            pass
        
        # Check for other handheld indicators
        try:
            # Check kernel command line for handheld indicators
            with open('/proc/cmdline', 'r') as f:
                cmdline = f.read().lower()
                if any(indicator in cmdline for indicator in ['steamdeck', 'ally', 'onexplayer', 'gpd']):
                    return "AMD Ryzen Z1 Extreme"  # Common handheld fallback
        except (FileNotFoundError, PermissionError):
            pass
        
        return "Unknown AMD Processor"
    
    def detect_current_processor(self) -> Optional[Dict[str, Any]]:
        """Detect the current processor and return its specifications"""
        if self._cached_processor:
            return self._cached_processor
        
        cpu_info = self.get_cpu_info()
        if not cpu_info:
            return None
        
        # Use unified processor detection for both Intel and AMD
        processor = get_processor_info(cpu_info)
        
        # If not found, try fallback logic
        if not processor:
            processor = self._fallback_processor_detection(cpu_info)
        
        self._cached_processor = processor
        return processor
    
    def _fallback_processor_detection(self, cpu_info: str) -> Optional[Dict[str, Any]]:
        """Fallback processor detection for unknown CPUs using unified database"""
        cpu_lower = cpu_info.lower()
        
        # Generic AMD detection with reasonable defaults
        if 'amd' in cpu_lower:
            # Try to extract model information
            if any(z_series in cpu_lower for z_series in ['z1', 'z2']):
                # It's likely a handheld Z-series, use Z1 Extreme as fallback
                return get_processor_info("AMD Ryzen Z1 Extreme")
            
            elif any(phoenix in cpu_lower for phoenix in ['7840', '7640', '7540']):
                # Phoenix series mobile
                if '7840' in cpu_lower:
                    return get_processor_info("AMD Ryzen 7 7840U")
                elif '7640' in cpu_lower:
                    return get_processor_info("AMD Ryzen 5 7640U")
            
            elif 'van gogh' in cpu_lower or 'custom apu' in cpu_lower:
                # Steam Deck
                return get_processor_info("AMD Custom APU 0405")
        
        return None
    
    def _detect_intel_processor(self, cpu_info: str) -> Optional[Dict[str, Any]]:
        """Detect Intel processor using unified database"""
        # Use unified processor detection
        processor = get_processor_info(cpu_info)
        
        # Filter to Intel processors only for this method
        if processor and processor.get('vendor') == 'Intel':
            return processor
        
        return None
    def get_processor_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive processor capabilities for PowerDeck"""
        processor = self.detect_current_processor()
        
        if not processor:
            # Return safe defaults for unknown processors
            return {
                "processor_name": "Unknown Processor",
                "cpu_info": self.get_cpu_info(),
                "detected": False,
                "safe_tdp_min": 4,
                "safe_tdp_max": 15,
                "max_cpu_cores": 8,
                "max_cpu_threads": 16,
                "cpu_base_mhz": 2000,
                "cpu_boost_mhz": 3500,
                "gpu_model": "Unknown GPU",
                "gpu_cu_count": 8,
                "gpu_base_mhz": 1000,
                "gpu_max_mhz": 1600,
                "memory_type": "Unknown",
                "form_factor": "Unknown",
                "is_handheld": self._is_handheld_device(),
                "recommended_profiles": []
            }
        
        # Create basic recommendations based on processor specs from unified database
        recommendations = {}
        if processor:
            # Create basic recommendations based on processor type and specs
            vendor = processor.get('vendor', 'Unknown')
            default_tdp = processor.get('default_tdp', 15)
            tdp_min = processor.get('tdp_min', 10)
            tdp_max = processor.get('tdp_max', 25)
            
            recommendations = {
                "recommended_tdp": default_tdp,
                "tdp_range": {"min": tdp_min, "max": tdp_max},
                "recommended_governor": "schedutil" if vendor == "Intel" else "powersave",
                "supports_boost": True,
                "vendor": vendor
            }
        else:
            recommendations = {}
        
        capabilities = {
            "processor_name": processor.get('name', 'Unknown') if processor else 'Unknown',
            "cpu_info": self.get_cpu_info(),
            "detected": processor is not None,
            "family": processor.get('vendor', 'Unknown') if processor else 'Unknown',
            "series": processor.get('series', 'Unknown') if processor else 'Unknown',
            "form_factor": processor.get('form_factor', 'Unknown') if processor else 'Unknown',
            "node_process": processor.get('process_node', 'Unknown') if processor else 'Unknown',
            "socket": processor.get('socket', 'Unknown') if processor else 'Unknown',
            "max_temp": processor.get('max_temp', 85) if processor else 85,
            "product_ids": processor.get('product_ids', []) if processor else [],
            "features": processor.get('features', []) if processor else [],
            "is_handheld": self.is_handheld_processor(),
            **recommendations
        }
        
        return capabilities
    
    def is_handheld_processor(self) -> bool:
        """Check if the current device is a handheld gaming device"""
        # First check processor-specific indicators
        processor = self.detect_current_processor()
        if processor:
            form_factor = processor.get('form_factor', '').lower()
            series = processor.get('series', '')
            name = processor.get('name', '')
            
            if ("handheld" in form_factor or 
                any(z_series in series for z_series in ["z1", "z2"]) or
                "custom apu" in name.lower()):
                return True
        
        # Check for actual handheld device characteristics
        return self._is_handheld_device()
    
    def _is_handheld_device(self) -> bool:
        """Check if this is a handheld device based on hardware characteristics"""
        try:
            # Check for battery (indicates portable device)
            has_battery = self._has_battery()
            
            # Check for built-in game controllers
            has_gamepad = self._has_builtin_gamepad()
            
            # Check for known handheld device patterns
            is_known_handheld = self._is_known_handheld_device()
            
            # Device is handheld if it has battery AND (gamepad OR is known handheld)
            return has_battery and (has_gamepad or is_known_handheld)
            
        except Exception:
            return False
    
    def _has_battery(self) -> bool:
        """Check if the device has a battery"""
        try:
            import os
            import glob
            
            # Check for battery in /sys/class/power_supply/
            battery_paths = glob.glob("/sys/class/power_supply/BAT*")
            if battery_paths:
                return True
            
            # Check for ACPI battery
            if os.path.exists("/proc/acpi/battery"):
                battery_dirs = os.listdir("/proc/acpi/battery")
                if battery_dirs:
                    return True
            
            return False
        except Exception:
            return False
    
    def _has_builtin_gamepad(self) -> bool:
        """Check if the device has built-in game controllers"""
        try:
            import os
            import glob
            
            # Check for input devices that might be built-in gamepads
            input_devices = glob.glob("/sys/class/input/js*")
            if input_devices:
                return True
            
            # Check for event devices that might be gamepads
            event_devices = glob.glob("/dev/input/event*")
            for device in event_devices:
                try:
                    # Try to read device name to check for gamepad indicators
                    with open(f"/sys/class/input/input{device.split('event')[-1]}/name", 'r') as f:
                        device_name = f.read().strip().lower()
                        if any(keyword in device_name for keyword in ['gamepad', 'controller', 'joystick', 'xbox', 'playstation']):
                            return True
                except Exception:
                    continue
            
            return False
        except Exception:
            return False
    
    def _is_known_handheld_device(self) -> bool:
        """Check if this is a known handheld gaming device"""
        try:
            import subprocess
            
            # Check DMI information for known handheld manufacturers
            handheld_patterns = [
                'ayaneo', 'aya neo', 'steam deck', 'valve',
                'rog ally', 'ally', 'onexplayer', 'gpd win',
                'gpd pocket', 'ayn odin', 'retroid'
            ]
            
            try:
                # Check system manufacturer and product name
                result = subprocess.run(['dmidecode', '-s', 'system-manufacturer'], 
                                      capture_output=True, text=True, timeout=5)
                manufacturer = result.stdout.strip().lower()
                
                result = subprocess.run(['dmidecode', '-s', 'system-product-name'], 
                                      capture_output=True, text=True, timeout=5)
                product = result.stdout.strip().lower()
                
                system_info = f"{manufacturer} {product}"
                
                for pattern in handheld_patterns:
                    if pattern in system_info:
                        return True
                        
            except Exception:
                pass
            
            # Check device tree or other platform-specific identifiers
            try:
                if os.path.exists("/proc/device-tree/model"):
                    with open("/proc/device-tree/model", 'r') as f:
                        model = f.read().strip().lower()
                        for pattern in handheld_patterns:
                            if pattern in model:
                                return True
            except Exception:
                pass
            
            return False
        except Exception:
            return False
    
    def get_optimal_tdp_range(self) -> tuple[int, int]:
        """Get TDP range for the current processor
        Returns: (hard_coded_min, database_max)
        - Minimum: Always 4W (hard-coded for underclocking)
        - Maximum: From processor database ctdp_max
        """
        processor = self.detect_current_processor()
        
        if not processor:
            return 4, 25  # Fallback: 4W min (hard-coded), 25W max (fallback)
        
        # Hard-coded minimum for underclocking capability
        hard_coded_min = 4
        
        # Maximum from processor database
        database_max = processor.ctdp_max or processor.default_tdp or 25
        
        return hard_coded_min, database_max
    
    def get_default_tdp(self) -> int:
        """Get default TDP for the current processor from database default_tdp
        This is the actual processor default TDP value (15W for 5560U)
        """
        processor = self.detect_current_processor()
        
        if not processor:
            return 15  # Fallback default
        
        # FIXED: Use processor default_tdp (15W), not ctdp_min (10W)
        return processor.default_tdp or processor.ctdp_min or 15
    
    def clear_cache(self):
        """Clear cached processor information"""
        self._cached_processor = None
        self._cached_cpu_info = None


# Compatibility functions for main.py
def get_current_processor_info() -> Dict[str, Any]:
    """Get current processor information and capabilities (CORRECTED)"""
    processor = detect_processor()
    
    return {
        "detected": processor['database_source'] != 'fallback',
        "model": processor['model'],
        "vendor": processor['vendor'],
        "family": processor['family'],
        "cores": processor['cores'],
        "threads": processor['threads'],
        "default_tdp": processor['default_tdp'],  # CORRECTED: Now from unified DB
        "tdp_min": processor['tdp_min'],
        "tdp_max": processor['tdp_max'],
        "base_freq_ghz": processor['base_freq_ghz'],
        "max_freq_ghz": processor['max_freq_ghz'],
        "gpu_model": processor['gpu_model'],
        "database_source": processor['database_source']
    }

def get_processor_tdp_limits() -> Tuple[int, int]:
    """Get TDP limits for the current processor (CORRECTED)"""
    default_tdp, min_tdp, max_tdp = get_tdp_limits()
    return (4, max_tdp)  # Hard-coded 4W minimum for underclocking

def get_processor_default_tdp() -> int:
    """Get default TDP for the current processor (CORRECTED)"""
    default_tdp, _, _ = get_tdp_limits()
    return default_tdp

def is_handheld_device() -> bool:
    """Check if running on a handheld gaming device"""
    processor = detect_processor()
    # Check for handheld-specific processors
    handheld_indicators = [
        'z1', 'z2', 'custom apu', 'van gogh',
        '5560u', '7840u', '7640u'
    ]
    model_lower = processor['model'].lower()
    return any(indicator in model_lower for indicator in handheld_indicators)

def refresh_processor_detection():
    """Refresh processor detection (clears unified DB cache)"""
    # The unified DB loads fresh each time, no cache to clear
    pass
