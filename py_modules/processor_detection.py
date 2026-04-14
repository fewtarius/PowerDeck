#!/usr/bin/env python3
"""
PowerDeck Processor Detection Module

Detects the current processor and provides specifications from the unified
processor database. Uses module-level caching to avoid repeated /proc/cpuinfo reads.
"""

import re
import subprocess
from typing import Dict, Optional, Tuple

# Import handling for both module and standalone usage
try:
    from .unified_processor_db import get_processor_info, get_processor_tdp_info
except ImportError:
    from unified_processor_db import get_processor_info, get_processor_tdp_info

# Module-level cache for processor detection results
_cached_model_name = None
_cached_processor_info = None


def get_processor_model() -> str:
    """Get the processor model from the system (cached)"""
    global _cached_model_name
    if _cached_model_name is not None:
        return _cached_model_name

    model = ""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('model name'):
                    model = line.split(':', 1)[1].strip()
                    break
    except (FileNotFoundError, PermissionError):
        pass

    if not model:
        try:
            result = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if line.startswith('Model name:'):
                    model = line.split(':', 1)[1].strip()
                    break
        except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass

    _cached_model_name = model or "Unknown Processor"
    return _cached_model_name


def detect_processor() -> Dict[str, any]:
    """
    Detect current processor and return comprehensive information (cached).

    Returns:
        Dictionary with processor specifications from unified database
    """
    global _cached_processor_info
    if _cached_processor_info is not None:
        return _cached_processor_info

    model_name = get_processor_model()
    processor_info = get_processor_info(model_name)

    if processor_info:
        result = {
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
        result = {
            'model': model_name,
            'vendor': 'Unknown',
            'family': 'Unknown',
            'series': 'Unknown',
            'cores': 0,
            'threads': 0,
            'base_freq_ghz': 0.0,
            'max_freq_ghz': 0.0,
            'default_tdp': 15,
            'tdp_min': 10,
            'tdp_max': 25,
            'l3_cache_mb': 0,
            'gpu_model': 'Unknown',
            'node_process': 'Unknown',
            'launch_year': 2020,
            'detected_model': model_name,
            'database_source': 'fallback'
        }

    _cached_processor_info = result
    return result


def get_tdp_limits() -> Tuple[int, int, int]:
    """
    Get TDP limits for the current processor.

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
    return detect_processor()['vendor'].lower() == 'amd'


def is_intel_processor() -> bool:
    """Check if current processor is Intel"""
    return detect_processor()['vendor'].lower() == 'intel'


def get_safe_tdp_limits() -> Tuple[int, int]:
    """
    Get safe TDP limits based on processor specifications.

    Returns:
        (min_safe_tdp, max_safe_tdp) tuple
    """
    _, _, max_tdp = get_tdp_limits()
    return (4, max_tdp)  # Hard-coded 4W minimum for underclocking


# Compatibility functions used by main.py

def get_current_processor_info() -> Dict[str, any]:
    """Get current processor information and capabilities"""
    processor = detect_processor()
    return {
        "detected": processor['database_source'] != 'fallback',
        "model": processor['model'],
        "vendor": processor['vendor'],
        "family": processor['family'],
        "cores": processor['cores'],
        "threads": processor['threads'],
        "default_tdp": processor['default_tdp'],
        "tdp_min": processor['tdp_min'],
        "tdp_max": processor['tdp_max'],
        "base_freq_ghz": processor['base_freq_ghz'],
        "max_freq_ghz": processor['max_freq_ghz'],
        "gpu_model": processor['gpu_model'],
        "database_source": processor['database_source']
    }


def get_processor_tdp_limits() -> Tuple[int, int]:
    """Get TDP limits (4W min, database max)"""
    _, _, max_tdp = get_tdp_limits()
    return (4, max_tdp)


def get_processor_default_tdp() -> int:
    """Get default TDP for the current processor"""
    default_tdp, _, _ = get_tdp_limits()
    return default_tdp


def is_handheld_device() -> bool:
    """Check if running on a handheld gaming device"""
    processor = detect_processor()
    handheld_indicators = [
        'z1', 'z2', 'custom apu', 'van gogh',
        '5560u', '7840u', '7640u'
    ]
    model_lower = processor['model'].lower()
    return any(indicator in model_lower for indicator in handheld_indicators)


def refresh_processor_detection():
    """Clear cached processor detection data and force re-detection"""
    global _cached_model_name, _cached_processor_info
    _cached_model_name = None
    _cached_processor_info = None


if __name__ == "__main__":
    print("PowerDeck Processor Detection Test")
    print("=" * 40)

    processor = detect_processor()
    print(f"Detected Processor: {processor['model']}")
    print(f"Vendor: {processor['vendor']}")
    print(f"Default TDP: {processor['default_tdp']}W")
    print(f"TDP Range: {processor['tdp_min']}W - {processor['tdp_max']}W")
    print(f"Cores/Threads: {processor['cores']}/{processor['threads']}")
    print(f"Database Source: {processor['database_source']}")

    default, min_tdp, max_tdp = get_tdp_limits()
    print(f"\nTDP Limits:")
    print(f"  Default: {default}W")
    print(f"  Range: {min_tdp}W - {max_tdp}W")

    safe_min, safe_max = get_safe_tdp_limits()
    print(f"  Safe Range: {safe_min}W - {safe_max}W")

    current_info = get_current_processor_info()
    print(f"\nCompatibility Info:")
    print(f"  Detected: {current_info['detected']}")
    print(f"  Default TDP: {current_info['default_tdp']}W")
