import { callable } from "@decky/api";
import type {
  BackendState,
  ControllerMode,
  UpdateCheckResult,
  UpdateStageResult,
} from "./types";

export const getState = callable<[], BackendState>("get_state");

export const applySettings = callable<[partial: any], boolean>("apply_settings");

export const setPerGameProfilesEnabled = callable<[enabled: boolean], boolean>("set_per_game_profiles_enabled");

export const setControllerMode = callable<[mode: string], boolean>("set_controller_mode");

export const updatePlugin = callable<[], boolean>("update_plugin");

export const checkForUpdates = callable<[], UpdateCheckResult>("check_for_updates");

export const stageUpdate = callable<[downloadUrl: string, version: string], UpdateStageResult>("stage_update");

export const installStagedUpdate = callable<[], UpdateStageResult>("install_staged_update");

export const setRogAllyPlatformProfile = callable<[profile: string], boolean>("set_rog_ally_platform_profile");

export const setRogAllyFanMode = callable<[fanId: number, mode: number], boolean>("set_rog_ally_fan_mode");

export const setRogAllyMcuPowersave = callable<[enabled: boolean], boolean>("set_rog_ally_mcu_powersave");

export const setRogAllyThermalPolicy = callable<[policy: number], boolean>("set_rog_ally_thermal_policy");

export const setBatteryChargeLimit = callable<[limit: number], boolean>("set_battery_charge_limit");

export const getAcPowerStatus = callable<[], boolean>("get_ac_power_status");

export const CONTROLLER_MODE_LABELS: { [key: string]: ControllerMode } = {
  "default": { name: "Default", description: "Hardware default (varies by device)" },
  "xbox-elite": { name: "Xbox Elite", description: "Xbox Elite controller" },
  "xbox-series": { name: "Xbox Series", description: "Xbox Series X|S controller" },
  "ds5": { name: "DualSense", description: "PlayStation 5 DualSense" },
  "ds5-edge": { name: "DualSense Edge", description: "PlayStation 5 DualSense Edge" },
  "deck-uhid": { name: "Steam Deck", description: "Steam Deck native input" },
  "unified-gamepad": { name: "Unified Gamepad", description: "Unified gamepad target" },
};

export const COOLING_PROFILES = ["auto", "quiet", "moderate", "aggressive"] as const;
export type CoolingProfile = (typeof COOLING_PROFILES)[number];

export const PSTATE_MODES = ["active", "passive", "guided"] as const;
export type PstateMode = (typeof PSTATE_MODES)[number];

export const EPP_VALUES = ["power", "balance_power", "balance_performance", "performance"] as const;
export type EppValue = (typeof EPP_VALUES)[number];

export const GOVERNOR_ORDER = ["powersave", "conservative", "ondemand", "schedutil", "performance"] as const;

export const PLATFORM_PROFILE_DESCRIPTIONS: { [key: string]: string } = {
  "power-saver": "Maximum Power Saving",
  "low-power": "Maximum Power Saving",
  "balanced": "Balanced",
  "performance": "Max Performance",
};

export const GOVERNOR_DESCRIPTIONS: { [key: string]: string } = {
  "powersave": "Maximum Power Saving",
  "conservative": "Power Saving",
  "ondemand": "Balanced",
  "schedutil": "Performance",
  "performance": "Max Performance",
};

export const EPP_DESCRIPTIONS: { [key: string]: string } = {
  "power": "Maximum Power Saving",
  "balance_power": "Balanced Power Saving",
  "balance_performance": "Balanced Performance",
  "performance": "Max Performance",
};

export const COOLING_DESCRIPTIONS: { [key: string]: string } = {
  "auto": "System managed",
  "quiet": "Quiet operation",
  "moderate": "Balanced cooling",
  "aggressive": "Aggressive cooling",
};

export const THERMAL_POLICY_DESCRIPTIONS: { [key: number]: string } = {
  0: "Quiet - minimal fan noise",
  1: "Balanced - moderate cooling",
  2: "Aggressive - active cooling",
  3: "Performance - maximum cooling",
};

export function getOrderedGovernors(available: string[]): string[] {
  return GOVERNOR_ORDER.filter((g) => available.includes(g));
}
