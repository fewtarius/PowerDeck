import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import { useSettings } from "../../settings/SettingsProvider";

export function RogAllyExtrasSection() {
  const { state, setRogAllyMcuPowersave } = useSettings();
  if (!state) return null;
  const current = state.capabilities.rog_ally_mcu_powersave ?? true;

  return (
    <PanelSection title="ROG Ally Extras">
      <PanelSectionRow>
        <ToggleField
          label="MCU Power Save"
          checked={current}
          onChange={(v) => setRogAllyMcuPowersave(v as boolean)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
