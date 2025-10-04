import {
  ButtonItem,
  definePlugin,
  staticClasses,
  SliderField,
  ToggleField,
  PanelSection,
  PanelSectionRow,
  Router
} from "@decky/ui";

import { useState, useEffect, useRef, useCallback, Component, ErrorInfo, ReactNode } from "react";
import { callable } from "@decky/api";

// React Icons imports
import { 
  FaBolt,           // Main plugin icon
  FaCog,            // Auto/settings
  FaVolumeOff,      // Quiet mode
  FaBalanceScale,   // Balanced modes
  FaFan,            // Aggressive cooling
  FaBatteryThreeQuarters, // Power saving
  FaBatteryHalf,    // Battery mode
  FaBatteryFull,    // Full power
  FaLightbulb,      // Conservative
  FaChartBar,       // On-demand
  FaChartLine,      // Balance performance
  FaCogs,           // Scheduler utilities
  FaRocket,         // Performance mode
  FaSyncAlt,        // Auto mode
  FaSlidersH,       // Range control (horizontal sliders)
  FaBullseye,       // Fixed mode
  FaCheckCircle,    // Up to date / success
  FaBell,           // Update available notification
  FaSpinner,        // Checking for updates
  FaSearch,         // Checking/searching
  FaDownload,       // Download/update available
  FaExclamationTriangle, // Error state
  FaThermometerHalf, // Temperature controls
  FaShieldAlt,      // MCU power save
  FaStopCircle,     // Fan stop
  FaDesktop,        // Performance profiles
  FaMicrochip,      // CPU fan
  FaMemory,         // GPU fan  
  FaBolt as FaLightning, // Power/lightning
  FaBatteryEmpty,   // Low power
  FaSnowflake,      // Cool/quiet
  FaFire,           // Hot/aggressive
  FaGamepad,        // Controller/InputPlumber
  FaSteam,          // Steam Deck
  FaPlaystation,    // PlayStation controllers
  FaXbox            // Xbox controllers
} from "react-icons/fa";

// Error Boundary Component for frontend resilience
interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: string | null;
}

class PowerDeckErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    // Update state to show error UI
    return { hasError: true, error, errorInfo: error.stack || "" };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Log error details
    debug.error("PowerDeck Frontend Error Boundary caught error:", error);
    debug.error("Error info:", errorInfo);
    
    // Auto-recovery attempt after 5 seconds
    setTimeout(() => {
      debug.log("Attempting auto-recovery from frontend error...");
      this.setState({ hasError: false, error: null, errorInfo: null });
    }, 5000);
  }

  render() {
    if (this.state.hasError) {
      return (
        <PanelSection title="PowerDeck - Error">
          <PanelSectionRow>
            <div style={{ padding: "20px", color: "#ff6b6b" }}>
              <div style={{ marginBottom: "10px" }}>
                WARNING: PowerDeck UI Error - Auto-recovering in 5 seconds...
              </div>
              <div style={{ fontSize: "0.8em", color: "#888" }}>
                Error: {this.state.error?.message || "Unknown error"}
              </div>
              <div style={{ marginTop: "10px" }}>
                <ButtonItem
                  onClick={() => {
                    debug.log("Manual recovery triggered");
                    this.setState({ hasError: false, error: null, errorInfo: null });
                  }}
                  layout="below"
                >
                  Retry Now
                </ButtonItem>
              </div>
            </div>
          </PanelSectionRow>
        </PanelSection>
      );
    }

    return this.props.children;
  }
}

// Debug logging (set to false for production)
const DEBUG_ENABLED = true;

// Version management - Read from backend, no hardcoded versions
// // Version managed by backend - no hardcoding // REMOVED - Use backend version instead

// Standardized debug logging
const debug = {
  log: (message: string, ...args: any[]) => {
    if (DEBUG_ENABLED) {
      console.log(`[PowerDeck] ${message}`, ...args);
    }
  },
  error: (message: string, ...args: any[]) => {
    if (DEBUG_ENABLED) {
      console.error(`[PowerDeck] ERROR: ${message}`, ...args);
    }
  },
  warn: (message: string, ...args: any[]) => {
    if (DEBUG_ENABLED) {
      console.warn(`[PowerDeck] WARNING: ${message}`, ...args);
    }
  }
};

// Frontend-based game detection (SimpleDeckyTDP approach) 
function getCurrentGameId() {
  const appId = Router.MainRunningApp?.appid || "default";
  return `${appId}`;
}

function getCurrentGameInfo() {
  const appid = Router.MainRunningApp?.appid || "default";
  const display_name = Router.MainRunningApp?.display_name || "Default";
  
  // ENHANCED: Check additional Router properties for better non-Steam game detection
  if (DEBUG_ENABLED) {
    debug.log("Router.MainRunningApp full object:", Router.MainRunningApp);
    debug.log("Available properties:", Object.keys(Router.MainRunningApp || {}));
  }
  
  // For non-Steam games, try to create a more stable identifier
  let gameId = appid;
  let gameName = display_name;
  
  // Enhanced non-Steam game detection: Use display name to create stable ID
  if (display_name && display_name !== "Default" && display_name !== "Steam") {
    // For non-Steam games, create a stable ID based on the display name
    // Remove spaces, convert to lowercase, and create hash-like identifier
    const cleanName = display_name.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
    if (cleanName.length > 0) {
      // Create a simple hash-like ID from the game name
      let hash = 0;
      for (let i = 0; i < cleanName.length; i++) {
        const char = cleanName.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32-bit integer
      }
      const stableId = `nonsteam_${Math.abs(hash)}`;
      
      debug.log(`Enhanced game detection: "${display_name}" -> ID: ${stableId} (was: ${appid})`);
      
      // Use the stable ID if the original appid looks generic
      if (appid === "default" || appid === "00000000" || appid.length < 3) {
        gameId = stableId;
        debug.log(`Using enhanced ID for non-Steam game: ${stableId}`);
      }
    }
  }
  
  return {
    id: gameId,
    name: gameName,
    displayName: gameName
  };
}

// Frontend-backend coordination: Update backend when frontend detects different game
async function updateBackendGameDetection() {
  try {
    const frontendGame = getCurrentGameInfo();
    if (frontendGame.id !== "default" && frontendGame.id !== "00000000") {
      debug.log("Frontend detected real game, updating backend:", frontendGame);
      // Trigger backend to switch to the real game profile
      const isAC = await getAcPowerStatus();
      const realGameId = isAC ? `${frontendGame.id}_ac` : `${frontendGame.id}_battery`;
      
      // Load/create profile for the real game
      const gameProfile = await getGameProfile(realGameId);
      if (gameProfile) {
        debug.log("Switching backend to real game profile:", realGameId);
        await setGameProfile(realGameId, gameProfile);
      }
    }
  } catch (error) {
    debug.error("Error updating backend game detection:", error);
  }
}

// Backend callable functions - Core System
const setTdp = callable<[tdp: number], boolean>("set_tdp");
const setCpuBoost = callable<[enabled: boolean], boolean>("set_cpu_boost");
const setCpuCores = callable<[cores: number], boolean>("set_cpu_cores");
const setGovernor = callable<[governor: string], boolean>("set_governor");
const setFanProfile = callable<[profile: string], boolean>("set_fan_profile");
const getAcPowerStatus = callable<[], boolean>("get_ac_power_status");

// Backend callable functions - Advanced System Control
const setSmt = callable<[enabled: boolean], boolean>("set_smt");
const setEpp = callable<[epp: string], boolean>("set_epp");
const setGpuMode = callable<[mode: string], boolean>("set_gpu_mode");
const setGpuFrequency = callable<[min: number, max: number], boolean>("set_gpu_frequency");

// Backend callable functions - Universal Power Management
const getUsbAutosuspendStatus = callable<[], { [key: string]: boolean }>("get_usb_autosuspend_status");
const setUsbAutosuspend = callable<[enabled: boolean], boolean>("set_usb_autosuspend");
const setWifiPowerSave = callable<[enabled: boolean], boolean>("set_wifi_power_save");
const getPcieAspmPolicy = callable<[], string>("get_pcie_aspm_policy");
const setPcieAspmPolicy = callable<[policy: string], boolean>("set_pcie_aspm_policy");


// Backend callable functions - Core functions
const getDeviceInfo = callable<[], any>("get_device_info");
const getDefaultTdp = callable<[], number>("get_default_tdp");
const getAvailableGovernors = callable<[], string[]>("get_available_governors");
const applyProfile = callable<[profile: any], boolean>("apply_profile");
const getTdpLimits = callable<[], { min: number; max: number }>("get_tdp_limits");
const getAvailableFanProfiles = callable<[], string[]>("get_available_fan_profiles");

// ROG Ally specific callable functions
const getRogAllyDeviceInfo = callable<[], any>("get_rog_ally_device_info");
const setRogAllyPowerLimitsBackend = callable<[fast_limit: number, sustained_limit: number, stapm_limit: number], boolean>("set_rog_ally_power_limits");
const getRogAllyPowerLimits = callable<[], {fast_limit: number | null, sustained_limit: number | null, stapm_limit: number | null}>("get_rog_ally_power_limits");
const setRogAllyPlatformProfileBackend = callable<[profile: string], boolean>("set_rog_ally_platform_profile");
const getRogAllyPlatformProfile = callable<[], string | null>("get_rog_ally_platform_profile");
const setRogAllyMcuPowersaveBackend = callable<[enabled: boolean], boolean>("set_rog_ally_mcu_powersave");
const getRogAllyMcuPowersave = callable<[], boolean | null>("get_rog_ally_mcu_powersave");
const setRogAllyThermalThrottlePolicyBackend = callable<[policy: number], boolean>("set_rog_ally_thermal_throttle_policy");
const getRogAllyThermalThrottlePolicy = callable<[], number | null>("get_rog_ally_thermal_throttle_policy");
const setRogAllyFanModeBackend = callable<[fan_id: number, mode: number], boolean>("set_rog_ally_fan_mode");
const getRogAllyFanStatus = callable<[], any>("get_rog_ally_fan_status");
const setRogAllyBatteryChargeLimitBackend = callable<[limit: number], boolean>("set_rog_ally_battery_charge_limit");
const getRogAllyBatteryChargeLimit = callable<[], number | null>("get_rog_ally_battery_charge_limit");
const setRogAllyPerformanceMode = callable<[mode: string], boolean>("set_rog_ally_performance_mode");
const getRogAllyComprehensiveStatus = callable<[], any>("get_rog_ally_comprehensive_status");
const setGameProfile = callable<[gameId: string, profile: any], boolean>("set_game_profile");
const getGameProfile = callable<[gameId: string], any>("get_game_profile");
const getPerGameProfilesEnabled = callable<[], boolean>("get_per_game_profiles_enabled");
const setPerGameProfilesEnabled = callable<[enabled: boolean], boolean>("set_per_game_profiles_enabled");
const updatePlugin = callable<[], boolean>("update_plugin");
const getCurrentVersion = callable<[], string>("get_current_version");
const getLatestVersion = callable<[], string>("get_latest_version");
const getUpdateStatus = callable<[], any>("get_update_status");
const checkForUpdates = callable<[], any>("check_for_updates");
const stageUpdate = callable<[downloadUrl: string, version: string], any>("stage_update");
const installStagedUpdate = callable<[], any>("install_staged_update");

// ROG Ally native TDP toggle functions
const getRogAllyNativeTdpEnabled = callable<[], boolean>("get_rog_ally_native_tdp_enabled");
const setRogAllyNativeTdpEnabled = callable<[enabled: boolean], boolean>("set_rog_ally_native_tdp_enabled");
const isRogAllyDevice = callable<[], boolean>("is_rog_ally_device");
const getTdpControlMode = callable<[], string>("get_tdp_control_mode");

// InputPlumber Integration - Controller Emulation
const getInputPlumberStatus = callable<[], any>("get_inputplumber_status");
const getInputPlumberModes = callable<[], any[]>("get_inputplumber_modes");
const setInputPlumberMode = callable<[mode: string], boolean>("set_inputplumber_mode");
const getInputPlumberProfileForGame = callable<[gameId: string], any | null>("get_inputplumber_profile_for_game");
const saveInputPlumberProfileForGame = callable<[gameId: string, settings: any], boolean>("save_inputplumber_profile_for_game");
const applyInputPlumberProfileForGame = callable<[gameId: string], boolean>("apply_inputplumber_profile_for_game");

