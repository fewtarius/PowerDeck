import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaCogs } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";
import { PLATFORM_PROFILE_DESCRIPTIONS } from "../../api";

// Friendly display names for platform profile strings. ACPI uses
// several spellings ("power-saver", "low-power", "balanced",
// "performance") - the alias map collapses them.
const PLATFORM_ALIASES: { [k: string]: string } = { "low-power": "power-saver" };

function normalize(profile: string): string {
  return PLATFORM_ALIASES[profile] ?? profile;
}

const PROFILE_DISPLAY: { [k: string]: string } = {
  "power-saver": "Power Saver",
  balanced: "Balanced",
  performance: "Performance",
};

export function PlatformProfileSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;
  const choices = state.device_info.powerControl?.platform_profile_choices ?? [];
  const profiles = choices.length > 0 ? choices : ["power-saver", "balanced", "performance"];
  const current = normalize(state.current_profile.platformProfile ?? "balanced");
  const activeIdx = profiles.indexOf(current);
  const idx = activeIdx >= 0 ? activeIdx : 0;

  const name = PROFILE_DISPLAY[current] ?? current;
  const desc = PLATFORM_PROFILE_DESCRIPTIONS[current] ?? "";

  return (
    <PanelSection title="Platform Profile">
      <PanelSectionRow>
        <LabeledSlider
          label="Platform Profile"
          value={idx}
          min={0}
          max={profiles.length - 1}
          step={1}
          notches={profiles.length}
          icon={<FaCogs />}
          displayValue={name}
          onChange={(v) => applySettings({ platformProfile: profiles[v] })}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
