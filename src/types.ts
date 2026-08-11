export interface PowerProfile {
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
  usbAutosuspend?: boolean;
  pcieAspm?: boolean;
  pciRuntimePm?: boolean;
  platformProfile?: string;
  thermalPolicy?: number;
  pstateMode?: string;
}

export interface RogAllyFanMode {
  speed: number | null;
  mode: number;
  label: string;
}

export interface RogAllyFanStatus {
  cpu_fan: RogAllyFanMode;
  gpu_fan: RogAllyFanMode;
}

export interface RogAllyControls {
  fan_control?: boolean;
  thermal_policy?: boolean;
  mcu_powersave?: boolean;
  power_limits?: boolean;
  platform_profiles?: boolean;
  battery_charge_limit?: boolean;
}

export interface RogAllyDeviceInfo {
  device_name: string;
  available_controls: RogAllyControls;
}

export interface PowerControlCapabilities {
  active_method: "platform_profile" | "native_tdp" | "none";
  platform_profile_available: boolean;
  platform_profile_choices: string[];
  native_tdp_available: boolean;
  reason: string;
}

export interface PStateModeCapabilities {
  current_mode: string;
  available_modes: string[];
  available_governors: string[];
  epp_available: boolean;
  epp_preferences: string[];
  mode_switch_supported: boolean;
}

export interface TdpControlAvailability {
  available: boolean;
  method: string;
  has_soft_control: boolean;
  reason: string;
}

export interface ControllerMode {
  name: string;
  description: string;
}

export interface ControllerInfo {
  available: boolean;
  current_mode: string;
  dbus_mode: boolean;
  modes: string[];
}

export interface UpdateCheckResult {
  update_available: boolean;
  current_version: string;
  latest_version: string;
  download_url?: string;
  error?: string;
}

export interface UpdateStageResult {
  success: boolean;
  staged_path?: string;
  error?: string;
}

export interface UpdateStatus {
  update_available: boolean;
  latest_version: string | null;
  hours_since_last_check: number | null;
}

export interface UpdateStageResult {
  success: boolean;
  error?: string;
}

export interface DeviceInfo {
  device_name: string;
  cpu_name: string;
  tdp_min: number;
  tdp_max: number;
  cpu_core_count: number;
  max_cpu_cores: number;
  has_fan_control: boolean;
  supports_cpu_boost: boolean;
  supports_smt: boolean;
  supports_gpu_control: boolean;
  min_gpu_freq: number;
  max_gpu_freq: number;
  scalingDriver?: string;
  supports_wifi_power_save?: boolean;
  supports_usb_power_mgmt?: boolean;
  supports_pcie_aspm?: boolean;
  battery_charge_limit_available?: boolean;
  isJELOS?: boolean;
  powerControl?: PowerControlCapabilities;
  cpu_family?: string;
  cpu_series?: string;
  cpu_vendor?: string;
  form_factor?: string;
}

export interface BackendState {
  plugin_version: string;
  plugin_loader_restart_in_progress: boolean;
  device_info: DeviceInfo;
  ac_power: boolean;
  per_game_profiles_enabled: boolean;
  update_status: UpdateStatus;
  defaults: {
    tdp: number;
    gpu_freq_min: number;
    gpu_freq_max: number;
  };
  capabilities: {
    governors: string[];
    fan_profiles: string[];
    tdp_limits: { min: number; max: number };
    tdp_control: TdpControlAvailability;
    pstate: PStateModeCapabilities | null;
    battery_charge_limit: number | null;
    usb_autosuspend: { [key: string]: boolean };
    pci_runtime_pm: { [key: string]: boolean };
    wifi_power_save: boolean | null;
    pcie_aspm_policy: string | null;
    controller: ControllerInfo;
    rog_ally: RogAllyDeviceInfo | null;
    rog_ally_platform_profile: string | null;
    rog_ally_thermal_policy: number | null;
    rog_ally_mcu_powersave: boolean | null;
    rog_ally_fan_status: RogAllyFanStatus | null;
  };
  current_profile_id: string;
  current_profile: PowerProfile;
}