// Controller mode display labels (essential modes only)
const CONTROLLER_MODE_LABELS: { [key: string]: { name: string; description: string } } = {
  'default': { name: 'Default', description: 'Standard Steam Input' },
  'xbox-series': { name: 'Xbox', description: 'Xbox Series X|S controller' },
  'xbox-elite': { name: 'Xbox Elite', description: 'Xbox Elite controller' },
  'ds5-edge': { name: 'DualSense Edge', description: 'PlayStation 5 DualSense Edge' },
  'deck-uhid': { name: 'Steam Deck', description: 'Steam Deck native input' }
};

// Controller mode icons
const getControllerIcon = (mode: string) => {
  switch (mode) {
    case 'default': return <FaGamepad />;
    case 'xbox-series': return <FaXbox />;
    case 'xbox-elite': return <FaXbox />;
    case 'ds5-edge': return <FaPlaystation />;
    case 'deck-uhid': return <FaSteam />;
    default: return <FaGamepad />;
  }
};

// Backend callable functions - Additional unused functions (kept for completeness, will be optimized later)

interface PowerProfile {
  tdp: number;
  cpuBoost: boolean;
  cpuCores: number;
  governor: string;
  fanProfile: string;
  smt: boolean;
  epp: string;
  gpuMode: string;
  gpuFreqMin: number;
  gpuFreqMax: number;
  gpuFreqFixed: number;
  wifiPowerSave?: boolean;
  pciePowerManagement?: boolean;
  usbAutosuspend?: boolean;
  pcieAspm?: boolean;
}

interface DeviceInfo {
  device_name: string;
  cpu_name: string;
  tdp_min: number;
  tdp_max: number;
  cpu_core_count: number;
  max_cpu_cores: number;
  has_fan_control: boolean;
  supports_cpu_boost: boolean;
  supports_smt: boolean;
  supports_epp: boolean;
  supports_gpu_control: boolean;
  min_gpu_freq: number;
  max_gpu_freq: number;
}

// Component for slider with React icon overlays
const SliderWithIcons: React.FC<{
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  icons: React.ReactNode[];
  onChange: (value: number) => void;
  showValue?: boolean;
  bottomSeparator?: "none" | "standard" | "thick";
}> = ({ 
  label, 
  value, 
  min, 
  max, 
  step = 1, 
  icons, 
  onChange, 
  showValue = false,
  bottomSeparator = "none"
}) => {
  const notchCount = icons.length;
  
  return (
    <div style={{ position: 'relative', marginLeft: '-16px' }}>
      <SliderField
        label={label}
        value={value}
        min={min}
        max={max}
        step={step}
        notchCount={notchCount}
        notchLabels={icons.map((_, index) => ({ notchIndex: index, label: "", value: index }))}
        notchTicksVisible={true}
        showValue={showValue}
        bottomSeparator={bottomSeparator}
        onChange={onChange}
      />
      {/* Icon overlay */}
      <div style={{ 
        position: 'absolute', 
        top: '100%', 
        left: '18px', 
        right: '2px', 
        height: '16px',
        marginTop: '-17px',
        display: 'flex', 
        justifyContent: 'space-between',
        alignItems: 'center',
        pointerEvents: 'none',
        zIndex: 10
      }}>
        {icons.map((icon, index) => (
          <div 
            key={index}
            style={{ 
              color: value === index ? '#00d4ff' : '#888',
              fontSize: '1.2em',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'color 0.2s ease'
            }}
          >
            {icon}
          </div>
        ))}
      </div>
    </div>
  );
};
const DebouncedSlider: React.FC<{
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  onChangeEnd?: (value: number) => void;
  disabled?: boolean;
  showValue?: boolean;
  suffix?: string;
}> = ({ 
  label, 
  value, 
  min, 
  max, 
  step = 1, 
  onChange, 
  onChangeEnd, 
  disabled = false,
  showValue = true,
  suffix = ""
}) => {
  const [internalValue, setInternalValue] = useState(value);
  const timeoutRef = useRef<any>();

  useEffect(() => {
    setInternalValue(value);
  }, [value]);

  const handleChange = useCallback((newValue: number) => {
    setInternalValue(newValue);
    onChange(newValue);

    if (onChangeEnd) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => {
        onChangeEnd(newValue);
      }, 500); // 500ms debounce
    }
  }, [onChange, onChangeEnd]);

  const displayLabel = showValue ? `${label}: ${isNaN(internalValue) ? 'undefined' : internalValue}${suffix}` : label;

  return (
    <PanelSectionRow>
      <SliderField
        label={displayLabel}
        value={internalValue}
        min={min}
        max={max}
        step={step}
        onChange={handleChange}
        disabled={disabled}
      />
    </PanelSectionRow>
  );
};

