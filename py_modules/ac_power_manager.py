"""
Hardware-level AC power detection module
Based on reference/SimpleDeckyTDP/py_modules/ac_power.py
Enhanced to monitor both AC supply and battery status files
"""
import os
import glob
import decky

AC_POWER_PATH = None
BATTERY_STATUS_PATHS = []

def find_power_supply_paths():
    """Find all power supply paths for AC and battery monitoring"""
    global AC_POWER_PATH, BATTERY_STATUS_PATHS
    
    try:
        # Find AC power supply paths (AC*, ADP*, ACAD, etc.)
        ac_patterns = ['/sys/class/power_supply/AC*/online', 
                      '/sys/class/power_supply/ADP*/online',
                      '/sys/class/power_supply/ACAD/online']
        
        for pattern in ac_patterns:
            matches = glob.glob(pattern)
            if matches:
                AC_POWER_PATH = matches[0]
                decky.logger.info(f"Found AC power path: {AC_POWER_PATH}")
                break
        
        # Find battery status paths (BAT*, etc.)
        battery_patterns = ['/sys/class/power_supply/BAT*/status',
                           '/sys/class/power_supply/battery/status']
        
        for pattern in battery_patterns:
            matches = glob.glob(pattern)
            BATTERY_STATUS_PATHS.extend(matches)
        
        if BATTERY_STATUS_PATHS:
            decky.logger.info(f"Found battery status paths: {BATTERY_STATUS_PATHS}")
        
        return AC_POWER_PATH, BATTERY_STATUS_PATHS
        
    except Exception as e:
        decky.logger.error(f"Power supply path detection failed: {e}")
        return None, []

def get_ac_power_path():
    """Find the AC power supply path from hardware"""
    global AC_POWER_PATH

    if AC_POWER_PATH:
        return AC_POWER_PATH

    ac_path, _ = find_power_supply_paths()
    return ac_path

def supports_hardware_ac_detection():
    """Check if hardware-level AC power detection is available"""
    ac_power_path = get_ac_power_path()
    return bool(ac_power_path) and os.path.exists(ac_power_path)

def get_hardware_ac_status():
    """Get AC power status directly from hardware with enhanced detection"""
    try:
        # Method 1: Direct AC power supply reading
        ac_power_path = get_ac_power_path()
        if ac_power_path and os.path.exists(ac_power_path):
            with open(ac_power_path, 'r') as f:
                ac_status = f.read().strip()
                decky.logger.debug(f"AC power direct reading: {ac_status}")
                if ac_status == "1":
                    return True
                elif ac_status == "0":
                    return False
        
        # Method 2: Battery status reading (Charging/Not charging)
        global BATTERY_STATUS_PATHS
        if not BATTERY_STATUS_PATHS:
            _, BATTERY_STATUS_PATHS = find_power_supply_paths()
        
        for battery_path in BATTERY_STATUS_PATHS:
            if os.path.exists(battery_path):
                with open(battery_path, 'r') as f:
                    battery_status = f.read().strip().lower()
                    decky.logger.debug(f"Battery status reading: {battery_status}")
                    
                    # Charging/Full = AC power connected
                    if battery_status in ['charging', 'full']:
                        return True
                    # Discharging/Not charging = on battery
                    elif battery_status in ['discharging', 'not charging']:
                        return False
        
        decky.logger.warning("Could not determine AC power status from hardware")
        return None
            
    except Exception as e:
        decky.logger.error(f"Hardware AC detection failed: {e}")
        return None

def debug_power_supply_info():
    """Debug function to log all power supply information"""
    try:
        decky.logger.info("=== POWER SUPPLY DEBUG INFO ===")
        power_supplies = glob.glob('/sys/class/power_supply/*')
        
        for supply_path in power_supplies:
            supply_name = os.path.basename(supply_path)
            decky.logger.info(f"Power supply: {supply_name}")
            
            # Check online status
            online_path = os.path.join(supply_path, 'online')
            if os.path.exists(online_path):
                with open(online_path, 'r') as f:
                    online_status = f.read().strip()
                    decky.logger.info(f"  {supply_name}/online: {online_status}")
            
            # Check status
            status_path = os.path.join(supply_path, 'status')
            if os.path.exists(status_path):
                with open(status_path, 'r') as f:
                    status = f.read().strip()
                    decky.logger.info(f"  {supply_name}/status: {status}")
            
            # Check type
            type_path = os.path.join(supply_path, 'type')
            if os.path.exists(type_path):
                with open(type_path, 'r') as f:
                    psu_type = f.read().strip()
                    decky.logger.info(f"  {supply_name}/type: {psu_type}")
        
    except Exception as e:
        decky.logger.error(f"Power supply debug failed: {e}")
