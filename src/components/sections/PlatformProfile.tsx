import { PanelSection, PanelSectionRow } from "@decky/ui";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider, platformProfileIcon } from "../shared";
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
  // Prefer the live sysfs value: the saved profile can diverge from the
  // hardware (firmware default, another tool, or a profile written before
  // platform_profile was exposed).
  const current = normalize(
    state.capabilities.platform_profile ??
      state.current_profile.platformProfile ??
      "balanced"
  );
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
          valueIcons={profiles.map(platformProfileIcon)}
          displayValue={name}
          onChange={(v) => applySettings({ platformProfile: profiles[v] })}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
