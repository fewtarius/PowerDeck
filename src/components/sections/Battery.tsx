import { useState } from "react";
import type { ReactNode } from "react";
import { PanelSection, PanelSectionRow } from "@decky/ui";
import { FaBatteryEmpty, FaBatteryHalf, FaBatteryFull } from "react-icons/fa";

import { useSettings } from "../../settings/SettingsProvider";
import { LabeledSlider } from "../shared";
import { setBatteryChargeLimit } from "../../api";

function chargePreset(pct: number): { name: string } {
  if (pct <= 60) return { name: "Battery-Friendly" };
  if (pct <= 80) return { name: "Balanced" };
  return { name: "Full Charge" };
}

// A small icon notcheset for the charge-limit slider: low/mid/high.
// The slider maps 20-100 in 5-step increments so there are 17 notches;
// we surface three representative icons at the low (20% battery-friendly),
// mid (80% balanced), and high (100% full) positions.
const CHARGE_NOTCH_VALUES = [20, 80, 100];
const CHARGE_NOTCH_ICONS = [<FaBatteryEmpty />, <FaBatteryHalf />, <FaBatteryFull />];
const CHARGE_STEP = 5;
const CHARGE_MIN = 20;
const CHARGE_MAX = 100;

function chargeNotchIcon(value: number): ReactNode {
  if (value <= 60) return CHARGE_NOTCH_ICONS[0]; // battery-friendly
  if (value <= 80) return CHARGE_NOTCH_ICONS[1]; // balanced
  return CHARGE_NOTCH_ICONS[2]; // full charge
}

export function BatterySection() {
  const { state, refresh } = useSettings();
  const [pending, setPending] = useState<number | null>(null);
  if (!state) return null;

  const current = state.capabilities.battery_charge_limit ?? 100;
  const value = pending ?? current;
  const preset = chargePreset(value);
  const notchCount = Math.floor((CHARGE_MAX - CHARGE_MIN) / CHARGE_STEP) + 1;

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
          min={CHARGE_MIN}
          max={CHARGE_MAX}
          step={CHARGE_STEP}
          notches={notchCount}
          valueIcons={Array.from({ length: notchCount }, (_, i) =>
            CHARGE_NOTCH_VALUES.includes(CHARGE_MIN + i * CHARGE_STEP)
              ? CHARGE_NOTCH_ICONS[CHARGE_NOTCH_VALUES.indexOf(CHARGE_MIN + i * CHARGE_STEP)]
              : null
          )}
          icon={chargeNotchIcon(value)}
          displayValue={`${value}% (${preset.name})`}
          onChange={(v) => handleChange(v)}
          description="Range: 20-100%"
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
