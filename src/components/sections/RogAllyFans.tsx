import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaFan } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";

function fanModeToIdx(mode: number): number {
  return mode === 2 ? 1 : 0;
}

const FAN_NAMES = ["Silent", "Performance"];
const FAN_DESCRIPTIONS = ["Off when cool", "Full speed"];

export function RogAllyFansSection() {
  const { state, setRogAllyFanMode } = useSettings();
  if (!state) return null;
  const fans = state.capabilities.rog_ally_fan_status;
  if (!fans) return null;

  const cpuIdx = fanModeToIdx(fans.cpu_fan.mode);
  const gpuIdx = fanModeToIdx(fans.gpu_fan.mode);
  const cpuName = FAN_NAMES[cpuIdx];
  const gpuName = FAN_NAMES[gpuIdx];
  const cpuDesc = FAN_DESCRIPTIONS[cpuIdx];
  const gpuDesc = FAN_DESCRIPTIONS[gpuIdx];

  return (
    <PanelSection title="Fan Control">
      <PanelSectionRow>
        <LabeledSlider
          label="CPU Fan Mode"
          value={cpuIdx}
          min={0}
          max={1}
          step={1}
          notches={2}
          icon={<FaFan />}
          displayValue={cpuName}
          onChange={async (v) => {
            await setRogAllyFanMode(1, v === 1 ? 2 : 0);
          }}
          description={cpuDesc}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <LabeledSlider
          label="GPU Fan Mode"
          value={gpuIdx}
          min={0}
          max={1}
          step={1}
          notches={2}
          icon={<FaFan />}
          displayValue={gpuName}
          onChange={async (v) => {
            await setRogAllyFanMode(2, v === 1 ? 2 : 0);
          }}
          description={gpuDesc}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
