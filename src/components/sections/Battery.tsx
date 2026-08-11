import { useState } from "react";
import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaBatteryFull } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";
import { setBatteryChargeLimit } from "../../api";

function chargePreset(pct: number): { name: string } {
  if (pct <= 60) return { name: "Battery-Friendly" };
  if (pct <= 80) return { name: "Balanced" };
  return { name: "Full Charge" };
}

export function BatterySection() {
  const { state, refresh } = useSettings();
  const [pending, setPending] = useState<number | null>(null);
  if (!state) return null;

  const current = state.capabilities.battery_charge_limit ?? 100;
  const value = pending ?? current;
  const preset = chargePreset(value);

  const handleChange = async (next: number) => {
    setPending(next);
    const ok = await setBatteryChargeLimit(next);
    setPending(null);
    if (ok) await refresh();
  };

  return (
    <PanelSection title="Battery Management">
      <PanelSectionRow>
        <LabeledSlider
          label="Charge Limit"
          value={value}
          min={20}
          max={100}
          step={5}
          icon={<FaBatteryFull />}
          displayValue={`${value}% (${preset.name})`}
          onChange={(v) => handleChange(v)}
          description="Range: 20-100%"
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
