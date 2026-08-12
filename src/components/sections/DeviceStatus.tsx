import { PanelSection, PanelSectionRow, Router } from "@decky/ui";
import {
  FaMicrochip,
  FaPlug,
  FaGamepad,
  FaShieldAlt,
} from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { InfoRow } from "../shared";
import { COLORS } from "../shared";

function currentGameName(): string | null {
  const appName = Router.MainRunningApp?.display_name;
  if (appName && appName !== "Default" && appName !== "Steam") return appName;
  return null;
}

export function DeviceStatusSection() {
  const { state } = useSettings();
  if (!state) return null;

  const device = state.device_info;
  const perGame = state.per_game_profiles_enabled;
  const gameName = perGame ? currentGameName() : null;

  return (
    <PanelSection title="Device Status">
      <PanelSectionRow>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
          <InfoRow
            icon={<FaMicrochip />}
            label="Device"
            value={device.device_name}
          />
          <InfoRow
            icon={<FaPlug />}
            label="Power"
            value={state.ac_power ? "AC Connected" : "On Battery"}
            valueColor={state.ac_power ? COLORS.statusOk : COLORS.statusWarn}
          />
          <InfoRow
            icon={gameName ? <FaGamepad /> : <FaShieldAlt />}
            label="Profile"
            value={gameName ? `Active Game: ${gameName}` : "Handheld (default)"}
            valueColor={gameName ? COLORS.accent : "#aaa"}
          />
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}
