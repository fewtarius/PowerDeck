"""
Profile Management System
Handles power profiles, per-game settings, and preset configurations
"""
import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import decky_plugin
from power_core import PowerProfile, RyzenadjConfiguration
from device_manager import get_device_capabilities

@dataclass
class CPUProfile:
    """CPU-specific profile settings"""
    governor: Optional[str] = None
    epp: Optional[str] = None
    boost_enabled: Optional[bool] = None
    smt_enabled: Optional[bool] = None

@dataclass
class GPUProfile:
    """GPU-specific profile settings"""
    mode: str = "balance"  # battery, balance, range, fixed
    min_frequency: Optional[int] = None
    max_frequency: Optional[int] = None
    fixed_frequency: Optional[int] = None

@dataclass
class PowerProfileData:
    """Complete power profile data"""
    name: str
    tdp: int
    cpu: CPUProfile = field(default_factory=CPUProfile)
    gpu: GPUProfile = field(default_factory=GPUProfile)
    ryzenadj_config: Optional[RyzenadjConfiguration] = None
    ac_profile: bool = False  # True if this is an AC power profile
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Handle nested dataclasses properly
        if self.ryzenadj_config:
            data['ryzenadj_config'] = asdict(self.ryzenadj_config)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PowerProfileData':
        """Create from dictionary (JSON deserialization)"""
        # Handle nested dataclasses
        cpu_data = data.get('cpu', {})
        gpu_data = data.get('gpu', {})
        ryzenadj_data = data.get('ryzenadj_config')
        
        cpu = CPUProfile(**cpu_data)
        gpu = GPUProfile(**gpu_data)
        ryzenadj_config = None
        if ryzenadj_data:
            ryzenadj_config = RyzenadjConfiguration(**ryzenadj_data)
        
        return cls(
            name=data.get('name', ''),
            tdp=data.get('tdp', 15),
            cpu=cpu,
            gpu=gpu,
            ryzenadj_config=ryzenadj_config,
            ac_profile=data.get('ac_profile', False)
        )

