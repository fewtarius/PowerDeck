import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider, governorIcon, eppIcon, pstateIcon } from "../shared";
import { EPP_DESCRIPTIONS, EPP_VALUES, GOVERNOR_DESCRIPTIONS, getOrderedGovernors } from "../../api";

const PSTATE_NAMES = ["Active", "Passive", "Guided"];
const PSTATE_DESCRIPTIONS = [
  "OS controls via governor + EPP",
  "OS controls frequency directly",
  "Firmware-controlled (governor/EPP ignored)",
];
const PSTATE_MODES = ["active", "passive", "guided"];

export function CpuSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;

  const device = state.device_info;
  const profile = state.current_profile;
  const orderedGovernors = getOrderedGovernors(state.capabilities.governors);
  const pstateCaps = state.capabilities.pstate;
  // Live hardware readings. The saved profile can disagree with the
  // kernel (coerced EPP, governor fallback, external tooling), and the
  // UI must show what the CPU is actually running.
  const liveGovernor = state.capabilities.governor ?? null;
  const liveEpp = state.capabilities.epp ?? null;
  // Governor is relevant on all drivers: on amd-pstate-epp it gates the
  // EPP hint set (performance governor silently restricts EPP to
  // 'performance'), and on classic amd-pstate it's the primary control
  // surface in passive/guided mode. Show it whenever the kernel exposes
  // more than one option; a single governor offers nothing to choose.
  const showGovernor = orderedGovernors.length > 1;
  // ACPI platform_profile is a separate control surface - it drives EC
  // power limits and fan, not cpufreq - so it must NOT suppress EPP.
  // The backend already gates epp_available on pstate mode "active"
  // (the only mode where the kernel honors the hint), so the slider
  // appears/disappears with the mode automatically.
  const showEpp = pstateCaps?.epp_available ?? false;

  const maxCores = device.max_cpu_cores || 16;
  const cpuCoresMax = profile.smt ? maxCores : Math.floor(maxCores / 2);

  const govValue = liveGovernor ?? profile.governor;
  const governorIdx = Math.max(0, orderedGovernors.indexOf(govValue));
  const govName = orderedGovernors[governorIdx] ?? govValue;
  // Description must track the *displayed* (snapped) governor, not the
  // raw profile value: when the profile holds a governor the kernel
  // doesn't expose (e.g. "schedutil" under amd-pstate-epp active where
  // only powersave/performance exist) the slider snaps to index 0 but
  // the description still read the stale profile value.
  const govDesc = GOVERNOR_DESCRIPTIONS[govName] ?? "";

  const eppOptions = (showEpp && pstateCaps && pstateCaps.epp_preferences.length > 0
    ? pstateCaps.epp_preferences
    : Array.from(EPP_VALUES)
  ).filter((e) => e !== "default" && e !== "custom");
  // Enforce canonical left-to-right order regardless of the kernel's
  // sysfs ordering (energy_performance_available_preferences is returned
  // in an arbitrary sequence, e.g. "default performance ... power").
  // UI must read battery-saving on the left, performance on the right.
  const orderedEppOptions = EPP_VALUES.filter((e) =>
    (eppOptions as readonly string[]).includes(e)
  ) as string[];
  const eppValue = (liveEpp ?? profile.epp) as string;
  const eppIdx = Math.max(0, orderedEppOptions.indexOf(eppValue));
  const eppName = orderedEppOptions[eppIdx] ?? eppValue;
  const eppDesc = EPP_DESCRIPTIONS[eppName] ?? "";

  // P-State mode index (computed once; defaults to Guided = 2)
  const pstateModes: string[] = PSTATE_MODES;
  const pstateIdx = Math.max(
    0,
    pstateModes.indexOf(pstateCaps?.current_mode ?? "guided")
  );

  return (
    <PanelSection title="CPU Control">
      <PanelSectionRow>
        <LabeledSlider
          label="CPU Cores"
          value={profile.cpuCores}
          min={1}
          max={cpuCoresMax}
          step={1}
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
              const smtDisabledMax = Math.floor(maxCores / 2);
              const adjusted = !enabled
                ? Math.min(profile.cpuCores, smtDisabledMax)
                : (profile.cpuCores === smtDisabledMax
                    ? maxCores
                    : profile.cpuCores);
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
      {pstateCaps && pstateCaps.mode_switch_supported && (
        <PanelSectionRow>
          <LabeledSlider
            label="CPU Driver Mode (P-State)"
            value={pstateIdx}
            min={0}
            max={pstateModes.length - 1}
            step={1}
            notches={pstateModes.length}
            valueIcons={pstateModes.map(pstateIcon)}
            displayValue={PSTATE_NAMES[pstateIdx]}
            onChange={(v) => applySettings({ pstateMode: pstateModes[v] })}
            description={PSTATE_DESCRIPTIONS[pstateIdx]}
          />
          {pstateCaps.current_mode === "guided" && (
            <div style={{ padding: "8px 12px", color: "#ffb366", fontSize: "0.8em" }}>
              Governor and EPP are ignored in Guided mode. Switch to "Active"
              for those settings to take effect.
            </div>
          )}
        </PanelSectionRow>
      )}
      {showGovernor && (
        <PanelSectionRow>
          <LabeledSlider
            label="Governor"
            value={governorIdx}
            min={0}
            max={orderedGovernors.length - 1}
            step={1}
            notches={orderedGovernors.length}
            valueIcons={orderedGovernors.map(governorIcon)}
            displayValue={govName}
            onChange={(v) => applySettings({ governor: orderedGovernors[v] })}
            description={govDesc}
          />
          {pstateCaps?.current_mode === "guided" && (
            <div style={{ padding: "8px 12px", color: "#ffb366", fontSize: "0.8em" }}>
              Warning: Governor is ignored in Guided mode. Switch the CPU
              Driver Mode (below) to "Active" for this setting to take
              effect.
            </div>
          )}
        </PanelSectionRow>
      )}
      {showEpp && (
        <PanelSectionRow>
          <LabeledSlider
            label="EPP"
            value={eppIdx}
            min={0}
            max={orderedEppOptions.length - 1}
            step={1}
            notches={orderedEppOptions.length}
            valueIcons={orderedEppOptions.map(eppIcon)}
            displayValue={eppName}
            onChange={(v) => applySettings({ epp: orderedEppOptions[v] })}
            description={eppDesc}
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
