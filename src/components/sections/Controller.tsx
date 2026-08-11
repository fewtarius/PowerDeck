import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaGamepad } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";
import { CONTROLLER_MODE_LABELS } from "../../api";

export function ControllerSection() {
  const { state, setControllerMode } = useSettings();
  if (!state) return null;
  const ctrl = state.capabilities.controller;
  if (!ctrl.available) return null;
  const modes = ctrl.modes;
  const current = ctrl.current_mode || modes[0] || "default";
  const idx = Math.max(0, modes.indexOf(current));
  const label = CONTROLLER_MODE_LABELS[current];
  const name = label?.name ?? current;
  const desc = label?.description ?? "";

  return (
    <PanelSection title="Controller Emulation">
      <PanelSectionRow>
        <LabeledSlider
          label="Controller"
          value={idx}
          min={0}
          max={Math.max(0, modes.length - 1)}
          step={1}
          notches={modes.length}
          icon={<FaGamepad />}
          displayValue={name}
          onChange={(v) => {
            const mode = modes[v];
            if (mode) setControllerMode(mode);
          }}
          description={desc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
