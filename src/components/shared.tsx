import { ReactNode } from "react";
import { SliderField } from "@decky/ui";

// Accent colors used across the UI. Keep these in sync with the
// inline styles in components/sections/* - one-off hex values
// outside this palette are flagged during code review.
export const COLORS = {
  accent: "#00d4ff",          // cyan - active notch / highlight
  textPrimary: "#ffffff",
  textSecondary: "#888",
  textTertiary: "#666",
  statusOk: "#4CAF50",        // green - AC power, healthy state
  statusWarn: "#FF9800",      // amber - battery, attention
  statusError: "#F44336",     // red - error / failed
} as const;

interface LabeledSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  description?: string;
  valueSuffix?: string;
  notches?: number;
  displayValue?: string;
  icon?: ReactNode;
}

/**
 * Renders the canonical control layout used by every slider in the
 * panel:
 *
 *     [ICON] <Label>: <displayValue>     <-- SliderField inline label
 *                          <description>   <-- right-justified below
 *
 * displayValue defaults to `${value}${valueSuffix}` - the raw number
 * for numeric controls ("TDP: 15W"). For categorical controls, pass
 * the friendly name of the current option ("Cooling: Auto") so the
 * user sees the choice rather than its index.
 *
 * The description is right-justified on a single line below the
 * slider. For numeric controls, that's "Range: 4-25W". For
 * categorical controls, that's the friendly description ("Auto-scales
 * with workload").
 *
 * Pass `notches` to render discrete tick marks at each notch position
 * so the slider looks like a step selector. `icon` is rendered on
 * the left of the slider to give the user a visual anchor for what
 * the slider controls (CPU, GPU, fan, etc.).
 */
export function LabeledSlider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  description,
  valueSuffix = "",
  notches,
  displayValue,
  icon,
}: LabeledSliderProps) {
  const inline = displayValue ?? `${value}${valueSuffix}`;
  return (
    <>
      <SliderField
        label={`${label}: ${inline}`}
        value={value}
        min={min}
        max={max}
        step={step}
        notchTicksVisible={!!notches}
        bottomSeparator="none"
        icon={icon}
        onChange={onChange}
      />
      {description && (
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            fontSize: "0.8em",
            color: COLORS.textSecondary,
            padding: "2px 12px 8px",
          }}
        >
          <span>{description}</span>
        </div>
      )}
    </>
  );
}

interface DescriptionRowProps {
  text: string;
}

/**
 * Plain-language explanation under a control. Right-justified on a
 * single line. Use for toggles that don't have their own slider.
 */
export function DescriptionRow({ text }: DescriptionRowProps) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
        fontSize: "0.8em",
        color: COLORS.textSecondary,
        padding: "2px 12px 8px",
      }}
    >
      <span>{text}</span>
    </div>
  );
}

interface InfoRowProps {
  icon?: ReactNode;
  label: string;
  value: string;
  valueColor?: string;
}

/**
 * Two-column key/value display. Use for device metadata (Device,
 * Power source, Profile, Capacity) where the user wants to glance at
 * status without taking an action.
 */
export function InfoRow({ icon, label, value, valueColor = COLORS.textPrimary }: InfoRowProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 4px",
      }}
    >
      {icon && (
        <span style={{ color: COLORS.accent, fontSize: "1em", width: 16 }}>{icon}</span>
      )}
      <span style={{ fontSize: "0.85em", color: COLORS.textSecondary, minWidth: 60 }}>
        {label}:
      </span>
      <span
        style={{
          fontSize: "0.85em",
          color: valueColor,
          fontWeight: 500,
          wordBreak: "break-word",
        }}
      >
        {value}
      </span>
    </div>
  );
}

interface StatusBadgeProps {
  text: string;
  color: string;
  icon?: ReactNode;
}

/**
 * Inline status pill - used in Device Status for things like
 * "AC Connected" / "On Battery" / "Active Game: Hades".
 */
export function StatusBadge({ text, color, icon }: StatusBadgeProps) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 3,
        backgroundColor: `${color}22`,
        color,
        fontSize: "0.8em",
        fontWeight: 500,
      }}
    >
      {icon}
      {text}
    </span>
  );
}
