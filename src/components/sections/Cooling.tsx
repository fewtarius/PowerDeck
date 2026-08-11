import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaFan } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";
import { COOLING_PROFILES, COOLING_DESCRIPTIONS } from "../../api";

const COOLING_DISPLAY: { [k: string]: string } = {
  auto: "Auto",
  quiet: "Quiet",
  moderate: "Moderate",
  aggressive: "Aggressive",
};

export function CoolingSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;

  const profile = state.current_profile.fanProfile || "auto";
  const idx = Math.max(0, COOLING_PROFILES.indexOf(profile as any));
  const name = COOLING_DISPLAY[profile] ?? profile;
  const desc = COOLING_DESCRIPTIONS[profile] ?? "";

  return (
    <PanelSection title="Cooling Profile">
      <PanelSectionRow>
        <LabeledSlider
          label="Cooling"
          value={idx}
          min={0}
          max={COOLING_PROFILES.length - 1}
          step={1}
          notches={COOLING_PROFILES.length}
          icon={<FaFan />}
          displayValue={name}
          onChange={(v) => applySettings({ fanProfile: COOLING_PROFILES[v] })}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
