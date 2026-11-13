import { useState } from "react";
import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

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

  const profileTdp = state.current_profile.tdp;
  const limits = state.capabilities.tdp_limits;
  const min = showAdvanced ? customMin : limits.min;
  const max = showAdvanced ? customMax : limits.max;
  // An unset TDP means PowerDeck is not managing the power limit. Show the
  // firmware's live value so the thumb reflects reality; the first drag
  // commits a limit into the profile and takes ownership from then on.
  const managed = profileTdp != null;
  const tdp = Math.min(Math.max(profileTdp ?? limits.current ?? min, min), max);
  // A part can be rated to a burst figure it cannot hold indefinitely.
  // The 395 tops out at 120W cTDP but measures a 100W slow ceiling, so a
  // 120W selection is 120W burst and 100W sustained. Say so rather than
  // implying the sustained figure it is.
  const sustained =
    limits.slow_max != null && limits.slow_max < tdp ? limits.slow_max : tdp;

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
            Balanced (Medium TDP): best available balanced governor (schedutil or powersave) + balance_power EPP<br />
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
          displayValue={managed ? `${tdp} Watts` : `${tdp} Watts (firmware)`}
          onChange={(value) => applySettings({ tdp: value })}
          description={
            softMode
              ? "Mapped to governor + EPP"
              : managed
                ? sustained < tdp
                  ? `${tdp}W burst / ${sustained}W sustained. Range: ${min}-${max}W`
                  : `Range: ${min}-${max}W`
                : `Not managed by PowerDeck - firmware limit ${limits.current}W. Move to set. Range: ${min}-${max}W`
          }
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
                  displayValue={`${customMin} Watts`}
                  onChange={(value) => {
                    setCustomMin(value);
                    if (managed && (profileTdp as number) < value) {
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
                  displayValue={`${customMax} Watts`}
                  onChange={(value) => {
                    setCustomMax(value);
                    if (managed && (profileTdp as number) > value) {
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
