#!/usr/bin/env python3
"""
PowerDeck Unified Processor Database

This module provides unified processor detection and specifications using
the complete database built from AMD and Intel CSV files.

Features:
- 1,278+ processors from AMD and Intel
- Correct TDP values (Default TDP, not cTDP minimums)
- Unified detection patterns for processor identification
- Comprehensive processor specifications

Usage:
    processor_info = get_processor_info()
    if processor_info:
        default_tdp = processor_info['default_tdp']
        tdp_range = (processor_info['tdp_min'], processor_info['tdp_max'])
"""

import json
import re
import os
from typing import Optional, Dict, Any, List
from pathlib import Path

# Global database variables (loaded once)
_PROCESSOR_DATABASE: Optional[List[Dict]] = None
_DETECTION_PATTERNS: Optional[Dict[str, List[Dict]]] = None

def load_processor_database() -> bool:
    """Load the unified processor database"""
    global _PROCESSOR_DATABASE, _DETECTION_PATTERNS
    
    if _PROCESSOR_DATABASE is not None:
        return True
    
    try:
        # Get path to database files
        current_dir = Path(__file__).parent
        db_file = current_dir / "unified_processor_database.json"
        patterns_file = current_dir / "processor_detection_patterns.json"
        
        # Load processor database
        if db_file.exists():
            with open(db_file, 'r') as f:
                _PROCESSOR_DATABASE = json.load(f)
        else:
            print(f"Warning: Processor database not found at {db_file}")
            return False
        
        # Load detection patterns
        if patterns_file.exists():
            with open(patterns_file, 'r') as f:
                _DETECTION_PATTERNS = json.load(f)
        else:
            print(f"Warning: Detection patterns not found at {patterns_file}")
            return False
        
        print(f"Loaded {len(_PROCESSOR_DATABASE)} processors with {len(_DETECTION_PATTERNS)} detection patterns")
        return True
        
    except Exception as e:
        print(f"Error loading processor database: {e}")
        return False

def get_cpu_info() -> Dict[str, str]:
    """Get CPU information from /proc/cpuinfo"""
    cpu_info = {}
    
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == 'model name':
                        cpu_info['model_name'] = value
                    elif key == 'vendor_id':
                        cpu_info['vendor_id'] = value
                    elif key == 'cpu family':
                        cpu_info['cpu_family'] = value
                    elif key == 'model':
                        cpu_info['model'] = value
                    elif key == 'stepping':
                        cpu_info['stepping'] = value
                    elif key == 'cpu cores':
                        cpu_info['cpu_cores'] = value
                    elif key == 'siblings':
                        cpu_info['siblings'] = value
                        
                # Only need first processor info
                if line.strip() == '' and cpu_info:
                    break
                    
    except FileNotFoundError:
        # Fallback for non-Linux systems
        cpu_info['model_name'] = 'Unknown CPU'
        cpu_info['vendor_id'] = 'Unknown'
    
    return cpu_info

