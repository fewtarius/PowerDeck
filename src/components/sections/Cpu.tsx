import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider, governorIcon, eppIcon } from "../shared";
import { EPP_DESCRIPTIONS, EPP_VALUES, GOVERNOR_DESCRIPTIONS, getOrderedGovernors } from "../../api";

export function CpuSection() {
  const { state, applySettings } = useSettings();
  if (!state) return null;

  const device = state.device_info;
  const profile = state.current_profile;
  const orderedGovernors = getOrderedGovernors(state.capabilities.governors);
  const pstateCaps = state.capabilities.pstate;
  // platform_profile hands CPU control entirely to the platform firmware;
  // hide governor + EPP to avoid stomping the platform's decisions.
  // native_tdp (ryzenadj) and "none" let us control EPP/governor freely.
  const isPlatformManaged = device.powerControl?.active_method === "platform_profile";
  // Governor is relevant on all drivers when not platform-managed:
  // on amd-pstate-epp it gates the EPP hint set (performance governor
  // silently restricts EPP to 'performance'), and on classic amd-pstate
  // it's the primary control surface in passive/guided mode. Show the
  // governor selector whenever the kernel exposes more than one option;
  // a single governor (e.g. only 'performance') offers nothing to choose.
  const showGovernor = !isPlatformManaged && orderedGovernors.length > 1;
  // Show EPP controls whenever the backend reports EPP as available —
  // this covers both amd-pstate-epp (always, in active mode) and
  // classic amd-pstate (active mode exposes per-CPU EPP sysfs files).
  // EPP is only honored in active mode, so the backend gates
  // epp_available on current_mode=="active"; the slider therefore
  // appears/disappears with the mode automatically.
  const showEpp = (pstateCaps?.epp_available ?? false) && !isPlatformManaged;

  const maxCores = device.max_cpu_cores || 16;
  const cpuCoresMax = profile.smt ? maxCores : Math.floor(maxCores / 2);

  const governorIdx = Math.max(0, orderedGovernors.indexOf(profile.governor));
  const govName = orderedGovernors[governorIdx] ?? profile.governor;
  // Description must track the *displayed* (snapped) governor, not the
  // raw profile value: when the profile holds a governor the kernel
  // doesn't expose (e.g. "schedutil" under amd-pstate-epp active where
  // only powersave/performance exist) the slider snaps to index 0 but
  // the description still read the stale profile value.
  const govDesc = GOVERNOR_DESCRIPTIONS[govName] ?? GOVERNOR_DESCRIPTIONS[profile.governor] ?? "";

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
  const eppIdx = Math.max(0, orderedEppOptions.indexOf(profile.epp as string));
  const eppName = orderedEppOptions[eppIdx] ?? profile.epp;
  const eppDesc = EPP_DESCRIPTIONS[eppName as string] ?? EPP_DESCRIPTIONS[profile.epp as string] ?? "";

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
