"""
PowerDeck Utility Functions
Common utility functions for the PowerDeck plugin
"""
import os
import subprocess
import json
import time
import hashlib
import shutil
import decky_plugin
from typing import Dict, List, Optional, Any, Union, Tuple
from pathlib import Path


def run_command(command: Union[str, List[str]], timeout: float = 30.0) -> Tuple[bool, str, str]:
    """
    Execute a shell command with timeout and error handling
    
    Args:
        command: Command to execute (string or list)
        timeout: Command timeout in seconds
        
    Returns:
        Tuple of (success, stdout, stderr)
    """
    try:
        if isinstance(command, str):
            command = command.split()
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        
        success = result.returncode == 0
        return success, result.stdout.strip(), result.stderr.strip()
        
    except subprocess.TimeoutExpired:
        decky_plugin.logger.error(f"Command timed out after {timeout}s: {' '.join(command)}")
        return False, "", "Command timed out"
    except Exception as e:
        decky_plugin.logger.error(f"Command execution failed: {e}")
        return False, "", str(e)


def get_file_hash(file_path: str) -> Optional[str]:
    """Get SHA-256 hash of a file"""
    try:
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception as e:
        decky_plugin.logger.error(f"Failed to hash file {file_path}: {e}")
        return None


def ensure_directory(path: str) -> bool:
    """Ensure a directory exists, creating it if necessary"""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        decky_plugin.logger.error(f"Failed to create directory {path}: {e}")
        return False


def read_file_safe(file_path: str, default: str = "") -> str:
    """Safely read a file, returning default if it fails"""
    try:
        with open(file_path, 'r') as f:
            return f.read().strip()
    except Exception:
        return default


def write_file_safe(file_path: str, content: str) -> bool:
    """Safely write to a file"""
    try:
        # Ensure parent directory exists
        ensure_directory(str(Path(file_path).parent))
        
        with open(file_path, 'w') as f:
            f.write(content)
        return True
    except Exception as e:
        decky_plugin.logger.error(f"Failed to write file {file_path}: {e}")
        return False


def find_executable(name: str) -> Optional[str]:
    """Find an executable in PATH or common locations"""
    # Check PATH first
    path = shutil.which(name)
    if path:
        return path
    
    # Check common locations
    common_paths = [
        f"/usr/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/opt/bin/{name}",
        f"/home/deck/.local/bin/{name}",
        f"/usr/sbin/{name}",
        f"/sbin/{name}"
    ]
    
    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    
    return None


def validate_tdp_value(tdp: int, min_tdp: int, max_tdp: int) -> bool:
    """Validate TDP value is within acceptable range"""
    return isinstance(tdp, int) and min_tdp <= tdp <= max_tdp


def clamp_value(value: Union[int, float], min_val: Union[int, float], max_val: Union[int, float]) -> Union[int, float]:
    """Clamp a value between min and max"""
    return max(min_val, min(max_val, value))


def get_process_list() -> List[Dict[str, Any]]:
    """Get list of running processes"""
    try:
        success, stdout, _ = run_command("ps aux")
        if not success:
            return []
        
        processes = []
        lines = stdout.split('\n')[1:]  # Skip header
        
        for line in lines:
            if not line.strip():
                continue
                
            parts = line.split(None, 10)  # Split into 11 parts max
            if len(parts) >= 11:
                processes.append({
                    'user': parts[0],
                    'pid': int(parts[1]),
                    'cpu': float(parts[2]),
                    'mem': float(parts[3]),
                    'command': parts[10]
                })
        
        return processes
    except Exception as e:
        decky_plugin.logger.error(f"Failed to get process list: {e}")
        return []


def is_process_running(process_name: str) -> bool:
    """Check if a process is running"""
    try:
        success, stdout, _ = run_command(f"pgrep -f {process_name}")
        return success and stdout.strip() != ""
    except Exception:
        return False


