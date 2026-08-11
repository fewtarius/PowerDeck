import { useState } from "react";
import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { FaMicrochip } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";

interface TdpSectionProps {
  softMode?: boolean;
}

export function TdpSection({ softMode = false }: TdpSectionProps) {
  const { state, applySettings } = useSettings();
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [customMin, setCustomMin] = useState(state?.capabilities.tdp_limits.min ?? 3);
  const [customMax, setCustomMax] = useState(state?.capabilities.tdp_limits.max ?? 30);

  if (!state) return null;

  const tdp = state.current_profile.tdp;
  const limits = state.capabilities.tdp_limits;
  const min = showAdvanced ? customMin : limits.min;
  const max = showAdvanced ? customMax : limits.max;

  return (
    <PanelSection title={softMode ? "TDP Control (Soft - Governor/EPP Mapping)" : "TDP Control"}>
      {softMode && (
        <PanelSectionRow>
          <div style={{ padding: "8px 0", fontSize: 12, color: "#aaa" }}>
            Hardware TDP control is unavailable (likely Secure Boot blocking ryzenadj).
            <br />
            The TDP slider below maps to CPU governor/EPP profiles instead of actual watts:
          </div>
        </PanelSectionRow>
      )}
      {softMode && (
        <PanelSectionRow>
          <div style={{ padding: "8px 0", fontSize: 11, color: "#666" }}>
            Battery Saver (Low TDP): powersave governor + power EPP<br />
            Balanced (Medium TDP): schedutil governor + balance_power EPP<br />
            Performance (High TDP): performance governor + performance EPP
          </div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <LabeledSlider
          label="TDP"
          value={tdp}
          min={min}
          max={max}
          step={1}
          icon={<FaMicrochip />}
          displayValue={`${tdp} Watts`}
          onChange={(value) => applySettings({ tdp: value })}
          description={softMode ? "Mapped to governor + EPP" : `Range: ${min}-${max}W`}
        />
      </PanelSectionRow>
      {!softMode && (
        <>
          <PanelSectionRow>
            <ToggleField
              label="Custom TDP Range"
              checked={showAdvanced}
              onChange={(v) => setShowAdvanced(v as boolean)}
            />
          </PanelSectionRow>
          {showAdvanced && (
            <>
              <PanelSectionRow>
                <LabeledSlider
                  label="TDP Min"
                  value={customMin}
                  min={limits.min}
                  max={customMax}
                  step={1}
                  icon={<FaMicrochip />}
                  displayValue={`${customMin} Watts`}
                  onChange={(value) => {
                    setCustomMin(value);
                    if (state.current_profile.tdp < value) {
                      applySettings({ tdp: value });
                    }
                  }}
                  description={`Range: ${limits.min}-${customMax}W`}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <LabeledSlider
                  label="TDP Max"
                  value={customMax}
                  min={customMin}
                  max={limits.max}
                  step={1}
                  icon={<FaMicrochip />}
                  displayValue={`${customMax} Watts`}
                  onChange={(value) => {
                    setCustomMax(value);
                    if (state.current_profile.tdp > value) {
                      applySettings({ tdp: value });
                    }
                  }}
                  description={`Range: ${customMin}-${limits.max}W`}
                />
              </PanelSectionRow>
            </>
          )}
        </>
      )}
      {softMode && state.capabilities.tdp_control.method && (
        <PanelSectionRow>
          <div style={{ padding: "4px 0", fontSize: 11, color: "#666" }}>
            Method: {state.capabilities.tdp_control.method} - {state.capabilities.tdp_control.reason}
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