class ProfileManager:
    """Manages power profiles and settings"""
    
    def __init__(self):
        self.settings_dir = os.path.join(decky_plugin.DECKY_PLUGIN_SETTINGS_DIR, "PowerDeck")
        self.profiles_file = os.path.join(self.settings_dir, "profiles.json")
        self.settings_file = os.path.join(self.settings_dir, "settings.json")
        
        # Ensure settings directory exists
        os.makedirs(self.settings_dir, exist_ok=True)
        
        self._profiles: Dict[str, PowerProfileData] = {}
        self._game_profiles: Dict[str, str] = {}  # game_id -> profile_name
        self._settings: Dict[str, Any] = {}
        
        self._load_data()
        self._ensure_default_profiles()
    
    def _load_data(self):
        """Load profiles and settings from disk"""
        try:
            # Load profiles
            if os.path.exists(self.profiles_file):
                with open(self.profiles_file, 'r') as f:
                    data = json.load(f)
                    
                self._profiles = {}
                for name, profile_data in data.get('profiles', {}).items():
                    self._profiles[name] = PowerProfileData.from_dict(profile_data)
                
                self._game_profiles = data.get('game_profiles', {})
            
            # Load settings
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    self._settings = json.load(f)
                    
        except Exception as e:
            decky_plugin.logger.error(f"Failed to load profile data: {e}")
            self._profiles = {}
            self._game_profiles = {}
            self._settings = {}
    
    def _save_data(self):
        """Save profiles and settings to disk"""
        try:
            # Save profiles
            profiles_data = {
                'profiles': {name: profile.to_dict() for name, profile in self._profiles.items()},
                'game_profiles': self._game_profiles
            }
            
            with open(self.profiles_file, 'w') as f:
                json.dump(profiles_data, f, indent=2)
            
            # Save settings
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings, f, indent=2)
                
        except Exception as e:
            decky_plugin.logger.error(f"Failed to save profile data: {e}")
    
    def _ensure_default_profiles(self):
        """Ensure default profiles exist"""
        capabilities = get_device_capabilities()
        
        # Battery Saver profile
        if 'battery_saver' not in self._profiles:
            self._profiles['battery_saver'] = PowerProfileData(
                name="Battery Saver",
                tdp=max(3, capabilities.min_tdp),
                cpu=CPUProfile(
                    governor="powersave",
                    epp="power",
                    boost_enabled=False,
                    smt_enabled=True
                ),
                gpu=GPUProfile(mode="battery")
            )
        
        # Balanced profile
        if 'balanced' not in self._profiles:
            balanced_tdp = min(15, capabilities.max_tdp)
            self._profiles['balanced'] = PowerProfileData(
                name="Balanced",
                tdp=balanced_tdp,
                cpu=CPUProfile(
                    governor="schedutil",
                    epp="balance_power",
                    boost_enabled=True,
                    smt_enabled=True
                ),
                gpu=GPUProfile(mode="balance")
            )
        
        # Performance profile
        if 'performance' not in self._profiles:
            perf_tdp = min(25, capabilities.max_tdp)
            self._profiles['performance'] = PowerProfileData(
                name="Performance",
                tdp=perf_tdp,
                cpu=CPUProfile(
                    governor="performance",
                    epp="balance_performance",
                    boost_enabled=True,
                    smt_enabled=True
                ),
                gpu=GPUProfile(mode="range")
            )
        
        # Gaming profile
        if 'gaming' not in self._profiles:
            gaming_tdp = min(30, capabilities.max_tdp)
            self._profiles['gaming'] = PowerProfileData(
                name="Gaming",
                tdp=gaming_tdp,
                cpu=CPUProfile(
                    governor="performance",
                    epp="performance",
                    boost_enabled=True,
                    smt_enabled=True
                ),
                gpu=GPUProfile(mode="range")
            )
        
        # Default profile (current active profile)
        if 'default' not in self._profiles:
            self._profiles['default'] = PowerProfileData(
                name="Default",
                tdp=min(15, capabilities.max_tdp),
                cpu=CPUProfile(
                    governor="schedutil",
                    epp="balance_power",
                    boost_enabled=True,
                    smt_enabled=True
                ),
                gpu=GPUProfile(mode="balance")
            )
        
        self._save_data()
    
    # Profile Management
    def get_profile(self, name: str) -> Optional[PowerProfileData]:
        """Get profile by name"""
        return self._profiles.get(name)
    
    def get_all_profiles(self) -> Dict[str, PowerProfileData]:
        """Get all profiles"""
        return self._profiles.copy()
    
    def save_profile(self, profile: PowerProfileData) -> bool:
        """Save or update a profile"""
        try:
            self._profiles[profile.name.lower().replace(' ', '_')] = profile
            self._save_data()
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to save profile: {e}")
            return False
    
    def delete_profile(self, name: str) -> bool:
        """Delete a profile"""
        if name in ['default', 'battery_saver', 'balanced', 'performance', 'gaming']:
            decky_plugin.logger.error(f"Cannot delete built-in profile: {name}")
            return False
        
        try:
            if name in self._profiles:
                del self._profiles[name]
                
                # Remove any game assignments to this profile
                games_to_remove = [game_id for game_id, profile_name in self._game_profiles.items() 
                                 if profile_name == name]
                for game_id in games_to_remove:
                    del self._game_profiles[game_id]
                
                self._save_data()
                return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to delete profile: {e}")
        
        return False
    
    def clone_profile(self, source_name: str, new_name: str) -> bool:
        """Clone an existing profile"""
        source = self.get_profile(source_name)
        if not source:
            return False
        
        try:
            # Create a deep copy
            new_profile = PowerProfileData.from_dict(source.to_dict())
            new_profile.name = new_name
            
            return self.save_profile(new_profile)
        except Exception as e:
            decky_plugin.logger.error(f"Failed to clone profile: {e}")
            return False
    
    # Game Profile Management
    def get_game_profile(self, game_id: str) -> Optional[PowerProfileData]:
        """Get profile assigned to a specific game"""
        profile_name = self._game_profiles.get(game_id)
        if profile_name:
            return self.get_profile(profile_name)
        return None
    
    def assign_game_profile(self, game_id: str, profile_name: str) -> bool:
        """Assign a profile to a game"""
        if profile_name not in self._profiles:
            decky_plugin.logger.error(f"Profile {profile_name} does not exist")
            return False
        
        try:
            self._game_profiles[game_id] = profile_name
            self._save_data()
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to assign game profile: {e}")
            return False
    
    def remove_game_profile(self, game_id: str) -> bool:
        """Remove profile assignment from a game"""
        try:
            if game_id in self._game_profiles:
                del self._game_profiles[game_id]
                self._save_data()
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to remove game profile: {e}")
            return False
    
    def get_all_game_profiles(self) -> Dict[str, str]:
        """Get all game profile assignments"""
        return self._game_profiles.copy()
    
    # Settings Management
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value"""
        return self._settings.get(key, default)
    
    def set_setting(self, key: str, value: Any) -> bool:
        """Set a setting value"""
        try:
            self._settings[key] = value
            self._save_data()
            return True
        except Exception as e:
            decky_plugin.logger.error(f"Failed to set setting {key}: {e}")
            return False
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings"""
        return self._settings.copy()
    
    # Profile Presets
    def get_preset_profiles(self) -> List[str]:
        """Get list of preset profile names"""
        return ['battery_saver', 'balanced', 'performance', 'gaming']
    
    def apply_preset_profile(self, preset: PowerProfile) -> bool:
        """Apply a preset profile to default"""
        preset_map = {
            PowerProfile.BATTERY_SAVER: 'battery_saver',
            PowerProfile.BALANCED: 'balanced',
            PowerProfile.PERFORMANCE: 'performance',
            PowerProfile.GAMING: 'gaming'
        }
        
        preset_name = preset_map.get(preset)
        if not preset_name:
            return False
        
        preset_profile = self.get_profile(preset_name)
        if not preset_profile:
            return False
        
        # Copy preset to default profile
        default_profile = PowerProfileData.from_dict(preset_profile.to_dict())
        default_profile.name = "Default"
        
        return self.save_profile(default_profile)
    
    # Import/Export
    def export_profiles(self) -> Dict[str, Any]:
        """Export all profiles and settings"""
        return {
            'profiles': {name: profile.to_dict() for name, profile in self._profiles.items()},
            'game_profiles': self._game_profiles,
            'settings': self._settings,
            'version': '1.0'
        }
    
    def import_profiles(self, data: Dict[str, Any]) -> bool:
        """Import profiles and settings"""
        try:
            version = data.get('version', '1.0')
            
            # Import profiles
            if 'profiles' in data:
                for name, profile_data in data['profiles'].items():
                    # Don't overwrite built-in profiles
                    if name not in ['battery_saver', 'balanced', 'performance', 'gaming']:
                        self._profiles[name] = PowerProfileData.from_dict(profile_data)
            
            # Import game profiles
            if 'game_profiles' in data:
                self._game_profiles.update(data['game_profiles'])
            
            # Import settings (merge, don't replace)
            if 'settings' in data:
                self._settings.update(data['settings'])
            
            self._save_data()
            return True
            
        except Exception as e:
            decky_plugin.logger.error(f"Failed to import profiles: {e}")
            return False

# Global profile manager instance
_profile_manager = None

def get_profile_manager() -> ProfileManager:
    """Get global profile manager instance"""
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProfileManager()
    return _profile_manager