def get_system_info() -> Dict[str, Any]:
    """Get basic system information"""
    info = {
        'hostname': 'unknown',
        'kernel': 'unknown',
        'distro': 'unknown',
        'arch': 'unknown',
        'uptime': 0,
        'load_average': [0.0, 0.0, 0.0]
    }
    
    try:
        # Hostname
        success, stdout, _ = run_command("hostname")
        if success:
            info['hostname'] = stdout
        
        # Kernel version
        success, stdout, _ = run_command("uname -r")
        if success:
            info['kernel'] = stdout
        
        # Architecture
        success, stdout, _ = run_command("uname -m")
        if success:
            info['arch'] = stdout
        
        # Distribution
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release", 'r') as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        info['distro'] = line.split('=', 1)[1].strip().strip('"')
                        break
        
        # Uptime
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime", 'r') as f:
                info['uptime'] = float(f.read().split()[0])
        
        # Load average
        if os.path.exists("/proc/loadavg"):
            with open("/proc/loadavg", 'r') as f:
                loads = f.read().split()[:3]
                info['load_average'] = [float(x) for x in loads]
    
    except Exception as e:
        decky_plugin.logger.error(f"Failed to get system info: {e}")
    
    return info


def format_temperature(celsius: float, unit: str = "celsius") -> str:
    """Format temperature with unit"""
    if unit.lower() == "fahrenheit":
        fahrenheit = (celsius * 9/5) + 32
        return f"{fahrenheit:.1f}°F"
    else:
        return f"{celsius:.1f}°C"


def format_frequency(hz: int) -> str:
    """Format frequency in human-readable form"""
    if hz >= 1_000_000_000:
        return f"{hz / 1_000_000_000:.2f} GHz"
    elif hz >= 1_000_000:
        return f"{hz / 1_000_000:.0f} MHz"
    elif hz >= 1_000:
        return f"{hz / 1_000:.0f} kHz"
    else:
        return f"{hz} Hz"


def format_power(watts: Union[int, float]) -> str:
    """Format power consumption"""
    if watts >= 1000:
        return f"{watts / 1000:.2f} kW"
    else:
        return f"{watts:.1f} W"


def debounce_calls(func, delay: float = 1.0):
    """Decorator to debounce function calls"""
    last_called = {}
    
    def wrapper(*args, **kwargs):
        key = str(args) + str(kwargs)
        now = time.time()
        
        if key in last_called and (now - last_called[key]) < delay:
            return None
        
        last_called[key] = now
        return func(*args, **kwargs)
    
    return wrapper


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """Decorator to retry function calls on failure"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    decky_plugin.logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


def validate_json_schema(data: Dict[str, Any], required_fields: List[str]) -> bool:
    """Validate JSON data has required fields"""
    try:
        for field in required_fields:
            if field not in data:
                return False
        return True
    except Exception:
        return False


def backup_file(file_path: str, backup_dir: Optional[str] = None) -> bool:
    """Create a backup of a file"""
    try:
        if not os.path.exists(file_path):
            return False
        
        if backup_dir is None:
            backup_dir = str(Path(file_path).parent / "backups")
        
        ensure_directory(backup_dir)
        
        timestamp = int(time.time())
        filename = Path(file_path).name
        backup_path = Path(backup_dir) / f"{filename}.{timestamp}.bak"
        
        shutil.copy2(file_path, backup_path)
        decky_plugin.logger.info(f"Created backup: {backup_path}")
        return True
        
    except Exception as e:
        decky_plugin.logger.error(f"Failed to backup file {file_path}: {e}")
        return False


def cleanup_old_backups(backup_dir: str, max_files: int = 10) -> None:
    """Clean up old backup files"""
    try:
        if not os.path.exists(backup_dir):
            return
        
        backup_files = []
        for file in Path(backup_dir).iterdir():
            if file.is_file() and file.name.endswith('.bak'):
                backup_files.append((file.stat().st_mtime, file))
        
        # Sort by modification time (newest first)
        backup_files.sort(reverse=True)
        
        # Remove old files beyond max_files limit
        for _, file_path in backup_files[max_files:]:
            try:
                file_path.unlink()
                decky_plugin.logger.info(f"Removed old backup: {file_path}")
            except Exception as e:
                decky_plugin.logger.error(f"Failed to remove backup {file_path}: {e}")
                
    except Exception as e:
        decky_plugin.logger.error(f"Failed to cleanup backups in {backup_dir}: {e}")


class PowerDeckError(Exception):
    """Base exception for PowerDeck-specific errors"""
    pass


class ConfigurationError(PowerDeckError):
    """Configuration-related errors"""
    pass


class HardwareError(PowerDeckError):
    """Hardware-related errors"""
    pass


class ValidationError(PowerDeckError):
    """Data validation errors"""
    pass