def find_processor_by_pattern(model_name: str) -> Optional[Dict[str, Any]]:
    """Find processor using detection patterns"""
    if not load_processor_database() or not _DETECTION_PATTERNS:
        return None
    
    model_lower = model_name.lower()
    
    # Special case for Steam Deck's unique naming
    if "custom apu 0932" in model_lower or "amd custom apu 0932" in model_lower:
        if "custom_apu_0932" in _DETECTION_PATTERNS:
            processors = _DETECTION_PATTERNS["custom_apu_0932"]
            for proc in processors:
                if "steam deck" in proc['name'].lower() or "custom apu 0932" in proc['name'].lower():
                    return proc
    
    if "custom apu 0405" in model_lower or "amd custom apu 0405" in model_lower:
        if "custom_apu_0405" in _DETECTION_PATTERNS:
            processors = _DETECTION_PATTERNS["custom_apu_0405"]
            for proc in processors:
                if "steam deck" in proc['name'].lower() or "custom apu 0405" in proc['name'].lower():
                    return proc
    
    # Extract specific model patterns first (more specific patterns)
    
    # AMD specific patterns - extract the exact model number
    amd_model_matches = re.findall(r'(\d{4}[a-z]+)', model_lower)
    for model in amd_model_matches:
        if model in _DETECTION_PATTERNS:
            processors = _DETECTION_PATTERNS[model]
            # Find exact match in the processor list, prefer processors with valid default TDP
            # Also prefer non-PRO versions for consumer devices unless explicitly PRO
            best_match = None
            preferred_match = None
            
            for proc in processors:
                if model in proc['name'].lower():
                    is_pro = 'pro' in proc['name'].lower()
                    has_valid_tdp = proc.get('default_tdp', 0) > 0
                    
                    # If this is a valid processor
                    if has_valid_tdp:
                        # Check if model string explicitly mentions PRO
                        model_wants_pro = 'pro' in model_lower
                        
                        if model_wants_pro and is_pro:
                            # Explicitly looking for PRO and this is PRO
                            return proc
                        elif not model_wants_pro and not is_pro:
                            # Looking for regular version and this is regular
                            return proc
                        elif not preferred_match:
                            # Keep as preferred match
                            preferred_match = proc
                    
                    # Keep as fallback if no better match found
                    elif best_match is None:
                        best_match = proc
            
            # Return preferred match or fallback
            if preferred_match:
                return preferred_match
            elif best_match:
                return best_match
    
    # Intel specific patterns - extract the exact model number  
    intel_model_matches = re.findall(r'(i[3579]-\d+[a-z]*)', model_lower)
    for model in intel_model_matches:
        if model in _DETECTION_PATTERNS:
            processors = _DETECTION_PATTERNS[model]
            # Find exact match, prefer processors with valid default TDP
            best_match = None
            for proc in processors:
                if model in proc['name'].lower():
                    # Prefer processors with non-zero default TDP
                    if proc.get('default_tdp', 0) > 0:
                        return proc
                    # Keep as fallback if no better match found
                    if best_match is None:
                        best_match = proc
            # Return best match if found (even with 0 TDP as fallback)
            if best_match:
                return best_match
    
    # Generic number patterns (less specific)
    number_matches = re.findall(r'(\d{3,4}[a-z]*)', model_lower)
    for number in number_matches:
        if number in _DETECTION_PATTERNS:
            processors = _DETECTION_PATTERNS[number]
            # Prefer exact name matches within the pattern group, and prefer non-zero TDP
            best_match = None
            for proc in processors:
                if number in proc['name'].lower():
                    # Check if other parts of the model name also match
                    name_parts = model_lower.split()
                    proc_name_lower = proc['name'].lower()
                    matches = sum(1 for part in name_parts if part in proc_name_lower)
                    if matches >= 2:  # At least 2 parts must match
                        # Prefer processors with non-zero default TDP
                        if proc.get('default_tdp', 0) > 0:
                            return proc
                        # Keep as fallback if no better match found
                        if best_match is None:
                            best_match = proc
            # Return best match if found (even with 0 TDP as fallback)
            if best_match:
                return best_match
    
    return None

def find_processor_by_exact_name(model_name: str) -> Optional[Dict[str, Any]]:
    """Find processor by exact name matching"""
    if not load_processor_database() or not _PROCESSOR_DATABASE:
        return None
    
    model_lower = model_name.lower()
    
    # Try exact matches first
    for processor in _PROCESSOR_DATABASE:
        if processor['name'].lower() == model_lower:
            return processor
    
    # Try substring matches
    for processor in _PROCESSOR_DATABASE:
        proc_name_lower = processor['name'].lower()
        
        # Check if key parts of the model name are in processor name
        model_parts = model_lower.split()
        matches = 0
        for part in model_parts:
            if part in proc_name_lower:
                matches += 1
        
        # If most parts match, consider it a match
        if matches >= len(model_parts) * 0.7:
            return processor
    
    return None

