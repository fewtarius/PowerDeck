import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaThermometerHalf } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";

const THERMAL_NAMES = ["Quiet", "Balanced", "Aggressive", "Performance"];
const THERMAL_DESCRIPTIONS = [
  "Minimal fan noise",
  "Moderate cooling",
  "Active cooling",
  "Maximum cooling",
];

export function RogAllyThermalSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;
  const current = state.current_profile.thermalPolicy ?? state.capabilities.rog_ally_thermal_policy ?? 0;
  const idx = Math.max(0, Math.min(3, current));

  const name = THERMAL_NAMES[idx];
  const desc = THERMAL_DESCRIPTIONS[idx];

  return (
    <PanelSection title="Thermal Management">
      <PanelSectionRow>
        <LabeledSlider
          label="Thermal"
          value={idx}
          min={0}
          max={3}
          step={1}
          notches={4}
          icon={<FaThermometerHalf />}
          displayValue={name}
          onChange={(v) => applySettings({ thermalPolicy: v })}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