const Content: React.FC = () => {
  // Add CSS for animations
  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
    `;
    document.head.appendChild(style);
    return () => {
      document.head.removeChild(style);
    };
  }, []);

  // Plugin version state - Read from backend (no hardcoding)
  const [pluginVersion, setPluginVersion] = useState<string>("Loading...");
  
  // Core state
  const [acPower, setAcPower] = useState<boolean>(false);
  const [activeProfile, setActiveProfile] = useState<'ac' | 'battery'>('battery');
  const [deviceInfo, setDeviceInfo] = useState<DeviceInfo | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Unified Profile state - SINGLE PROFILE MANAGEMENT SYSTEM
  const [currentProfile, setCurrentProfile] = useState<PowerProfile>({
    tdp: 15,  // Will be updated to database default during initialization
    cpuBoost: true,
    cpuCores: 8,
    governor: "performance",
    fanProfile: "moderate",
    smt: true,
    epp: "performance",
    gpuMode: "auto",
    gpuFreqMin: 300, // Safe default for Intel devices
    gpuFreqMax: 1100, // Safe default for Intel devices  
    gpuFreqFixed: 700,
    usbAutosuspend: false, // Default to disabled for stability
    pcieAspm: false // Default to disabled for stability
  });

  const [currentProfileId, setCurrentProfileId] = useState<string>("00000000_ac");

  // UI state
  const [showAdvancedTdp, setShowAdvancedTdp] = useState<boolean>(false);
  const [customTdpMin, setCustomTdpMin] = useState<number>(3);
  const [customTdpMax, setCustomTdpMax] = useState<number>(30);

  // Additional Power Management States
  const [perGameProfilesEnabled, setPerGameProfilesEnabledState] = useState<boolean>(true);

  // Game detection state 
  const [currentGame, setCurrentGame] = useState<{ id: string; name: string }>({ id: "handheld", name: "Handheld" });
  const [deviceClassification, setDeviceClassification] = useState<string>("Device");

  // Quiet mode optimization - track last applied profile to avoid redundant system calls
  const [lastAppliedProfile, setLastAppliedProfile] = useState<PowerProfile | null>(null);

  // Advanced Power Management State - WiFi enabled by default, others disabled
  const [showAdvancedMenu, setShowAdvancedMenu] = useState<boolean>(false);
  const [wifiPowerSaveEnabled, setWifiPowerSaveEnabled] = useState<boolean>(true);
  const [usbAutosuspendEnabled, setUsbAutosuspendEnabled] = useState<boolean>(false);
  const [pcieAspmEnabled, setPcieAspmEnabled] = useState<boolean>(false);

  // Available options from device
  const [availableGovernors, setAvailableGovernors] = useState<string[]>(['performance', 'powersave', 'ondemand', 'conservative', 'schedutil']);
  const [availableFanProfiles, setAvailableFanProfiles] = useState<string[]>(['auto', 'quiet', 'moderate', 'aggressive']);
  const [tdpLimits, setTdpLimits] = useState<{ min: number; max: number }>({ min: 4, max: 30 });

  // ROG Ally specific state
  const [isRogAlly, setIsRogAlly] = useState<boolean>(false);
  const [rogAllyDeviceInfo, setRogAllyDeviceInfo] = useState<any>(null);
  const [rogAllyPowerLimits, setRogAllyPowerLimits] = useState<{fast_limit: number | null, sustained_limit: number | null, stapm_limit: number | null}>({
    fast_limit: null, sustained_limit: null, stapm_limit: null
  });
  const [rogAllyPlatformProfile, setRogAllyPlatformProfile] = useState<string>('balanced');
  const [rogAllyMcuPowersave, setRogAllyMcuPowersave] = useState<boolean>(true);
  const [rogAllyThermalPolicy, setRogAllyThermalPolicy] = useState<number>(0);
  const [rogAllyFanStatus, setRogAllyFanStatus] = useState<any>({ 
    cpu_fan: { speed: null, mode: 2, label: 'cpu_fan' }, 
    gpu_fan: { speed: null, mode: 0, label: 'gpu_fan' } 
  });
  const [rogAllyBatteryChargeLimit, setRogAllyBatteryChargeLimit] = useState<number>(100);
  const [defaultTdp, setDefaultTdp] = useState<number>(15);  // Database default (ctdp_min)

  // InputPlumber Integration State
  const [inputPlumberAvailable, setInputPlumberAvailable] = useState<boolean>(false);
  const [inputPlumberModes, setInputPlumberModes] = useState<string[]>([]);
  const [currentInputPlumberMode, setCurrentInputPlumberMode] = useState<string>("default");
  const [inputPlumberDbusMode, setInputPlumberDbusMode] = useState<boolean>(false);

  // Helper function to get cooling profile icon
  const getCoolingProfileIcon = (profile: string) => {
    switch (profile) {
      case 'auto': return <FaCog />;
      case 'quiet': return <FaVolumeOff />;
      case 'moderate': return <FaBalanceScale />;
      case 'aggressive': return <FaFan />;
      default: return <FaCog />;
    }
  };

  // Helper function to get governor icon
  const getGovernorIcon = (governor: string) => {
    switch (governor) {
      case 'powersave': return <FaBatteryThreeQuarters />;
      case 'conservative': return <FaLightbulb />;
      case 'ondemand': return <FaChartBar />;
      case 'schedutil': return <FaCogs />;
      case 'performance': return <FaRocket />;
      default: return <FaCogs />;
    }
  };

  // Helper function to get EPP icon
  const getEppIcon = (epp: string) => {
    switch (epp) {
      case 'power': return <FaBatteryFull />;
      case 'balance_power': return <FaBalanceScale />;
      case 'balance_performance': return <FaChartLine />;
      case 'performance': return <FaRocket />;
      default: return <FaBalanceScale />;
    }
  };

  // Helper function to get GPU mode icon
  const getGpuModeIcon = (mode: string) => {
    switch (mode) {
      case 'battery': return <FaBatteryHalf />;
      case 'auto': return <FaSyncAlt />;
      case 'range': return <FaSlidersH />;
      case 'fixed': return <FaBullseye />;
      default: return <FaSyncAlt />;
    }
  };

  // Cooling Profile Options
  const COOLING_PROFILES = [
    { notchIndex: 0, label: "Auto", value: 0 },
    { notchIndex: 1, label: "Quiet", value: 1 },
    { notchIndex: 2, label: "Balanced", value: 2 },
    { notchIndex: 3, label: "Performance", value: 3 }
  ];

  // CPU Governor Options
  const getGovernorOptions = useCallback(() => {
    // Sort governors logically: power-saving first, performance last
    const govOrder = ['powersave', 'conservative', 'ondemand', 'schedutil', 'performance'];
    
    const sortedAvailableGovs = availableGovernors
      .filter(gov => govOrder.includes(gov))
      .sort((a, b) => govOrder.indexOf(a) - govOrder.indexOf(b));

    return sortedAvailableGovs.map((gov, index) => ({
      notchIndex: index,
      label: `${gov.charAt(0).toUpperCase() + gov.slice(1)}`,
      value: index
    }));
  }, [availableGovernors]);

  // Update system state management
  const [updateState, setUpdateState] = useState<'idle' | 'checking' | 'available' | 'downloading' | 'ready' | 'installing' | 'completed' | 'error'>('idle');
  const [updateMessage, setUpdateMessage] = useState<string>('');
  const [backgroundUpdateStatus, setBackgroundUpdateStatus] = useState<any>(null);
  const [updateInfo, setUpdateInfo] = useState<{currentVersion?: string, latestVersion?: string, downloadUrl?: string} | null>(null);
  const [isCheckingForUpdates, setIsCheckingForUpdates] = useState<boolean>(false);

  // ROG Ally native TDP toggle state with persistence
  const [isRogAllyDeviceDetected, setIsRogAllyDeviceDetected] = useState<boolean>(false);
  const [rogAllyNativeTdpEnabled, setRogAllyNativeTdpEnabledState] = useState<boolean>(() => {
    // Initialize from localStorage as fallback
    const saved = localStorage.getItem('powerdeck_rog_ally_native_tdp');
    return saved ? JSON.parse(saved) : false;
  });
  const [tdpControlMode, setTdpControlMode] = useState<string>("powerdeck");

  // Helper function to update ROG Ally native TDP state with persistence
  const updateRogAllyNativeTdpState = useCallback(async (enabled: boolean, source: string = 'user') => {
    try {
      debug.log(`Updating ROG Ally native TDP state to ${enabled} (source: ${source})`);
      
      // Update local state
      setRogAllyNativeTdpEnabledState(enabled);
      
      // Persist to localStorage
      localStorage.setItem('powerdeck_rog_ally_native_tdp', JSON.stringify(enabled));
      
      // Save to backend
      const success = await setRogAllyNativeTdpEnabled(enabled);
      if (!success) {
        debug.error("Failed to save ROG Ally native TDP state to backend");
      }
      
      // Update TDP control mode
      const newControlMode = await getTdpControlMode();
      setTdpControlMode(newControlMode);
      
      debug.log(`ROG Ally native TDP ${enabled ? 'enabled' : 'disabled'}, control mode: ${newControlMode}`);
      return success;
    } catch (error) {
      debug.error("Error updating ROG Ally native TDP state:", error);
      return false;
    }
  }, []);

  // Universal function to update current profile - UNIFIED SYSTEM
  const updateCurrentProfile = useCallback((updates: Partial<PowerProfile>) => {
    debug.log("updateCurrentProfile called with:", updates);
    setCurrentProfile(prev => {
      const newProfile = { ...prev, ...updates };
      
      // Calculate current profile ID
      const isBaseGame = currentGame.id === "handheld" || currentGame.id === "laptop" || currentGame.id === "desktop";
      const powerSuffix = acPower ? '_ac' : '_battery';
      const profileId = (isBaseGame ? "00000000" : currentGame.id) + powerSuffix;
      
      // ENHANCEMENT: Add game name and metadata to profile for future reference
      const profileWithMetadata = {
        ...newProfile,
        gameName: currentGame.name,
        gameId: currentGame.id,
        profileId: profileId,
        lastUpdated: new Date().toISOString()
      };
      
      debug.log(`Saving profile ${profileId} to backend with metadata:`, profileWithMetadata);
      
      // Save to backend immediately using unified profile ID system
      debug.log(`About to call setGameProfile with profileId: "${profileId}"`);
      try {
        setGameProfile(profileId, profileWithMetadata).then(success => {
          debug.log(`Backend save result for ${profileId}: ${success}`);
        }).catch(error => {
          debug.error(`Failed to save profile ${profileId} to backend:`, error);
          debug.error("Error details:", error.message, error.stack);
        });
      } catch (syncError) {
        debug.error("Synchronous error calling setGameProfile:", syncError);
      }
      
      // Also save to localStorage for compatibility (without metadata to avoid breaking existing code)
      const storageKey = acPower ? 'powerdeck_ac_profile' : 'powerdeck_battery_profile';
      localStorage.setItem(storageKey, JSON.stringify(newProfile));
      debug.log(`Also saved to localStorage: ${storageKey}`);
      
      return newProfile;
    });
  }, [currentGame.id, acPower]);

  // Quiet mode optimization - only apply profile if it has actually changed
  // forceApply: always apply regardless of comparison (for AC/battery switches, game changes, wake from sleep)
  const applyProfileQuiet = useCallback(async (newProfile: PowerProfile, forceApply: boolean = false) => {
    try {
      // Deep comparison of important settings that trigger hardware changes
      // BUT: Skip comparison if forceApply is true (AC/battery switch, game change, etc.)
      if (lastAppliedProfile && !forceApply) {
        const importantSettings = ['tdp', 'cpuBoost', 'cpuCores', 'governor', 'smt', 'epp', 'gpuMode', 'gpuFreqMin', 'gpuFreqMax', 'gpuFreqFixed', 'usbAutosuspend', 'pcieAspm'];
        const hasChanges = importantSettings.some(key => 
          lastAppliedProfile[key as keyof PowerProfile] !== newProfile[key as keyof PowerProfile]
        );
        
        if (!hasChanges) {
          debug.log('Quiet mode: Profile unchanged, skipping hardware application');
          return true;
        }
        
        debug.log('Quiet mode: Profile changed, applying hardware settings');
      } else if (forceApply) {
        debug.log('Quiet mode: Force apply requested (AC/battery switch or game change), applying hardware settings');
      }
      
      const result = await applyProfile(newProfile);
      if (result) {
        setLastAppliedProfile({ ...newProfile });
        debug.log('Quiet mode: Profile applied and cached');
      }
      return result;
    } catch (error) {
      debug.error('Quiet mode: Failed to apply profile:', error);
      return false;
    }
  }, [lastAppliedProfile]);

  // Helper function to normalize profiles by ensuring all required fields are present
  const normalizeProfile = useCallback((profile: any): PowerProfile => {
    return {
      ...profile,
      usbAutosuspend: profile.usbAutosuspend ?? false,
      pcieAspm: profile.pcieAspm ?? false
    };
  }, []);

  // Helper function to sync USB and PCIe settings from profile to state variables and hardware
  const syncUsbPcieSettings = useCallback(async (profile: PowerProfile) => {
    // Sync USB autosuspend setting - handle both true and false values
    const usbSetting = profile.usbAutosuspend ?? false; // Default to false if undefined
    setUsbAutosuspendEnabled(usbSetting);
    if (usbSetting) {
      try {
        await setUsbAutosuspend(true);
        debug.log('Applied USB autosuspend from profile (enabled)');
      } catch (error) {
        debug.error('Failed to apply USB autosuspend from profile:', error);
      }
    } else {
      debug.log('Applied USB autosuspend from profile (disabled) - let OS manage');
    }
    
    // Sync PCIe ASPM setting - handle both true and false values  
    const pcieSetting = profile.pcieAspm ?? false; // Default to false if undefined
    setPcieAspmEnabled(pcieSetting);
    if (pcieSetting) {
      try {
        await setPcieAspmPolicy('powersave');
        debug.log('Applied PCIe ASPM from profile (enabled)');
      } catch (error) {
        debug.error('Failed to apply PCIe ASPM from profile:', error);
      }
    } else {
      debug.log('Applied PCIe ASPM from profile (disabled) - let OS manage');
    }
  }, []);

  // Load device info and initial settings
  useEffect(() => {
    const initializePlugin = async () => {
      try {
        setLoading(true);
        
        // Load device info
        const deviceData = await getDeviceInfo();
        setDeviceInfo(deviceData);
        debug.log(`DeviceInfo loaded:`, deviceData);
        debug.log(`GPU limits from deviceInfo: min=${deviceData?.min_gpu_freq}, max=${deviceData?.max_gpu_freq}`);
        
        // Check if this is a ROG Ally device and load ROG Ally specific info
        if (deviceData?.device_name && (deviceData.device_name.includes('ROG Ally') || deviceData.device_name.includes('RC71L') || deviceData.device_name.includes('RC72L'))) {
          setIsRogAlly(true);
          
          // Check if device is ROG Ally for native TDP toggle
          try {
            debug.log('Calling isRogAllyDevice() function...');
            const isRogAllyCheck = await isRogAllyDevice();
            debug.log(`ROG Ally device check result: ${isRogAllyCheck}`);
            setIsRogAllyDeviceDetected(isRogAllyCheck);
            debug.log(`ROG Ally device detected state set to: ${isRogAllyCheck}`);
            
            if (isRogAllyCheck) {
              // Load ROG Ally native TDP setting with robust error handling and persistence
              debug.log('Loading ROG Ally native TDP setting...');
              try {
                const nativeTdpEnabled = await getRogAllyNativeTdpEnabled();
                debug.log(`Backend ROG Ally native TDP state: ${nativeTdpEnabled}`);
                
                // Check if this differs from localStorage and sync if needed
                const localStorageValue = localStorage.getItem('powerdeck_rog_ally_native_tdp');
                const localState = localStorageValue ? JSON.parse(localStorageValue) : false;
                
                if (nativeTdpEnabled !== localState) {
                  debug.log(`Syncing state mismatch: backend=${nativeTdpEnabled}, localStorage=${localState}`);
                  // Use backend value as source of truth but update localStorage
                  localStorage.setItem('powerdeck_rog_ally_native_tdp', JSON.stringify(nativeTdpEnabled));
                }
                
                setRogAllyNativeTdpEnabledState(nativeTdpEnabled);
                debug.log(`ROG Ally native TDP enabled set to: ${nativeTdpEnabled}`);
                
              } catch (stateError) {
                debug.error('Failed to load ROG Ally native TDP state from backend, using localStorage fallback:', stateError);
                // Fallback to localStorage value if backend fails
                const localStorageValue = localStorage.getItem('powerdeck_rog_ally_native_tdp');
                const fallbackState = localStorageValue ? JSON.parse(localStorageValue) : false;
                setRogAllyNativeTdpEnabledState(fallbackState);
                debug.log(`Using localStorage fallback state: ${fallbackState}`);
              }
              
              // Get current TDP control mode
              try {
                debug.log('Getting TDP control mode...');
                const controlMode = await getTdpControlMode();
                setTdpControlMode(controlMode);
                debug.log(`TDP control mode: ${controlMode}`);
              } catch (modeError) {
                debug.error('Failed to get TDP control mode:', modeError);
                setTdpControlMode("powerdeck"); // Safe fallback
              }
            } else {
              debug.log('Device is not detected as ROG Ally, skipping native TDP setup');
            }
          } catch (error) {
            debug.error('Error in ROG Ally device detection and setup:', error);
            setIsRogAllyDeviceDetected(false);
          }
          try {
            const rogAllyInfo = await getRogAllyDeviceInfo();
            setRogAllyDeviceInfo(rogAllyInfo);
            debug.log(`ROG Ally device info loaded:`, rogAllyInfo);
            
            // Load initial ROG Ally settings
            if (rogAllyInfo?.available_controls?.platform_profiles) {
              const platformProfile = await getRogAllyPlatformProfile();
              setRogAllyPlatformProfile(platformProfile || 'balanced');
            }
            
            if (rogAllyInfo?.available_controls?.thermal_policy) {
              const thermalPolicy = await getRogAllyThermalThrottlePolicy();
              setRogAllyThermalPolicy(thermalPolicy || 0);
            }
            
            if (rogAllyInfo?.available_controls?.fan_control) {
              const fanStatus = await getRogAllyFanStatus();
              setRogAllyFanStatus(fanStatus || { 
                cpu_fan: { speed: null, mode: 2, label: 'cpu_fan' }, 
                gpu_fan: { speed: null, mode: 0, label: 'gpu_fan' } 
              });
            }
            
            if (rogAllyInfo?.available_controls?.power_limits) {
              const powerLimits = await getRogAllyPowerLimits();
              setRogAllyPowerLimits(powerLimits || { fast_limit: null, sustained_limit: null, stapm_limit: null });
            }
            
            if (rogAllyInfo?.available_controls?.battery_charge_limit) {
              const chargeLimit = await getRogAllyBatteryChargeLimit();
              setRogAllyBatteryChargeLimit(chargeLimit || 100);
            }
            
            if (rogAllyInfo?.available_controls?.mcu_powersave) {
              const mcuPowersave = await getRogAllyMcuPowersave();
              setRogAllyMcuPowersave(mcuPowersave !== false);
            }
          } catch (error) {
            debug.error('Failed to load ROG Ally specific info:', error);
          }
        }
        // Load plugin version and check for background updates
        let currentVersion = "unknown";
        try {
          currentVersion = await getCurrentVersion();
          setPluginVersion(currentVersion);
          debug.log(`Plugin version loaded: ${currentVersion}`);
        } catch (error) {
          debug.log("Failed to load plugin version:", error);
        }
        
        // Check background update status
        try {
          const bgUpdateStatus = await getUpdateStatus();
          setBackgroundUpdateStatus(bgUpdateStatus);
          debug.log("Background update status:", bgUpdateStatus);
          
          // If background check found an update, set the button to show it
          if (bgUpdateStatus.update_available && bgUpdateStatus.latest_version) {
            setUpdateState('available');
            setUpdateMessage(`Update available: ${currentVersion} → ${bgUpdateStatus.latest_version}`);
            debug.log(`Background update found: ${currentVersion} -> ${bgUpdateStatus.latest_version}`);
          }
        } catch (error) {
          debug.log("Failed to load background update status:", error);
        }
        // Load TDP limits and default
        const limits = await getTdpLimits();
        setTdpLimits(limits);
        setCustomTdpMin(limits.min);
        setCustomTdpMax(limits.max);
        
        // Get default TDP from processor database (ctdp_min)
        const dbDefaultTdp = await getDefaultTdp();
        setDefaultTdp(dbDefaultTdp);
        
        // Update current profile with device-specific GPU limits
        if (deviceData && deviceData.min_gpu_freq && deviceData.max_gpu_freq) {
          setCurrentProfile(prevProfile => ({
            ...prevProfile,
            gpuFreqMin: deviceData.min_gpu_freq,
            gpuFreqMax: deviceData.max_gpu_freq,
            gpuFreqFixed: Math.floor((deviceData.min_gpu_freq + deviceData.max_gpu_freq) / 2)
          }));
          debug.log(`Updated GPU limits from device info: ${deviceData.min_gpu_freq}-${deviceData.max_gpu_freq} MHz`);
        }
        
        // Load available options
        const governors = await getAvailableGovernors();
        const fanProfiles = await getAvailableFanProfiles();
        setAvailableGovernors(governors);
        setAvailableFanProfiles(fanProfiles);
        
        // Load additional power management settings
        try {
          const usbStatus = await getUsbAutosuspendStatus();
          // Check if any USB devices have autosuspend enabled (for info only)
          const anyEnabled = Object.values(usbStatus).some(enabled => enabled);
          debug.log(`USB autosuspend status: ${anyEnabled ? 'some devices enabled' : 'disabled'}`);
        } catch (error) {
          debug.log("USB autosuspend not supported");
        }
        
        // Load per-game profiles setting
        try {
          const perGameEnabled = await getPerGameProfilesEnabled();
          setPerGameProfilesEnabledState(perGameEnabled);
        } catch (error) {
          debug.log("Per-game profiles not supported");
        }
        
        // Initialize advanced power management settings with defaults
        try {
          // WiFi power save: enabled by default - apply immediately
          setWifiPowerSaveEnabled(true);
          await setWifiPowerSave(true);
          debug.log("WiFi power save enabled by default");
          
          // USB autosuspend: disabled by default - don't apply
          setUsbAutosuspendEnabled(false);
          debug.log("USB autosuspend disabled by default (OS managed)");
          
          // PCIe ASPM: disabled by default - don't apply  
          setPcieAspmEnabled(false);
          debug.log("PCIe ASPM disabled by default (OS managed)");
        } catch (error) {
          debug.log("Advanced power management initialization failed:", error);
        }

        // Initialize InputPlumber integration
        try {
          const ipStatus = await getInputPlumberStatus();
          setInputPlumberAvailable(ipStatus.available || false);
          setCurrentInputPlumberMode(ipStatus.current_mode || "default");
          setInputPlumberDbusMode(ipStatus.dbus_mode || false);
          debug.log(`InputPlumber status: available=${ipStatus.available}, mode=${ipStatus.current_mode}, dbus=${ipStatus.dbus_mode}`);
          
          if (ipStatus.available) {
            const modes = await getInputPlumberModes();
            setInputPlumberModes(modes || []);
            debug.log(`InputPlumber modes loaded: ${modes?.length || 0} modes`);
          }
        } catch (error) {
          debug.log("InputPlumber not available or failed to initialize:", error);
          setInputPlumberAvailable(false);
        }
        
        // Load device classification for proper profile naming
        try {
          // const classification = await getDeviceClassification();
          // setDeviceClassification(classification);
          // debug.log(`Device classified as: ${classification}`);
        } catch (error) {
          debug.log("Device classification not supported, using default");
          setDeviceClassification("Handheld"); // Safe fallback for gaming devices
        }
        
        // Check AC power status first to determine initial profile ID
        const acStatus = await getAcPowerStatus();
        setAcPower(acStatus);
        setActiveProfile(acStatus ? 'ac' : 'battery');
        
        // IMPROVED INITIALIZATION: Check if a specific game is currently running
        let initialGameInfo = { id: "handheld", name: "Handheld" }; // Default fallback
        let initialProfileId = acStatus ? "00000000_ac" : "00000000_battery"; // Default fallback
        
        // Try to detect current game if per-game profiles are enabled
        const perGameEnabled = true; // Default to enabled for detection
        if (perGameEnabled) {
          try {
            const currentGameInfo = getCurrentGameInfo();
            if (currentGameInfo && currentGameInfo.id !== "default" && currentGameInfo.id !== "00000000") {
              // Real game detected during initialization
              initialGameInfo = currentGameInfo;
              initialProfileId = acStatus ? `${currentGameInfo.id}_ac` : `${currentGameInfo.id}_battery`;
              debug.log(`Game detected during initialization: ${currentGameInfo.name} (${currentGameInfo.id})`);
              debug.log(`Will load profile: ${initialProfileId}`);
            } else {
              debug.log("No specific game detected during initialization, using handheld profile");
            }
          } catch (error) {
            debug.log("Game detection failed during initialization, using handheld profile:", error);
          }
        }
        
        // Set initial game and profile ID
        setCurrentGame(initialGameInfo);
        setCurrentProfileId(initialProfileId);
        
        // Try to load profile from backend first
        let profileToLoad = null;
        try {
          profileToLoad = await getGameProfile(initialProfileId);
          debug.log(`Loaded profile from backend for ${initialProfileId}:`, profileToLoad);
        } catch (error) {
          debug.log(`No profile in backend for ${initialProfileId}, using defaults`);
        }
        
        // Fallback to localStorage if backend doesn't have the profile
        if (!profileToLoad) {
          const savedAcProfile = localStorage.getItem('powerdeck_ac_profile');
          const savedBatteryProfile = localStorage.getItem('powerdeck_battery_profile');
          
          if (acStatus && savedAcProfile) {
            profileToLoad = JSON.parse(savedAcProfile);
          } else if (!acStatus && savedBatteryProfile) {
            profileToLoad = JSON.parse(savedBatteryProfile);
          } else {
            // Use default profile based on power mode with database TDP values and device GPU limits
            const gpuMin = deviceData?.min_gpu_freq || 400;
            const gpuMax = deviceData?.max_gpu_freq || 1600;
            const gpuFixed = Math.floor((gpuMin + gpuMax) / 2);
            
            profileToLoad = acStatus ? {
              tdp: dbDefaultTdp, cpuBoost: true, cpuCores: 8, governor: "performance",
              fanProfile: "moderate", smt: true, epp: "performance", gpuMode: "auto",
              gpuFreqMin: gpuMin, gpuFreqMax: gpuMax, gpuFreqFixed: gpuFixed,
              usbAutosuspend: false, pcieAspm: false // Default to disabled for stability
            } : {
              tdp: dbDefaultTdp, cpuBoost: false, cpuCores: 4, governor: "powersave",
              fanProfile: "quiet", smt: true, epp: "power", gpuMode: "battery",
              gpuFreqMin: gpuMin, gpuFreqMax: Math.floor(gpuMax * 0.8), gpuFreqFixed: Math.floor(gpuFixed * 0.8),
              usbAutosuspend: false, pcieAspm: false // Default to disabled for stability
            };
          }
          
          // Save the fallback profile to backend for future use with metadata
          try {
            const fallbackProfileWithMetadata = {
              ...profileToLoad,
              gameName: initialGameInfo.name,
              gameId: initialGameInfo.id,
              profileId: initialProfileId,
              lastUpdated: new Date().toISOString()
            };
            await setGameProfile(initialProfileId, fallbackProfileWithMetadata);
            debug.log(`Saved fallback profile to backend with metadata for ${initialProfileId}`);
          } catch (error) {
            debug.error("Failed to save fallback profile to backend:", error);
          }
        }
        
        // Set the current profile and apply it - normalize first to ensure all fields present
        const normalizedProfile = normalizeProfile(profileToLoad);
        setCurrentProfile(normalizedProfile);
        await syncUsbPcieSettings(normalizedProfile);
        await applyProfileQuiet(normalizedProfile);
        
        // Save the normalized profile back to ensure it has all current fields with metadata
        try {
          const normalizedProfileWithMetadata = {
            ...normalizedProfile,
            gameName: initialGameInfo.name,
            gameId: initialGameInfo.id,
            profileId: initialProfileId,
            lastUpdated: new Date().toISOString()
          };
          await setGameProfile(initialProfileId, normalizedProfileWithMetadata);
          debug.log('Saved normalized profile with USB/PCIe fields and metadata');
        } catch (error) {
          debug.error("Failed to save normalized profile:", error);
        }
        
        // Frontend-backend coordination: Check if frontend detects a different game than default
        try {
          setTimeout(async () => {
            await updateBackendGameDetection();
          }, 2000); // Give Router time to populate after UI loads
        } catch (error) {
          debug.error("Frontend-backend game coordination failed:", error);
        }
        
      } catch (err) {
        setError(`Initialization failed: ${err}`);
      } finally {
        setLoading(false);
      }
    };
    
    initializePlugin();
  }, []);

  // Unified monitoring system - combines AC power and game detection into single 30s poll
  useEffect(() => {
    debug.log("Starting unified monitoring system (AC power + game detection) with 30s polling");
    
    const unifiedMonitoringInterval = setInterval(async () => {
      try {
        // Check AC power status
        const newAcPower = await getAcPowerStatus();
        let acPowerChanged = newAcPower !== acPower;
        
        // Check game status (only if per-game profiles enabled)
        let gameInfo = null;
        let gameChanged = false;
        
        if (perGameProfilesEnabled) {
          gameInfo = getCurrentGameInfo();
          
          // IMPROVED GAME DETECTION LOGIC:
          // Only consider it a "game change" if:
          // 1. We detect a new specific game that's different from current
          // 2. We consistently detect "default" for multiple checks (real game exit)
          // Don't immediately switch to default on first "default" detection
          
          if (gameInfo && gameInfo.id !== "default" && gameInfo.id !== "00000000") {
            // Real game detected - check if it's different from current
            if (gameInfo.id !== currentGame.id || gameInfo.name !== currentGame.name) {
              gameChanged = true;
              debug.log(`Real game change detected: ${currentGame.name} (${currentGame.id}) → ${gameInfo.name} (${gameInfo.id})`);
            }
            
            // Frontend-backend coordination: Update backend with real game when detected
            await updateBackendGameDetection();
          } else {
            // Router reports "default" - this could be:
            // 1. Game actually exited (should switch to handheld profile)
            // 2. Temporary Router inconsistency (should NOT switch profiles)
            
            // Only treat as "game exited" if current game was not already a base game
            const currentIsBaseGame = currentGame.id === "handheld" || currentGame.id === "laptop" || currentGame.id === "desktop";
            if (!currentIsBaseGame) {
              // We had a specific game before, now Router says "default"
              // Add a small delay check to avoid false positives from Router inconsistency
              debug.log(`Router reports default, but we had game ${currentGame.name}. Waiting to confirm game exit...`);
              
              // Wait 2 seconds and check again
              setTimeout(async () => {
                const confirmGameInfo = getCurrentGameInfo();
                if (confirmGameInfo && (confirmGameInfo.id === "default" || confirmGameInfo.id === "00000000")) {
                  debug.log("Game exit confirmed after delay check, switching to handheld profile");
                  // Game actually exited, switch to handheld
                  setCurrentGame({ id: "handheld", name: "Handheld" });
                  
                  // Load handheld profile
                  const handlerProfileId = newAcPower ? "00000000_ac" : "00000000_battery";
                  try {
                    const defaultProfile = await getGameProfile(handlerProfileId);
                    if (defaultProfile) {
                      debug.log(`Loading default profile after confirmed game exit: ${handlerProfileId}`);
                      const normalizedProfile = normalizeProfile(defaultProfile);
                      setCurrentProfile(normalizedProfile);
                      await syncUsbPcieSettings(normalizedProfile);
                      // FORCE APPLY: Game exit, switching profiles - always re-apply settings
                      await applyProfileQuiet(normalizedProfile, true);
                    }
                  } catch (error) {
                    debug.error("Failed to load default profile after game exit:", error);
                  }
                } else {
                  debug.log("Game still detected after delay check, keeping current profile");
                }
              }, 2000);
            }
            // If current game is already a base game, no action needed
          }
        }
        
        // Only proceed with profile switching if AC power actually changed or real game change detected
        if (acPowerChanged || gameChanged) {
          debug.log(`State changes detected: AC=${acPowerChanged ? `${acPower}→${newAcPower}` : 'unchanged'}, Game=${gameChanged ? `${currentGame.name}→${gameInfo?.name}` : 'unchanged'}`);
          
          // Calculate current profile ID for saving
          const currentIsBaseGame = currentGame.id === "handheld" || currentGame.id === "laptop" || currentGame.id === "desktop";
          const currentProfileId = (currentIsBaseGame ? "00000000" : currentGame.id) + (acPower ? '_ac' : '_battery');
          
          // Save current profile before any changes with metadata
          try {
            const currentProfileWithMetadata = {
              ...currentProfile,
              gameName: currentGame.name,
              gameId: currentGame.id,
              profileId: currentProfileId,
              lastUpdated: new Date().toISOString()
            };
            await setGameProfile(currentProfileId, currentProfileWithMetadata);
            debug.log(`Saved current profile with metadata: ${currentProfileId}`);
          } catch (error) {
            debug.error("Failed to save current profile:", error);
          }
          
          // Update states
          if (acPowerChanged) {
            setAcPower(newAcPower);
            setActiveProfile(newAcPower ? 'ac' : 'battery');
          }
          if (gameChanged && gameInfo) {
            setCurrentGame(gameInfo);
          }
          
          // Calculate new profile ID
          const newAcState = acPowerChanged ? newAcPower : acPower;
          const newGameId = gameChanged && gameInfo ? gameInfo.id : currentGame.id;
          const newIsBaseGame = newGameId === "handheld" || newGameId === "laptop" || newGameId === "desktop";
          const newProfileId = (newIsBaseGame ? "00000000" : newGameId) + (newAcState ? '_ac' : '_battery');
          
          setCurrentProfileId(newProfileId);
          
          // Load and apply new profile
          try {
            const newProfile = await getGameProfile(newProfileId);
            if (newProfile) {
              debug.log(`Loaded profile for new state: ${newProfileId}`, newProfile);
              const normalizedProfile = normalizeProfile(newProfile);
              setCurrentProfile(normalizedProfile);
              await syncUsbPcieSettings(normalizedProfile);
              // FORCE APPLY: AC/battery or game changed, always re-apply settings to hardware
              await applyProfileQuiet(normalizedProfile, true);
              
              // Save normalized profile if it was missing fields
              if (normalizedProfile.usbAutosuspend !== newProfile.usbAutosuspend || 
                  normalizedProfile.pcieAspm !== newProfile.pcieAspm) {
                try {
                  await setGameProfile(newProfileId, normalizedProfile);
                  debug.log('Updated profile with missing USB/PCIe fields');
                } catch (error) {
                  debug.error('Failed to update profile with missing fields:', error);
                }
              }
            } else {
              debug.log(`No profile found for ${newProfileId}, creating default`);
              // Create appropriate default based on power state
              const defaultProfile = newAcState ? {
                ...currentProfile, tdp: defaultTdp, cpuBoost: true, governor: "performance",
                usbAutosuspend: false, pcieAspm: false // Default to disabled for stability
              } : {
                ...currentProfile, tdp: defaultTdp, cpuBoost: false, governor: "powersave",
                usbAutosuspend: false, pcieAspm: false // Default to disabled for stability
              };
              
              // Add metadata to default profile
              const defaultProfileWithMetadata = {
                ...defaultProfile,
                gameName: newGameId === currentGame.id ? currentGame.name : (gameInfo ? gameInfo.name : "Handheld"),
                gameId: newGameId,
                profileId: newProfileId,
                lastUpdated: new Date().toISOString()
              };
              
              setCurrentProfile(defaultProfile);
              await syncUsbPcieSettings(defaultProfile);
              // FORCE APPLY: AC/battery or game changed, always re-apply settings to hardware
              await applyProfileQuiet(defaultProfile, true);
              await setGameProfile(newProfileId, defaultProfileWithMetadata);
              debug.log(`Created and saved default profile with metadata: ${newProfileId}`);
            }
          } catch (error) {
            debug.error(`Failed to load/apply profile for new state:`, error);
          }
          
          if (gameChanged && gameInfo) {
            debug.log(`Unified state update complete: Now ${acPowerChanged ? 'on ' + (newAcPower ? 'AC' : 'battery') + ' and ' : ''}playing ${gameInfo.name}`);
          } else if (acPowerChanged) {
            debug.log(`Unified state update complete: Switched to ${newAcPower ? 'AC' : 'battery'} power`);
          }
        }
      } catch (error) {
        debug.error('Unified monitoring failed:', error);
      }
    }, 7500); // Single 7.5-second interval for all monitoring - balance of responsiveness vs efficiency

    // Get initial states
    getAcPowerStatus().then(acStatus => {
      setAcPower(acStatus);
      setActiveProfile(acStatus ? 'ac' : 'battery');
    }).catch(debug.error);
    
    if (perGameProfilesEnabled) {
      // Initial game detection using frontend Router  
      const initialGameInfo = getCurrentGameInfo();
      if (initialGameInfo && initialGameInfo.id !== "default") {
        debug.log(`Initial game detected: ${initialGameInfo.name} (${initialGameInfo.id})`);
        setCurrentGame(initialGameInfo);
      }
    }

    return () => {
      debug.log("Stopping unified monitoring system");
      clearInterval(unifiedMonitoringInterval);
    };
  }, [perGameProfilesEnabled, currentGame.id, currentGame.name, currentProfile, acPower]);

  // Helper function to apply hardware setting and update profile
  const applySettingAndUpdateProfile = useCallback(async (
    settingFunction: () => Promise<boolean>,
    profileUpdate: Partial<PowerProfile>,
    settingName: string
  ) => {
    try {
      const success = await settingFunction();
      if (success) {
        updateCurrentProfile(profileUpdate);
      } else {
        setError(`Failed to apply ${settingName}`);
      }
    } catch (err) {
      setError(`Error applying ${settingName}: ${err}`);
    }
  }, [updateCurrentProfile]);

  // Hardware control functions
  const handleTdpChange = useCallback(async (value: number) => {
    await applySettingAndUpdateProfile(
      () => setTdp(value),
      { tdp: value },
      'TDP setting'
    );
  }, [applySettingAndUpdateProfile]);

  const handleCpuBoostChange = useCallback(async (enabled: boolean) => {
    await applySettingAndUpdateProfile(
      () => setCpuBoost(enabled),
      { cpuBoost: enabled },
      'CPU boost setting'
    );
  }, [applySettingAndUpdateProfile]);

  const handleCpuCoresChange = useCallback(async (cores: number) => {
    await applySettingAndUpdateProfile(
      () => setCpuCores(cores),
      { cpuCores: cores },
      'CPU cores setting'
    );
  }, [applySettingAndUpdateProfile]);

  const handleSmtChange = useCallback(async (enabled: boolean) => {
    const maxCores = deviceInfo?.max_cpu_cores || 16;
    const currentCores = currentProfile.cpuCores;
    
    // When disabling SMT, ensure CPU cores don't exceed physical cores
    // When enabling SMT, allow access to logical cores
    let adjustedCores = currentCores;
    if (!enabled && currentCores > Math.floor(maxCores / 2)) {
      adjustedCores = Math.floor(maxCores / 2);
    }
    
    await applySettingAndUpdateProfile(
      () => setSmt(enabled),
      { smt: enabled, cpuCores: adjustedCores },
      'SMT (Simultaneous Multithreading) setting'
    );
  }, [applySettingAndUpdateProfile, deviceInfo?.max_cpu_cores, currentProfile.cpuCores]);

  const handleGovernorChange = useCallback(async (value: string) => {
    await applySettingAndUpdateProfile(
      () => setGovernor(value),
      { governor: value },
      'CPU governor'
    );
  }, [applySettingAndUpdateProfile]);

  const handleFanProfileChange = useCallback(async (value: string) => {
    await applySettingAndUpdateProfile(
      () => setFanProfile(value),
      { fanProfile: value },
      'fan profile'
    );
  }, [applySettingAndUpdateProfile]);

  const handleEppChange = useCallback(async (value: string) => {
    await applySettingAndUpdateProfile(
      () => setEpp(value),
      { epp: value },
      'EPP setting'
    );
  }, [applySettingAndUpdateProfile]);

  const handleGpuModeChange = useCallback(async (value: string) => {
    await applySettingAndUpdateProfile(
      () => setGpuMode(value),
      { gpuMode: value },
      'GPU mode'
    );
  }, [applySettingAndUpdateProfile]);

  const handleGpuFrequencyChange = useCallback(async (min: number, max: number) => {
    // Guard against min=max for Intel GPUs (they don't support identical min/max)
    let adjustedMin = min;
    let adjustedMax = max;
    
    if (adjustedMin >= adjustedMax) {
      // Ensure at least 50MHz difference for Intel GPU compatibility
      const deviceMin = deviceInfo?.min_gpu_freq || 200;
      const deviceMax = deviceInfo?.max_gpu_freq || 3000;
      
      // If max is at device limit, adjust min down
      if (adjustedMax >= deviceMax - 50) {
        adjustedMax = deviceMax;
        adjustedMin = Math.max(adjustedMax - 50, deviceMin);
      } else {
        // Otherwise adjust max up
        adjustedMax = Math.min(adjustedMin + 50, deviceMax);
      }
      
      // Final safety check
      if (adjustedMin >= adjustedMax) {
        adjustedMin = deviceMin;
        adjustedMax = Math.min(deviceMin + 50, deviceMax);
      }
    }
    
    await applySettingAndUpdateProfile(
      () => setGpuFrequency(adjustedMin, adjustedMax),
      { gpuFreqMin: adjustedMin, gpuFreqMax: adjustedMax },
      'GPU frequency'
    );
  }, [applySettingAndUpdateProfile, deviceInfo]);

  const handleGpuFixedFrequencyChange = useCallback(async (fixed: number) => {
    // For Intel GPUs, set min and max close to the fixed value but not identical
    const deviceMin = deviceInfo?.min_gpu_freq || 200;
    const deviceMax = deviceInfo?.max_gpu_freq || 3000;
    
    // Clamp fixed frequency to device limits first
    const clampedFixed = Math.max(deviceMin, Math.min(fixed, deviceMax));
    
    // Calculate range around the fixed frequency
    let minFreq = Math.max(clampedFixed - 25, deviceMin);
    let maxFreq = Math.min(clampedFixed + 25, deviceMax);
    
    // Additional guard: ensure min < max and respect device limits
    if (minFreq >= maxFreq) {
      if (clampedFixed <= deviceMin + 25) {
        // Near minimum limit, use minimum range
        minFreq = deviceMin;
        maxFreq = Math.min(deviceMin + 50, deviceMax);
      } else if (clampedFixed >= deviceMax - 25) {
        // Near maximum limit, use maximum range
        maxFreq = deviceMax;
        minFreq = Math.max(deviceMax - 50, deviceMin);
      } else {
        // Fallback: center the range
        minFreq = Math.max(clampedFixed - 25, deviceMin);
        maxFreq = Math.min(clampedFixed + 25, deviceMax);
      }
    }
    
    await applySettingAndUpdateProfile(
      () => setGpuFrequency(minFreq, maxFreq),
      { gpuFreqFixed: clampedFixed },
      'GPU fixed frequency'
    );
  }, [applySettingAndUpdateProfile, deviceInfo]);

  // Advanced Power Management Handlers
  const handleWifiPowerSaveChange = useCallback(async (enabled: boolean) => {
    setWifiPowerSaveEnabled(enabled);
    if (enabled) {
      // Only apply WiFi power save when enabled
      try {
        await setWifiPowerSave(true);
        debug.log('WiFi power save enabled');
      } catch (error) {
        debug.error('Failed to enable WiFi power save:', error);
      }
    }
    // When disabled, don't change anything - let OS manage
  }, []);

  const handleUsbAutosuspendChange = useCallback(async (enabled: boolean) => {
    setUsbAutosuspendEnabled(enabled);
    
    // Update the current profile with the new USB autosuspend setting
    const updatedProfile = { ...currentProfile, usbAutosuspend: enabled };
    setCurrentProfile(updatedProfile);
    
    // Save the updated profile immediately
    try {
      await setGameProfile(currentProfileId, updatedProfile);
      debug.log(`USB autosuspend ${enabled ? 'enabled' : 'disabled'} and saved to profile ${currentProfileId}`);
    } catch (error) {
      debug.error('Failed to save USB autosuspend setting to profile:', error);
    }
    
    if (enabled) {
      // Only apply USB autosuspend when enabled
      try {
        await setUsbAutosuspend(true);
        debug.log('USB autosuspend applied to hardware');
      } catch (error) {
        debug.error('Failed to apply USB autosuspend to hardware:', error);
      }
    }
    // When disabled, don't change anything - let OS manage
  }, [currentProfile, currentProfileId]);

  const handlePcieAsmpChange = useCallback(async (enabled: boolean) => {
    setPcieAspmEnabled(enabled);
    
    // Update the current profile with the new PCIe ASMP setting
    const updatedProfile = { ...currentProfile, pcieAspm: enabled };
    setCurrentProfile(updatedProfile);
    
    // Save the updated profile immediately
    try {
      await setGameProfile(currentProfileId, updatedProfile);
      debug.log(`PCIe ASPM ${enabled ? 'enabled' : 'disabled'} and saved to profile ${currentProfileId}`);
    } catch (error) {
      debug.error('Failed to save PCIe ASPM setting to profile:', error);
    }
    
    if (enabled) {
      // Only apply PCIe ASPM when enabled  
      try {
        await setPcieAspmPolicy('powersave');
        debug.log('PCIe ASPM applied to hardware (powersave policy)');
      } catch (error) {
        debug.error('Failed to apply PCIe ASPM to hardware:', error);
      }
    }
    // When disabled, don't change anything - let OS manage
  }, [currentProfile, currentProfileId]);

  if (loading) {
    return (
      <PanelSection title="PowerDeck">
        <PanelSectionRow>
          <div style={{ padding: "20px", textAlign: "center" }}>
            Loading PowerDeck...
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (error) {
    return (
      <PanelSection title="PowerDeck">
        <PanelSectionRow>
          <div style={{ padding: "20px", color: "#ff6b6b" }}>
            Error: {error}
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <div>
      {/* Device Status Section */}
      <PanelSection title="Device Status">
        <PanelSectionRow>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%', padding: '0 4px' }}>
            {/* Device Info */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <span style={{ fontSize: '0.85em', color: '#aaaaaa' }}>Device</span>
              <span style={{ fontSize: '0.85em', color: '#ffffff', paddingLeft: '12px' }}>
                {deviceInfo ? deviceInfo.device_name : 'Unknown'}
              </span>
            </div>
            
            {/* Power Status */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <span style={{ fontSize: '0.85em', color: '#aaaaaa' }}>Power</span>
              <span style={{ 
                fontSize: '0.85em', 
                color: acPower ? '#4CAF50' : '#FF9800', 
                paddingLeft: '12px'
              }}>
                {acPower ? 'AC Connected' : 'On Battery'}
              </span>
            </div>
            
            {/* Active Profile */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <span style={{ fontSize: '0.85em', color: '#aaaaaa' }}>Profile</span>
              <span style={{ 
                fontSize: '0.85em', 
                color: '#ffffff', 
                paddingLeft: '12px',
                wordBreak: 'break-word',
                lineHeight: '1.2'
              }}>
                {perGameProfilesEnabled ? (() => {
                  // Show frontend-detected game name if available, otherwise backend game name
                  const frontendGame = getCurrentGameInfo();
                  if (frontendGame.id !== "default" && frontendGame.name !== "Default") {
                    return frontendGame.name;
                  }
                  return currentGame.name;
                })() : deviceClassification}
              </span>
            </div>
          </div>
        </PanelSectionRow>
      </PanelSection>

      {/* Cooling Profile Section - Only show if device has fan control AND not ROG Ally */}
      {deviceInfo?.has_fan_control && !isRogAlly && (
        <PanelSection title="Cooling Profile">
          <PanelSectionRow>
            <SliderWithIcons
              label=""
              value={(() => {
                const profile = currentProfile.fanProfile || "quiet";
                const profiles = ["auto", "quiet", "moderate", "aggressive"];
                return profiles.indexOf(profile) >= 0 ? profiles.indexOf(profile) : 0;
              })()}
              min={0}
              max={3}
              step={1}
              icons={[<FaCog />, <FaVolumeOff />, <FaBalanceScale />, <FaFan />]}
              onChange={(value) => {
                const profiles = ["auto", "quiet", "moderate", "aggressive"];
                const selectedProfile = profiles[value] || "auto";
                handleFanProfileChange(selectedProfile);
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
              <span style={{ color: '#00d4ff', fontSize: '1em' }}>
                {getCoolingProfileIcon(currentProfile.fanProfile || "auto")}
              </span>
              <span>
                {(() => {
                  const profile = currentProfile.fanProfile || "auto";
                  const descriptions = {
                    "auto": "System Managed",
                    "quiet": "Quiet Operation", 
                    "moderate": "Balanced Cooling",
                    "aggressive": "Aggressive Cooling"
                  };
                  return descriptions[profile as keyof typeof descriptions] || "System Managed";
                })()}
              </span>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* ROG Ally Fan Control Section - Replaces generic cooling for ROG Ally */}
      {isRogAlly && rogAllyDeviceInfo?.available_controls?.fan_control && (
        <PanelSection title="Fan Control">
          <PanelSectionRow>
            <SliderWithIcons
              label="CPU Fan Mode"
              value={rogAllyFanStatus?.cpu_fan?.mode || 2}
              min={0}
              max={3}
              step={1}
              icons={[<FaStopCircle />, <FaVolumeOff />, <FaBalanceScale />, <FaFan />]}
              onChange={async (value) => {
                const newFanStatus = {
                  ...rogAllyFanStatus,
                  cpu_fan: { ...rogAllyFanStatus.cpu_fan, mode: value }
                };
                setRogAllyFanStatus(newFanStatus);
                try {
                  await setRogAllyFanModeBackend(0, value); // CPU fan ID is 0
                  debug.log(`ROG Ally CPU fan mode set to: ${value}`);
                } catch (error) {
                  debug.error("Failed to set ROG Ally CPU fan mode:", error);
                }
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <SliderWithIcons
              label="GPU Fan Mode"
              value={rogAllyFanStatus?.gpu_fan?.mode || 0}
              min={0}
              max={3}
              step={1}
              icons={[<FaStopCircle />, <FaVolumeOff />, <FaBalanceScale />, <FaFan />]}
              onChange={async (value) => {
                const newFanStatus = {
                  ...rogAllyFanStatus,
                  gpu_fan: { ...rogAllyFanStatus.gpu_fan, mode: value }
                };
                setRogAllyFanStatus(newFanStatus);
                try {
                  await setRogAllyFanModeBackend(1, value); // GPU fan ID is 1
                  debug.log(`ROG Ally GPU fan mode set to: ${value}`);
                } catch (error) {
                  debug.error("Failed to set ROG Ally GPU fan mode:", error);
                }
              }}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* TDP Control Section - Hidden on ROG Ally (use Platform Profiles instead) */}
      {(() => {
        const shouldShow = !(isRogAllyDeviceDetected && rogAllyNativeTdpEnabled);
        debug.log(`TDP Control visibility: isRogAllyDeviceDetected=${isRogAllyDeviceDetected}, rogAllyNativeTdpEnabled=${rogAllyNativeTdpEnabled}, shouldShow=${shouldShow}`);
        return shouldShow;
      })() && (
        <PanelSection title="TDP Control">
        <DebouncedSlider
          label="TDP"
          value={currentProfile.tdp}
          min={showAdvancedTdp ? customTdpMin : tdpLimits.min}
          max={showAdvancedTdp ? customTdpMax : tdpLimits.max}
          step={1}
          onChange={() => {}} // Handle immediate visual updates
          onChangeEnd={handleTdpChange} // Handle actual setting application
          suffix="W"
        />
        <PanelSectionRow>
          <ToggleField
            label="Custom TDP Range"
            checked={showAdvancedTdp}
            onChange={setShowAdvancedTdp}
          />
        </PanelSectionRow>
        {showAdvancedTdp && (
          <>
            <DebouncedSlider
              label="TDP Min"
              value={customTdpMin}
              min={tdpLimits.min}
              max={customTdpMax}
              step={1}
              onChange={setCustomTdpMin}
              onChangeEnd={(value) => {
                if (currentProfile.tdp < value) {
                  handleTdpChange(value);
                }
              }}
              suffix="W"
            />
            <DebouncedSlider
              label="TDP Max"
              value={customTdpMax}
              min={customTdpMin}
              max={tdpLimits.max}
              step={1}
              onChange={setCustomTdpMax}
              onChangeEnd={(value) => {
                if (currentProfile.tdp > value) {
                  handleTdpChange(value);
                }
              }}
              suffix="W"
            />
          </>
        )}
      </PanelSection>
      )}

      {/* ROG Ally Platform Profile Section - High priority placement */}
      {isRogAlly && rogAllyDeviceInfo?.available_controls?.platform_profiles && (
        <PanelSection title="Platform Profile">
          <PanelSectionRow>
            <SliderWithIcons
              label=""
              value={(() => {
                const profiles = ["power-saver", "balanced", "performance"];
                return profiles.indexOf(rogAllyPlatformProfile) >= 0 ? profiles.indexOf(rogAllyPlatformProfile) : 1;
              })()}
              min={0}
              max={2}
              step={1}
              icons={[<FaBatteryFull />, <FaBalanceScale />, <FaRocket />]}
              onChange={async (value) => {
                const profiles = ["power-saver", "balanced", "performance"];
                const selectedProfile = profiles[value] || "balanced";
                setRogAllyPlatformProfile(selectedProfile);
                try {
                  await setRogAllyPlatformProfileBackend(selectedProfile);
                  debug.log(`ROG Ally platform profile set to: ${selectedProfile}`);
                } catch (error) {
                  debug.error("Failed to set ROG Ally platform profile:", error);
                }
              }}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* ROG Ally Thermal Management Section - After Platform Profile */}
      {isRogAlly && rogAllyDeviceInfo?.available_controls?.thermal_policy && (
        <PanelSection title="Thermal Management">
          <PanelSectionRow>
            <SliderWithIcons
              label="Thermal Policy"
              value={rogAllyThermalPolicy}
              min={0}
              max={3}
              step={1}
              icons={[<FaThermometerHalf />, <FaBalanceScale />, <FaFire />, <FaRocket />]}
              onChange={async (value) => {
                setRogAllyThermalPolicy(value);
                try {
                  await setRogAllyThermalThrottlePolicyBackend(value);
                  debug.log(`ROG Ally thermal policy set to: ${value}`);
                } catch (error) {
                  debug.error("Failed to set ROG Ally thermal policy:", error);
                }
              }}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* CPU Control Section - Hidden when ROG Ally native TDP is enabled */}
      {(() => {
        const shouldShow = !(isRogAllyDeviceDetected && rogAllyNativeTdpEnabled);
        debug.log(`CPU Control visibility: isRogAllyDeviceDetected=${isRogAllyDeviceDetected}, rogAllyNativeTdpEnabled=${rogAllyNativeTdpEnabled}, shouldShow=${shouldShow}`);
        return shouldShow;
      })() && (
      <PanelSection title="CPU Control">
        <DebouncedSlider
          label="CPU Cores"
          value={currentProfile.cpuCores}
          min={1}
          max={(() => {
            const maxCores = deviceInfo?.max_cpu_cores || 16;
            // When SMT is disabled, show physical cores (half of logical cores)
            // When SMT is enabled, show logical cores (full count)
            return currentProfile.smt ? maxCores : Math.floor(maxCores / 2);
          })()}
          step={1}
          onChange={() => {}} // Handle immediate visual updates
          onChangeEnd={handleCpuCoresChange} // Handle actual setting application
        />
        <PanelSectionRow>
          <ToggleField
            label="CPU Boost"
            checked={currentProfile.cpuBoost}
            onChange={handleCpuBoostChange}
          />
        </PanelSectionRow>
        {deviceInfo?.supports_smt && (
          <PanelSectionRow>
            <ToggleField
              label="SMT (Hyperthreading)"
              description="Enables/disables simultaneous multithreading for power efficiency."
              checked={currentProfile.smt}
              onChange={handleSmtChange}
            />
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <SliderWithIcons
            label="CPU Governor"
            value={(() => {
              const gov = currentProfile.governor || "powersave";
              const govOrder = ['powersave', 'conservative', 'ondemand', 'schedutil', 'performance'];
              const sortedAvailableGovs = availableGovernors
                .filter(g => govOrder.includes(g))
                .sort((a, b) => govOrder.indexOf(a) - govOrder.indexOf(b));
              const govIndex = sortedAvailableGovs.indexOf(gov);
              return Math.max(0, govIndex);
            })()}
            min={0}
            max={(() => {
              const govOrder = ['powersave', 'conservative', 'ondemand', 'schedutil', 'performance'];
              const sortedAvailableGovs = availableGovernors
                .filter(g => govOrder.includes(g))
                .sort((a, b) => govOrder.indexOf(a) - govOrder.indexOf(b));
              return sortedAvailableGovs.length - 1;
            })()}
            step={1}
            icons={(() => {
              const govOrder = ['powersave', 'conservative', 'ondemand', 'schedutil', 'performance'];
              const iconMap: { [key: string]: React.ReactNode } = {
                'powersave': <FaBatteryThreeQuarters />,
                'conservative': <FaLightbulb />,
                'ondemand': <FaChartBar />,
                'schedutil': <FaCogs />,
                'performance': <FaRocket />
              };
              const sortedAvailableGovs = availableGovernors
                .filter(g => govOrder.includes(g))
                .sort((a, b) => govOrder.indexOf(a) - govOrder.indexOf(b));
              return sortedAvailableGovs.map(gov => iconMap[gov] || <FaCogs />);
            })()}
            onChange={(value) => {
              const govOrder = ['powersave', 'conservative', 'ondemand', 'schedutil', 'performance'];
              const sortedAvailableGovs = availableGovernors
                .filter(g => govOrder.includes(g))
                .sort((a, b) => govOrder.indexOf(a) - govOrder.indexOf(b));
              const selectedGovernor = sortedAvailableGovs[value] || "powersave";
              handleGovernorChange(selectedGovernor);
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ display: 'flex', alignItems: 'center', fontSize: "14px", opacity: 0.7, marginTop: "-6px", marginBottom: "8px", gap: '8px' }}>
            <span style={{ color: '#00d4ff', fontSize: '1.2em', display: 'flex', alignItems: 'center' }}>
              {getGovernorIcon(currentProfile.governor || "powersave")}
            </span>
            <span>
              {(() => {
                const gov = currentProfile.governor || "powersave";
                const govMap: { [key: string]: string } = {
                  "powersave": "Power Saving Mode",
                  "conservative": "Conservative Mode", 
                  "ondemand": "On Demand Mode",
                  "schedutil": "Scheduler Utility",
                  "performance": "Performance Mode"
                };
                return govMap[gov] || gov;
              })()}
            </span>
          </div>
        </PanelSectionRow>
        
        {/* EPP Section - only show when EPP control is meaningful */}
        {(() => {
          const currentGov = currentProfile.governor || "powersave";
          // Hide EPP when using performance governor with limited EPP options
          const showEpp = !(currentGov === "performance" && availableGovernors.includes("performance") && availableGovernors.includes("powersave"));
          return showEpp;
        })() && (
          <>
            <PanelSectionRow>
              <SliderWithIcons
                label="Energy Performance Preference"
                value={(() => {
                  const epp = currentProfile.epp || "balance_performance";
                  const epps = ["power", "balance_power", "balance_performance", "performance"];
                  return epps.indexOf(epp) >= 0 ? epps.indexOf(epp) : 2;
                })()}
                min={0}
                max={3}
                step={1}
                icons={[<FaBatteryFull />, <FaBalanceScale />, <FaChartLine />, <FaRocket />]}
                onChange={(value) => {
                  const epps = ["power", "balance_power", "balance_performance", "performance"];
                  const selectedEpp = epps[value] || "balance_performance";
                  handleEppChange(selectedEpp);
                }}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
                <span style={{ color: '#00d4ff', fontSize: '1.2em', display: 'flex', alignItems: 'center' }}>
                  {getEppIcon(currentProfile.epp || "balance_performance")}
                </span>
                <span>
                  {(() => {
                    const epp = currentProfile.epp || "balance_performance";
                    const eppMap: { [key: string]: string } = {
                      "power": "Maximum Power Savings",
                      "balance_power": "Balanced Power Savings",
                      "balance_performance": "Balanced Performance",
                      "performance": "Maximum Performance"
                    };
                    return eppMap[epp] || epp;
                  })()}
                </span>
              </div>
            </PanelSectionRow>
          </>
        )}
        
      </PanelSection>
      )}

      {/* GPU Control Section - Hidden when ROG Ally native TDP is enabled */}
      {(() => {
        const shouldShow = !(isRogAllyDeviceDetected && rogAllyNativeTdpEnabled);
        debug.log(`GPU Control visibility: isRogAllyDeviceDetected=${isRogAllyDeviceDetected}, rogAllyNativeTdpEnabled=${rogAllyNativeTdpEnabled}, shouldShow=${shouldShow}`);
        return shouldShow;
      })() && (
      <PanelSection title="GPU Control">
        <PanelSectionRow>
          <SliderWithIcons
            label="GPU Power Mode"
            value={(() => {
              const mode = currentProfile.gpuMode || "auto";
              const modes = ["battery", "auto", "range", "fixed"];
              return Math.max(0, modes.indexOf(mode));
            })()}
            min={0}
            max={3}
            step={1}
            icons={[<FaBatteryHalf />, <FaSyncAlt />, <FaChartBar />, <FaBullseye />]}
            onChange={(value) => {
              const modes = ["battery", "auto", "range", "fixed"];
              const selectedMode = modes[value] || "auto";
              handleGpuModeChange(selectedMode);
            }}
          />
        </PanelSectionRow>
        
        <PanelSectionRow>
          {currentProfile.gpuMode === "battery" && (
            <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
              <span style={{ color: '#00d4ff', fontSize: '1.2em', display: 'flex', alignItems: 'center' }}>
                <FaBatteryHalf />
              </span>
              <span>Lowest power consumption, reduced performance</span>
            </div>
          )}
          {currentProfile.gpuMode === "auto" && (
            <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
              <span style={{ color: '#00d4ff', fontSize: '1.2em', display: 'flex', alignItems: 'center' }}>
                <FaSyncAlt />
              </span>
              <span>System automatically manages GPU frequency</span>
            </div>
          )}
          {currentProfile.gpuMode === "range" && (
            <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
              <span style={{ color: '#00d4ff', fontSize: '1.2em', display: 'flex', alignItems: 'center' }}>
                <FaSlidersH />
              </span>
              <span>Set minimum and maximum frequency range</span>
            </div>
          )}
          {currentProfile.gpuMode === "fixed" && (
            <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
              <span style={{ color: '#00d4ff', fontSize: '1.2em', display: 'flex', alignItems: 'center' }}>
                <FaBullseye />
              </span>
              <span>GPU runs at fixed frequency for consistent performance</span>
            </div>
          )}
        </PanelSectionRow>

        {currentProfile.gpuMode === "range" && (
          <>
            <DebouncedSlider
              label="GPU Min Freq"
              value={currentProfile.gpuFreqMin || deviceInfo?.min_gpu_freq || 200}
              min={deviceInfo?.min_gpu_freq || 200}
              max={currentProfile.gpuFreqMax || deviceInfo?.max_gpu_freq || 3000}
              step={50}
              onChange={() => {}} // Handle immediate visual updates
              onChangeEnd={(value) => handleGpuFrequencyChange(value, currentProfile.gpuFreqMax || deviceInfo?.max_gpu_freq || 3000)}
              suffix="MHz"
            />
            <DebouncedSlider
              label="GPU Max Freq"
              value={currentProfile.gpuFreqMax || deviceInfo?.max_gpu_freq || 3000}
              min={currentProfile.gpuFreqMin || deviceInfo?.min_gpu_freq || 200}
              max={deviceInfo?.max_gpu_freq || 3000}
              step={50}
              onChange={() => {}} // Handle immediate visual updates
              onChangeEnd={(value) => handleGpuFrequencyChange(currentProfile.gpuFreqMin || deviceInfo?.min_gpu_freq || 200, value)}
              suffix="MHz"
            />
            {DEBUG_ENABLED && (
              <div style={{ fontSize: '0.7em', color: '#999', padding: '5px' }}>
                Debug: deviceInfo={deviceInfo ? 'loaded' : 'null'} min={deviceInfo?.min_gpu_freq} max={deviceInfo?.max_gpu_freq}
              </div>
            )}
          </>
        )}

        {currentProfile.gpuMode === "fixed" && (
          <DebouncedSlider
            label="GPU Fixed Freq"
            value={Math.min(currentProfile.gpuFreqFixed || Math.floor(((deviceInfo?.min_gpu_freq || 200) + (deviceInfo?.max_gpu_freq || 3000)) / 2), deviceInfo?.max_gpu_freq || 3000)}
            min={deviceInfo?.min_gpu_freq || 200}
            max={deviceInfo?.max_gpu_freq || 3000}
            step={50}
            onChange={() => {}} // Handle immediate visual updates
            onChangeEnd={(value) => handleGpuFixedFrequencyChange(value)}
            suffix="MHz"
          />
        )}
      </PanelSection>
      )}

      {/* ROG Ally Battery Management Section */}
      {isRogAlly && rogAllyDeviceInfo?.available_controls?.battery_management && (
        <PanelSection title="Battery Management">
          <PanelSectionRow>
            <SliderWithIcons
              label="Charge Limit"
              value={rogAllyBatteryChargeLimit}
              min={20}
              max={100}
              step={5}
              icons={[<FaBatteryEmpty />, <FaBatteryHalf />, <FaBatteryFull />]}
              onChange={async (value) => {
                setRogAllyBatteryChargeLimit(value);
                try {
                  await setRogAllyBatteryChargeLimitBackend(value);
                  debug.log(`ROG Ally battery charge limit set to: ${value}%`);
                } catch (error) {
                  debug.error("Failed to set ROG Ally battery charge limit:", error);
                }
              }}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* InputPlumber Controller Emulation Section - Moved above Advanced Power Management */}
      {inputPlumberAvailable && (
        <PanelSection title="Controller Emulation">
          <PanelSectionRow>
            <SliderWithIcons
              label=""
              value={(() => {
                const index = inputPlumberModes.indexOf(currentInputPlumberMode);
                return index >= 0 ? index : 0;
              })()}
              min={0}
              max={Math.max(0, inputPlumberModes.length - 1)}
              step={1}
              icons={inputPlumberModes.map((mode) => getControllerIcon(mode))}
              onChange={async (value) => {
                const selectedMode = inputPlumberModes[value];
                if (selectedMode) {
                  setCurrentInputPlumberMode(selectedMode);
                  try {
                    const success = await setInputPlumberMode(selectedMode);
                    if (success) {
                      const modeInfo = CONTROLLER_MODE_LABELS[selectedMode] || { name: selectedMode, description: '' };
                      debug.log(`InputPlumber mode set to: ${modeInfo.name}`);
                      
                      // Save to current game profile if per-game profiles enabled
                      if (perGameProfilesEnabled && currentGame.id !== "handheld") {
                        const gameId = acPower ? `${currentGame.id}_ac` : `${currentGame.id}_battery`;
                        await saveInputPlumberProfileForGame(gameId, {
                          controller_mode: selectedMode
                        });
                        debug.log(`Saved InputPlumber mode to profile: ${gameId}`);
                      }
                    } else {
                      const modeInfo = CONTROLLER_MODE_LABELS[selectedMode] || { name: selectedMode, description: '' };
                      debug.error(`Failed to set InputPlumber mode to: ${modeInfo.name}`);
                    }
                  } catch (error) {
                    debug.error("Failed to set InputPlumber mode:", error);
                  }
                }
              }}
              showValue={false}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ display: 'flex', alignItems: 'center', fontSize: '0.8em', color: '#888', paddingLeft: '12px', gap: '8px' }}>
              <span style={{ color: '#1a9fff', fontSize: '1.2em' }}>
                {getControllerIcon(currentInputPlumberMode)}
              </span>
              <span>
                {(() => {
                  const modeInfo = CONTROLLER_MODE_LABELS[currentInputPlumberMode];
                  return modeInfo ? modeInfo.name : currentInputPlumberMode;
                })()}
              </span>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* Advanced Power Management Section */}
      <PanelSection title="Advanced Power Management">
        <PanelSectionRow>
          <ToggleField
            label="Show Advanced Options"
            checked={showAdvancedMenu}
            onChange={setShowAdvancedMenu}
          />
        </PanelSectionRow>
        
        {showAdvancedMenu && (
          <>
            {/* ROG Ally Native TDP Toggle - Only show on ROG Ally devices */}
            {(() => {
              debug.log(`Checking ROG Ally toggle visibility: isRogAllyDeviceDetected=${isRogAllyDeviceDetected}`);
              return isRogAllyDeviceDetected;
            })() && (
              <>
                <PanelSectionRow>
                  <ToggleField
                    label="ROG Ally Native TDP Support"
                    checked={rogAllyNativeTdpEnabled}
                    onChange={async (enabled) => {
                      debug.log(`ROG Ally Native TDP toggle changed to: ${enabled}`);
                      await updateRogAllyNativeTdpState(enabled);
                    }}
                  />
                </PanelSectionRow>
              </>
            )}
            
            {/* ROG Ally MCU Power Save - Moved to Advanced Power Management */}
            {isRogAlly && rogAllyDeviceInfo?.available_controls?.mcu_powersave && (
              <PanelSectionRow>
                <ToggleField
                  label="Enable MCU Power Save"
                  description="Reduce power consumption when device is idle"
                  checked={rogAllyMcuPowersave}
                  onChange={async (value) => {
                    setRogAllyMcuPowersave(value);
                    try {
                      await setRogAllyMcuPowersaveBackend(value);
                      debug.log(`ROG Ally MCU power save set to: ${value}`);
                    } catch (error) {
                      debug.error("Failed to set ROG Ally MCU power save:", error);
                    }
                  }}
                />
              </PanelSectionRow>
            )}
            
            <PanelSectionRow>
              <ToggleField
                label="WiFi Power Save"
                description="Enable WiFi power saving features (recommended)"
                checked={wifiPowerSaveEnabled}
                onChange={handleWifiPowerSaveChange}
              />
            </PanelSectionRow>
            
            <PanelSectionRow>
              <ToggleField
                label="USB Auto-suspend"
                description="Enable USB device auto-suspend (may affect some devices)"
                checked={usbAutosuspendEnabled}
                onChange={handleUsbAutosuspendChange}
              />
            </PanelSectionRow>
            
            <PanelSectionRow>
              <ToggleField
                label="PCIe ASPM"
                description="Enable PCIe Active State Power Management"
                checked={pcieAspmEnabled}
                onChange={handlePcieAsmpChange}
              />
            </PanelSectionRow>
            
            <PanelSectionRow>
              <div style={{ fontSize: '0.8em', color: '#888', fontStyle: 'italic', marginTop: '10px' }}>
                Note: Disabled options will not modify system settings and let the OS manage them completely.
              </div>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      {/* Controller Emulation section moved above Advanced Power Management */}

      {/* Plugin Management Section */}
      <PanelSection title="Plugin Management">
        <PanelSectionRow>
          <ToggleField
            label="Per-Game Profiles"
            description="Enable different power settings for each game"
            checked={perGameProfilesEnabled}
            onChange={async (enabled) => {
              setPerGameProfilesEnabledState(enabled);
              try {
                await setPerGameProfilesEnabled(enabled);
                debug.log(`Per-game profiles ${enabled ? 'enabled' : 'disabled'}`);
              } catch (error) {
                debug.error("Failed to set per-game profiles:", error);
              }
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            onClick={async () => {
              try {
                if (updateState === 'idle') {
                  // Step 1: Check for updates
                  setUpdateState('checking');
                  setUpdateMessage('Checking for updates...');
                  debug.log("Checking for updates...");
                  
                  const result = await checkForUpdates();
                  
                  if (result.update_available) {
                    setUpdateState('available');
                    setUpdateMessage(`Update available: ${result.current_version} → ${result.latest_version}`);
                    setUpdateInfo({
                      currentVersion: result.current_version,
                      latestVersion: result.latest_version,
                      downloadUrl: result.download_url
                    });
                    debug.log(`Update available: ${result.current_version} -> ${result.latest_version}`);
                  } else {
                    setUpdateState('idle');
                    setUpdateMessage(`You have the latest version: ${result.current_version}`);
                    debug.log(`You have the latest version: ${result.current_version}`);
                    
                    // Reset message after 3 seconds
                    setTimeout(() => {
                      setUpdateMessage('');
                    }, 3000);
                  }
                  
                } else if (updateState === 'available') {
                  // Step 2: Download and stage update
                  if (!updateInfo?.downloadUrl || !updateInfo?.latestVersion) {
                    setUpdateState('error');
                    setUpdateMessage('Missing update information');
                    return;
                  }
                  
                  setUpdateState('downloading');
                  setUpdateMessage('Downloading update...');
                  debug.log("Downloading and staging update...");
                  
                  const stageResult = await stageUpdate(updateInfo.downloadUrl, updateInfo.latestVersion);
                  
                  if (stageResult.success) {
                    setUpdateState('ready');
                    setUpdateMessage(`Update ready to install: ${updateInfo.latestVersion}`);
                    debug.log("Update staged successfully");
                  } else {
                    setUpdateState('error');
                    setUpdateMessage('Failed to download update');
                    debug.error("Update staging failed:", stageResult.error);
                  }
                  
                } else if (updateState === 'ready') {
                  // Step 3: Install staged update
                  setUpdateState('installing');
                  setUpdateMessage('Installing update...');
                  debug.log("Installing staged update...");
                  
                  const installResult = await installStagedUpdate();
                  
                  if (installResult.success) {
                    setUpdateState('completed');
                    setUpdateMessage(`Successfully updated to ${updateInfo?.latestVersion}! Plugin loader will restart automatically.`);
                    debug.log(`Successfully updated to ${updateInfo?.latestVersion}`);
                    
                    // The backend should handle plugin_loader restart automatically
                    // Reset to idle after a delay to allow user to see completion
                    setTimeout(() => {
                      setUpdateState('idle');
                      setUpdateMessage('');
                      setUpdateInfo(null);
                    }, 5000);
                  } else {
                    setUpdateState('error');
                    setUpdateMessage('Failed to install update');
                    debug.error("Update installation failed:", installResult.error);
                  }
                  
                } else if (updateState === 'completed') {
                  // Manual restart option if auto-restart didn't work
                  debug.log("Manual restart requested");
                  // This could call a restart function if needed
                  
                } else if (updateState === 'error') {
                  // Reset from error state
                  setUpdateState('idle');
                  setUpdateMessage('');
                  setUpdateInfo(null);
                }
                
              } catch (error) {
                setUpdateState('error');
                setUpdateMessage('Unexpected error occurred');
                debug.error("Update process error:", error);
                
                // Reset error state after 5 seconds
                setTimeout(() => {
                  setUpdateState('idle');
                  setUpdateMessage('');
                  setUpdateInfo(null);
                }, 5000);
              }
            }}
            layout="below"
            disabled={updateState === 'checking' || updateState === 'downloading' || updateState === 'installing'}
          >
            {updateState === 'checking' && (
              <>
                <FaSpinner style={{ animation: 'spin 1s linear infinite', marginRight: '6px' }} />
                Checking for Updates...
              </>
            )}
            {updateState === 'available' && (
              <>
                <FaDownload style={{ marginRight: '6px' }} />
                Download Update
              </>
            )}
            {updateState === 'downloading' && (
              <>
                <FaSpinner style={{ animation: 'spin 1s linear infinite', marginRight: '6px' }} />
                Downloading...
              </>
            )}
            {updateState === 'ready' && (
              <>
                <FaCog style={{ marginRight: '6px' }} />
                Install Update
              </>
            )}
            {updateState === 'installing' && (
              <>
                <FaCog style={{ animation: 'spin 1s linear infinite', marginRight: '6px' }} />
                Installing...
              </>
            )}
            {updateState === 'completed' && (
              <>
                <FaCheckCircle style={{ marginRight: '6px' }} />
                Update Complete!
              </>
            )}
            {updateState === 'error' && (
              <>
                <FaExclamationTriangle style={{ marginRight: '6px' }} />
                Retry Update
              </>
            )}
            {updateState === 'idle' && (
              <>
                <FaSearch style={{ marginRight: '6px' }} />
                Check for Updates
              </>
            )}
          </ButtonItem>
          {updateMessage && (
            <div style={{ 
              fontSize: '0.85em', 
              color: updateState === 'error' ? '#ff6b6b' : updateState === 'completed' ? '#51cf66' : '#868e96',
              textAlign: 'center',
              marginTop: '8px',
              padding: '4px 8px',
              borderRadius: '4px',
              backgroundColor: 'rgba(255,255,255,0.05)'
            }}>
              {updateMessage}
            </div>
          )}
        </PanelSectionRow>
      </PanelSection>

      {/* Plugin Version Section */}
      <PanelSection>
        <PanelSectionRow>
          <div style={{ 
            fontSize: '1.0em', 
            color: '#ccc', 
            textAlign: 'center',
            padding: '0 0 8px 0',
            marginTop: '-4px',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px'
          }}>
            <div style={{ fontWeight: '500' }}>
              PowerDeck v{pluginVersion}
            </div>
            {backgroundUpdateStatus && (
              <div style={{ 
                fontSize: '0.9em', 
                color: backgroundUpdateStatus.update_available ? '#ff6b35' : 
                       updateState === 'checking' ? '#4a9eff' : '#4a9eff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px'
              }}>
                {updateState === 'checking' ? (
                  <>
                    <FaSpinner style={{ animation: 'spin 1s linear infinite' }} />
                    Checking for updates...
                  </>
                ) : backgroundUpdateStatus.update_available ? (
                  <>
                    <FaBell />
                    Update v{backgroundUpdateStatus.latest_version} available
                  </>
                ) : (
                  <>
                    <FaCheckCircle />
                    Up to date
                  </>
                )}
                {backgroundUpdateStatus.hours_since_last_check !== null && updateState !== 'checking' && (
                  <div style={{ 
                    fontSize: '0.8em', 
                    color: '#888', 
                    marginTop: '2px',
                    fontStyle: 'italic'
                  }}>
                    Last checked: {Math.round(backgroundUpdateStatus.hours_since_last_check * 10) / 10}h ago
                  </div>
                )}
              </div>
            )}
          </div>
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
};

const index = definePlugin(() => {
  return {
    title: <div className={staticClasses.Title}>PowerDeck</div>,
    content: (
      <PowerDeckErrorBoundary>
        <Content />
      </PowerDeckErrorBoundary>
    ),
    icon: <FaBolt />,
    onDismount() {
      debug.log("Unmounting");
    },
  };
});

export default index;