def get_processor_info(cpu_model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get comprehensive processor information
    
    Args:
        cpu_model_override: Override CPU model for testing
        
    Returns:
        Dictionary with processor specifications or None if not found
    """
    if not load_processor_database():
        return None
    
    # Get CPU model name
    if cpu_model_override:
        model_name = cpu_model_override
    else:
        cpu_info = get_cpu_info()
        model_name = cpu_info.get('model_name', 'Unknown CPU')
    
    # Try different matching strategies
    processor = None
    
    # Strategy 1: Pattern-based detection
    processor = find_processor_by_pattern(model_name)
    
    # Strategy 2: Exact name matching  
    if not processor:
        processor = find_processor_by_exact_name(model_name)
    
    if processor:
        # Add detected model name for reference
        processor_copy = processor.copy()
        processor_copy['detected_model'] = model_name
        return processor_copy
    
    return None

def get_processor_tdp_info(cpu_model_override: Optional[str] = None) -> Dict[str, int]:
    """
    Get TDP information for the current processor
    
    Returns:
        Dictionary with default_tdp, tdp_min, tdp_max
    """
    processor = get_processor_info(cpu_model_override)
    
    if processor:
        return {
            'default_tdp': processor.get('default_tdp', 15),
            'tdp_min': processor.get('tdp_min', 10),
            'tdp_max': processor.get('tdp_max', 25),
            'processor_name': processor.get('name', 'Unknown'),
            'vendor': processor.get('vendor', 'Unknown')
        }
    else:
        # Fallback values
        return {
            'default_tdp': 15,
            'tdp_min': 10, 
            'tdp_max': 25,
            'processor_name': 'Unknown',
            'vendor': 'Unknown'
        }

def list_processors_by_vendor(vendor: str) -> List[Dict[str, Any]]:
    """List all processors by vendor (AMD or Intel)"""
    if not load_processor_database() or not _PROCESSOR_DATABASE:
        return []
    
    return [p for p in _PROCESSOR_DATABASE if p['vendor'].lower() == vendor.lower()]

def search_processors(query: str) -> List[Dict[str, Any]]:
    """Search processors by name or pattern"""
    if not load_processor_database() or not _PROCESSOR_DATABASE:
        return []
    
    query_lower = query.lower()
    results = []
    
    for processor in _PROCESSOR_DATABASE:
        if query_lower in processor['name'].lower():
            results.append(processor)
    
    return results

def get_database_stats() -> Dict[str, Any]:
    """Get statistics about the processor database"""
    if not load_processor_database() or not _PROCESSOR_DATABASE:
        return {}
    
    amd_count = len([p for p in _PROCESSOR_DATABASE if p['vendor'] == 'AMD'])
    intel_count = len([p for p in _PROCESSOR_DATABASE if p['vendor'] == 'Intel'])
    
    return {
        'total_processors': len(_PROCESSOR_DATABASE),
        'amd_processors': amd_count,
        'intel_processors': intel_count,
        'detection_patterns': len(_DETECTION_PATTERNS) if _DETECTION_PATTERNS else 0
    }

# Testing functions
def test_5560u_detection():
    """Test that 5560U is detected correctly with proper TDP"""
    test_names = [
        "AMD Ryzen 5 5560U with Radeon Graphics",
        "AMD Ryzen™ 5 5560U",
        "5560U"
    ]
    
    for name in test_names:
        processor = get_processor_info(name)
        if processor:
            print(f"Found {name}:")
            print(f"   Name: {processor['name']}")
            print(f"   Default TDP: {processor['default_tdp']}W")
            print(f"   TDP Range: {processor['tdp_min']}W - {processor['tdp_max']}W")
            print(f"   Vendor: {processor['vendor']}")
            print()
        else:
            print(f"Failed to find {name}")

if __name__ == "__main__":
    # Run tests
    print("PowerDeck Unified Processor Database Test")
    print("=" * 50)
    
    # Show database stats
    stats = get_database_stats()
    print(f"Database loaded: {stats}")
    print()
    
    # Test 5560U specifically
    print("Testing 5560U Detection:")
    test_5560u_detection()
    
    # Test current system
    print("Current System Detection:")
    current = get_processor_info()
    if current:
        print(f"Detected: {current['name']}")
        print(f"   Default TDP: {current['default_tdp']}W")
        print(f"   TDP Range: {current['tdp_min']}W - {current['tdp_max']}W")
    else:
        print("Could not detect current processor")
