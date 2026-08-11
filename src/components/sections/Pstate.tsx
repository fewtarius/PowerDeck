import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaCogs } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";

const PSTATE_NAMES = ["Active", "Passive", "Guided"];
const PSTATE_DESCRIPTIONS = [
  "CPU scales via EPP",
  "OS scales the CPU",
  "Hardware + OS scaling",
];

export function PstateSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;
  const caps = state.capabilities.pstate;
  if (!caps) return null;

  const current = caps.current_mode || "guided";
  const idx = ["active", "passive", "guided"].indexOf(current);
  const safe = idx >= 0 ? idx : 2;

  const name = PSTATE_NAMES[safe];
  const desc = PSTATE_DESCRIPTIONS[safe];

  return (
    <PanelSection title="CPU Driver Mode">
      <PanelSectionRow>
        <LabeledSlider
          label="P-State"
          value={safe}
          min={0}
          max={2}
          step={1}
          notches={3}
          icon={<FaCogs />}
          displayValue={name}
          onChange={(v) => applySettings({ pstateMode: ["active", "passive", "guided"][v] })}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
