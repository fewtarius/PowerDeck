"""
PowerDeck Settings Management
Modern settings system with validation and persistence
"""
import json
import os
import time
import decky_plugin
from typing import Dict, Any, Optional, Union
from pathlib import Path


class PowerDeckSettings:
    """Centralized settings management for PowerDeck"""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize settings manager"""
        self.config_dir = Path(config_dir) if config_dir else Path(decky_plugin.DECKY_PLUGIN_SETTINGS_DIR)
        self.config_file = self.config_dir / "powerdeck_settings.json"
        self.settings_cache = {}
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing settings
        self._load_settings()
    
    def _load_settings(self) -> None:
        """Load settings from file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    self.settings_cache = json.load(f)
                    decky_plugin.logger.info(f"Loaded settings from {self.config_file}")
            else:
                # Initialize with default settings
                self.settings_cache = self._get_default_settings()
                self._save_settings()
                decky_plugin.logger.info("Initialized with default settings")
        except Exception as e:
            decky_plugin.logger.error(f"Failed to load settings: {e}")
            self.settings_cache = self._get_default_settings()
    
    def _save_settings(self) -> bool:
        """Save settings to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings_cache, f, indent=2)
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to save settings: {e}")
            return False
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default settings configuration"""
        return {
            # Performance settings
            "default_profile": "balanced",
            "auto_apply_profiles": True,
            "max_tdp_on_resume": True,
            "enable_game_profiles": True,
            
            # UI settings
            "show_advanced_options": False,
            "temperature_unit": "celsius",  # celsius or fahrenheit
            "theme": "auto",  # auto, light, dark
            "compact_mode": False,
            
            # Safety settings
            "enable_thermal_protection": True,
            "max_safe_temperature": 85,
            "emergency_profile": "battery_saver",
            "enable_power_limits": True,
            
            # Logging and debug
            "log_level": "info",
            "enable_debug_mode": False,
            "telemetry_enabled": False,
            
            # Advanced settings
            "custom_ryzenadj_path": "",
            "enable_experimental_features": False,
            "startup_delay": 2.0,
            "polling_interval": 5.0,
            
            # Compatibility settings
            "force_device_detection": False,
            "override_device_type": "",
            "custom_tdp_limits": {},
            
            # Notification settings
            "show_profile_notifications": True,
            "show_temperature_warnings": True,
            "notification_duration": 3000,
            
            # Import/Export settings
            "backup_on_profile_change": True,
            "auto_backup_interval": 86400,  # 24 hours in seconds
            "max_backup_files": 10,
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value"""
        return self.settings_cache.get(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """Set a setting value"""
        try:
            self.settings_cache[key] = value
            return self._save_settings()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set setting {key}: {e}")
            return False
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings"""
        return self.settings_cache.copy()
    
    def update_multiple(self, settings: Dict[str, Any]) -> bool:
        """Update multiple settings at once"""
        try:
            self.settings_cache.update(settings)
            return self._save_settings()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to update settings: {e}")
            return False
    
    def reset_to_defaults(self) -> bool:
        """Reset all settings to defaults"""
        try:
            self.settings_cache = self._get_default_settings()
            return self._save_settings()
        except Exception as e:
            decky_plugin.logger.error(f"Failed to reset settings: {e}")
            return False
    
    def validate_setting(self, key: str, value: Any) -> bool:
        """Validate a setting value"""
        validators = {
            "max_safe_temperature": lambda v: isinstance(v, (int, float)) and 50 <= v <= 100,
            "polling_interval": lambda v: isinstance(v, (int, float)) and v >= 1.0,
            "startup_delay": lambda v: isinstance(v, (int, float)) and v >= 0,
            "notification_duration": lambda v: isinstance(v, int) and v >= 0,
            "max_backup_files": lambda v: isinstance(v, int) and v >= 1,
            "auto_backup_interval": lambda v: isinstance(v, int) and v >= 300,  # Min 5 minutes
            "temperature_unit": lambda v: v in ["celsius", "fahrenheit"],
            "theme": lambda v: v in ["auto", "light", "dark"],
            "log_level": lambda v: v in ["debug", "info", "warning", "error", "critical"],
        }
        
        if key in validators:
            return validators[key](value)
        
        return True  # No validation for unknown settings
    
    def export_settings(self) -> Dict[str, Any]:
        """Export settings for backup/sharing"""
        return {
            "powerdeck_settings": self.settings_cache.copy(),
            "export_version": "1.0",
            "export_timestamp": int(time.time())
        }
    
    def import_settings(self, imported_data: Dict[str, Any]) -> bool:
        """Import settings from backup/sharing"""
        try:
            if "powerdeck_settings" not in imported_data:
                decky_plugin.logger.error("Invalid settings import format")
                return False
            
            imported_settings = imported_data["powerdeck_settings"]
            
            # Validate imported settings
            valid_settings = {}
            for key, value in imported_settings.items():
                if self.validate_setting(key, value):
                    valid_settings[key] = value
                else:
                    decky_plugin.logger.warning(f"Skipping invalid setting: {key}={value}")
            
            # Merge with current settings (don't overwrite everything)
            self.settings_cache.update(valid_settings)
            return self._save_settings()
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to import settings: {e}")
            return False
    
    def delete_setting(self, key: str) -> bool:
        """Delete a setting (revert to default)"""
        try:
            if key in self.settings_cache:
                del self.settings_cache[key]
                return self._save_settings()
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to delete setting {key}: {e}")
            return False


# Global settings instance
_settings_instance = None


def get_settings() -> PowerDeckSettings:
    """Get global settings instance"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = PowerDeckSettings()
    return _settings_instance


def reset_settings_instance():
    """Reset the global settings instance (for testing)"""
    global _settings_instance
    _settings_instance = None
