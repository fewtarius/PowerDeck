import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaTachometerAlt } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";

const MODE_LABELS: { [k: string]: string } = {
  battery: "Battery",
  auto: "Auto",
  performance: "Performance",
  range: "Range",
  fixed: "Fixed",
};

const MODE_DESCRIPTIONS: { [k: string]: string } = {
  battery: "Maximum Power Saving",
  auto: "Auto-scales with workload",
  performance: "Maximum Performance",
  range: "Range (min/max)",
  fixed: "Lock GPU at a fixed frequency",
};

function availableModes(isJELOS: boolean | undefined): string[] {
  return isJELOS
    ? ["battery", "auto", "performance", "range", "fixed"]
    : ["battery", "auto", "range", "fixed"];
}

const SLIDER_STEP = 50;

export function GpuSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;
  const device = state.device_info;
  const profile = state.current_profile;
  const modes = availableModes(device.isJELOS);
  const mode = profile.gpuMode || "auto";
  const modeIdx = Math.max(0, modes.indexOf(mode));
  const modeLabel = MODE_LABELS[mode] ?? mode;
  const modeDesc = MODE_DESCRIPTIONS[mode] ?? "";

  const minFreq = device.min_gpu_freq;
  const maxFreq = device.max_gpu_freq;

  const adjustRange = (field: "min" | "max", val: number) => {
    const cur = {
      gpuFreqMin: profile.gpuFreqMin || minFreq,
      gpuFreqMax: profile.gpuFreqMax || maxFreq,
    };
    let mn = field === "min" ? val : cur.gpuFreqMin;
    let mx = field === "max" ? val : cur.gpuFreqMax;
    if (mn >= mx) {
      if (mx >= maxFreq - SLIDER_STEP) {
        mx = maxFreq;
        mn = Math.max(mx - SLIDER_STEP, minFreq);
      } else {
        mx = Math.min(mn + SLIDER_STEP, maxFreq);
      }
      if (mn >= mx) {
        mn = minFreq;
        mx = Math.min(minFreq + SLIDER_STEP, maxFreq);
      }
    }
    applySettings({ gpuFreqMin: mn, gpuFreqMax: mx });
  };

  return (
    <PanelSection title="GPU Control">
      <PanelSectionRow>
        <LabeledSlider
          label="GPU Mode"
          value={modeIdx}
          min={0}
          max={modes.length - 1}
          step={1}
          notches={modes.length}
          icon={<FaTachometerAlt />}
          displayValue={modeLabel}
          onChange={(v) => applySettings({ gpuMode: modes[v] })}
          description={modeDesc}
        />
      </PanelSectionRow>
      {mode === "range" && (
        <>
          <PanelSectionRow>
            <LabeledSlider
              label="GPU Min Freq"
              value={profile.gpuFreqMin || minFreq}
              min={minFreq}
              max={profile.gpuFreqMax || maxFreq}
              step={SLIDER_STEP}
              icon={<FaTachometerAlt />}
              displayValue={`${profile.gpuFreqMin || minFreq} MHz`}
              onChange={(v) => adjustRange("min", v)}
              description={`Range: ${minFreq}-${maxFreq}MHz`}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <LabeledSlider
              label="GPU Max Freq"
              value={profile.gpuFreqMax || maxFreq}
              min={profile.gpuFreqMin || minFreq}
              max={maxFreq}
              step={SLIDER_STEP}
              icon={<FaTachometerAlt />}
              displayValue={`${profile.gpuFreqMax || maxFreq} MHz`}
              onChange={(v) => adjustRange("max", v)}
              description={`Range: ${minFreq}-${maxFreq}MHz`}
            />
          </PanelSectionRow>
        </>
      )}
      {mode === "fixed" && (
        <PanelSectionRow>
          <LabeledSlider
            label="GPU Fixed Freq"
            value={Math.min(
              profile.gpuFreqFixed || Math.floor((minFreq + maxFreq) / 2),
              maxFreq
            )}
            min={minFreq}
            max={maxFreq}
            step={SLIDER_STEP}
            icon={<FaTachometerAlt />}
            displayValue={`${Math.min(profile.gpuFreqFixed || Math.floor((minFreq + maxFreq) / 2), maxFreq)} MHz`}
            onChange={(v) => {
              const clamped = Math.max(minFreq, Math.min(v, maxFreq));
              applySettings({ gpuFreqFixed: clamped });
            }}
            description={`Range: ${minFreq}-${maxFreq}MHz`}
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
