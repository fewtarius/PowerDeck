import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { FaMicrochip, FaRocket } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";
import { EPP_DESCRIPTIONS, EPP_VALUES, GOVERNOR_DESCRIPTIONS, getOrderedGovernors } from "../../api";

export function CpuSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;

  const device = state.device_info;
  const profile = state.current_profile;
  const activePowerControl =
    device.powerControl?.active_method && device.powerControl.active_method !== "none";

  const orderedGovernors = getOrderedGovernors(state.capabilities.governors);
  const showGovernor = device.scalingDriver !== "amd-pstate-epp" && !activePowerControl;
  const showEpp = device.scalingDriver === "amd-pstate-epp" && !activePowerControl;

  const maxCores = device.max_cpu_cores || 16;
  const cpuCoresMax = profile.smt ? maxCores : Math.floor(maxCores / 2);

  const governorIdx = Math.max(0, orderedGovernors.indexOf(profile.governor));
  const govName = orderedGovernors[governorIdx] ?? profile.governor;
  const govDesc = GOVERNOR_DESCRIPTIONS[profile.governor] ?? "";

  const eppIdx = Math.max(0, EPP_VALUES.indexOf(profile.epp as any));
  const eppName = EPP_VALUES[eppIdx] ?? profile.epp;
  const eppDesc = EPP_DESCRIPTIONS[profile.epp as any] ?? "";

  return (
    <PanelSection title="CPU Control">
      <PanelSectionRow>
        <LabeledSlider
          label="CPU Cores"
          value={profile.cpuCores}
          min={1}
          max={cpuCoresMax}
          step={1}
          icon={<FaMicrochip />}
          displayValue={`${profile.cpuCores} (Online)`}
          onChange={(value) => applySettings({ cpuCores: value })}
          description={`Range: 1-${cpuCoresMax}`}
        />
      </PanelSectionRow>
      {device.supports_smt && (
        <PanelSectionRow>
          <ToggleField
            label="SMT (Hyperthreading)"
            checked={profile.smt}
            onChange={(enabled) => {
              const adjusted =
                !enabled && profile.cpuCores > Math.floor(maxCores / 2)
                  ? Math.floor(maxCores / 2)
                  : profile.cpuCores;
              applySettings({ smt: enabled as boolean, cpuCores: adjusted });
            }}
          />
        </PanelSectionRow>
      )}
      {device.supports_cpu_boost && (
        <PanelSectionRow>
          <ToggleField
            label="CPU Boost"
            checked={profile.cpuBoost}
            onChange={(v) => applySettings({ cpuBoost: v as boolean })}
          />
        </PanelSectionRow>
      )}
      {showGovernor && orderedGovernors.length > 1 && (
        <PanelSectionRow>
          <LabeledSlider
            label="Governor"
            value={governorIdx}
            min={0}
            max={orderedGovernors.length - 1}
            step={1}
            notches={orderedGovernors.length}
            icon={<FaMicrochip />}
            displayValue={govName}
            onChange={(v) => applySettings({ governor: orderedGovernors[v] })}
            description={govDesc}
          />
        </PanelSectionRow>
      )}
      {showEpp && (
        <PanelSectionRow>
          <LabeledSlider
            label="EPP"
            value={eppIdx}
            min={0}
            max={EPP_VALUES.length - 1}
            step={1}
            notches={EPP_VALUES.length}
            icon={<FaRocket />}
            displayValue={eppName}
            onChange={(v) => applySettings({ epp: EPP_VALUES[v] })}
            description={eppDesc}
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
