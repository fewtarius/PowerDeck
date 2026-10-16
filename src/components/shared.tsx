import { ReactNode, useCallback, useEffect, useState } from "react";
import { SliderField } from "@decky/ui";
import { FaBatteryEmpty, FaBatteryThreeQuarters, FaBullseye, FaCog, FaChartBar, FaFire,
  FaBatteryFull, FaBatteryHalf, FaRocket, FaSyncAlt, FaMicrochip,
  FaLightbulb, FaThermometerHalf, FaGamepad, FaPause, FaSlidersH,
  FaVolumeOff, FaBalanceScale, FaXbox, FaPlaystation } from "react-icons/fa";

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

// ── Icon helpers ─────────────────────────────────────────────────────
// One icon per discrete position of a categorical slider. The active
// (selected) icon is rendered tinted with COLORS.accent so the user gets
// a persistent visual anchor for "where am I" without reading the label.
// These mirror the colour/icon language of the pre-rewrite UI so the
// panel keeps its established visual vocabulary.
export function governorIcon(governor: string): ReactNode {
  switch (governor) {
    case "powersave": return <FaBatteryThreeQuarters />;
    case "conservative": return <FaLightbulb />;
    case "ondemand": return <FaChartBar />;
    case "schedutil": return <FaCog />;
    case "performance": return <FaRocket />;
    default: return <FaCog />;
  }
}

export function eppIcon(epp: string): ReactNode {
  switch (epp) {
    case "power": return <FaBatteryEmpty />;
    case "balance_power": return <FaBatteryHalf />;
    case "balance_performance": return <FaChartBar />;
    case "performance": return <FaRocket />;
    case "default": return <FaCog />;
    case "custom": return <FaSlidersH />;
    default: return <FaBatteryHalf />;
  }
}

export function gpuModeIcon(mode: string): ReactNode {
  switch (mode) {
    case "battery": return <FaBatteryHalf />;
    case "auto": return <FaSyncAlt />;
    case "performance": return <FaRocket />;
    case "range": return <FaSlidersH />;
    case "fixed": return <FaBullseye />;
    default: return <FaSyncAlt />;
  }
}

export function coolingIcon(profile: string): ReactNode {
  switch (profile) {
    case "auto": return <FaCog />;
    case "quiet": return <FaVolumeOff />;
    case "moderate": return <FaBalanceScale />;
    case "aggressive": return <FaFire />;
    default: return <FaCog />;
  }
}

export function pstateIcon(mode: string): ReactNode {
  switch (mode) {
    case "active": return <FaRocket />;
    case "passive": return <FaPause />;
    case "guided": return <FaSlidersH />;
    default: return <FaCog />;
  }
}

export function thermalPolicyIcon(policy: number): ReactNode {
  switch (policy) {
    case 0: return <FaThermometerHalf />;
    case 1: return <FaBalanceScale />;
    case 2: return <FaFire />;
    case 3: return <FaRocket />;
    default: return <FaThermometerHalf />;
  }
}

export function platformProfileIcon(profile: string): ReactNode {
  if (profile === "power-saver" || profile === "low-power") return <FaBatteryFull />;
  if (profile === "performance") return <FaRocket />;
  return <FaBalanceScale />;
}

export function controllerIcon(mode: string): ReactNode {
  // Re-exported from api labels; kept here so the icon set lives with
  // the rest of the shared iconography rather than the callable layer.
  switch (mode) {
    case "deck-uhid": return <FaMicrochip />;
    case "xbox-series":
    case "xbox-elite": return <FaXbox />;
    case "ds5-edge":
    case "ds5": return <FaPlaystation />;
    default: return <FaGamepad />;
  }
}

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
  /** Optional icon per discrete position (categorical sliders). When
   * provided, a row of icon notches is rendered beneath the slider and
   * the icon for the active position is tinted COLORS.accent, giving the
   * user a persistent visual anchor for "where am I" without reading the
   * label. Matches the colour/icon language of the pre-rewrite UI. */
  valueIcons?: ReactNode[];
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
 * so the slider looks like a step selector.
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
  valueIcons,
}: LabeledSliderProps) {
  // Mirror value in local state so the slider thumb follows the user's
  // drag immediately. Without this, the controlled SliderField snaps back
  // to the prop value (which only updates after the async backend
  // round-trip + refresh completes), making every slider feel stuck or
  // sluggish. The prop is still the source of truth on external changes
  // (profile switch, AC toggle) via the useEffect below.
  const [internalValue, setInternalValue] = useState(value);

  // Sync from prop when it changes externally. During an active drag
  // the prop hasn't changed yet, so this doesn't fight the user's input.
  useEffect(() => {
    setInternalValue(value);
  }, [value]);

  const handleChange = useCallback(
    (newValue: number) => {
      setInternalValue(newValue);
      onChange(newValue);
    },
    [onChange]
  );

  const inline = displayValue ?? `${internalValue}${valueSuffix}`;
  return (
    <>
      <SliderField
        label={`${label}:`}
        value={internalValue}
        min={min}
        max={max}
        step={step}
        notchTicksVisible={!!notches}
        bottomSeparator="none"
        onChange={handleChange}
      />
      {valueIcons && valueIcons.length > 0 ? (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "2px 12px 4px",
            pointerEvents: "none",
          }}
          aria-hidden="true"
        >
          {valueIcons.map((ic, i) => (
            <span
              key={i}
              style={{
                color:
                  i === Math.round(internalValue) && internalValue >= min && internalValue <= max
                    ? COLORS.accent
                    : COLORS.textTertiary,
                fontSize: "1.1em",
                opacity:
                  i === Math.round(internalValue) && internalValue >= min && internalValue <= max
                    ? 1
                    : 0.5,
                transition: "color 0.16s ease, opacity 0.16s ease",
              }}
            >
              {ic}
            </span>
          ))}
        </div>
      ) : (
        // Numeric sliders have no valueIcons row — show the current
        // value right-justified below the slider so the user always sees
        // the active setting (e.g. "15W", "3 / 8").
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            fontSize: "0.85em",
            color: COLORS.textSecondary,
            padding: "2px 12px 4px",
          }}
        >
          <span>{inline}</span>
        </div>
      )}
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
