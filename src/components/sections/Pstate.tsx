import { PanelSection, PanelSectionRow } from "@decky/ui";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider, pstateIcon } from "../shared";

const PSTATE_NAMES = ["Active", "Passive", "Guided"];
const PSTATE_DESCRIPTIONS = [
  "OS controls via governor + EPP",
  "OS controls frequency directly",
  "Firmware-controlled (governor/EPP ignored)",
];
const PSTATE_MODES = ["active", "passive", "guided"];

export function PstateSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;
  const caps = state.capabilities.pstate;
  if (!caps) return null;

  const current = caps.current_mode || "guided";
  const idx = PSTATE_MODES.indexOf(current);
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
          max={PSTATE_MODES.length - 1}
          step={1}
          notches={PSTATE_MODES.length}
          valueIcons={PSTATE_MODES.map(pstateIcon)}
          displayValue={name}
          onChange={(v) => applySettings({ pstateMode: PSTATE_MODES[v] })}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
