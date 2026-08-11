# PowerDeck Frontend Style Guide

How to lay out panels so users can see what their hardware is doing at a
glance. The previous revision's UI was praised for surfacing current
values and ranges everywhere - this guide is the contract that keeps
the new layout matching that bar.

## TL;DR

- Every **numeric** slider shows its current value inline in the label
  (`TDP: 15W`) and an optional range line under it (`Range: 4-30W`).
- Every **categorical** slider has **no slider label** - it relies on
  notches + icons for the visual, and a `DescriptionRow` below for the
  friendly name. Multi-slider categorical sections (e.g. ROG Ally
  fans) label each slider so users can tell them apart.
- `DescriptionRow` text follows `<name> - <description>` when both
  exist (`balanced - Balanced`), `<name>` alone when only the raw
  key maps to anything worth showing, and `<description>` alone when
  the raw key is meaningless (e.g. controller modes).
- Use `LabeledSlider` for numeric, `SliderWithIcons` for categorical,
  plain `SliderField` only when neither helper fits.
- Icons live in `components/sections/*`. Cross-section helpers and
  the colour palette live in `components/shared.tsx`.

## Section anatomy

Every section follows the same skeleton:

```tsx
<PanelSection title="CPU Control">
  <PanelSectionRow>
    {/* primary control */}
  </PanelSectionRow>
  <PanelSectionRow>
    {/* secondary information: range, description, status */}
  </PanelSectionRow>
</PanelSection>
```

- Title is short and action-oriented. No emoji, no period.
  "TDP Control", "GPU Control", "Cooling Profile", "Battery Management".
- Return `null` early when `state` is unloaded. Never render
  half-loaded controls.
- Capability-gate inside the section, not behind a wrapper. The new
  `state.capabilities` blob is the single source of truth.

## Controls

### Numeric sliders - `LabeledSlider`

Use for any continuous value:

| Field        | Suffix     | Example label         |
|--------------|-----------|-----------------------|
| TDP          | `W`       | `TDP: 15W`            |
| GPU freq     | `MHz`     | `GPU Min Freq: 800MHz`|
| CPU cores    | (none)    | `CPU Cores: 8`        |
| Charge limit | `%`       | `Charge Limit: 80%`   |

```
┌─────────────────────────────┐
│  TDP: 15W                   │
│  ●━━━━━━━━━━━━━●━━━━━━━━━●  │
│             Watts    Range: 3-30W
└─────────────────────────────┘
```

Implementation:

```tsx
<PanelSectionRow>
  <LabeledSlider
    label="TDP"
    value={tdp}
    min={min}
    max={max}
    step={1}
    suffix="W"
    rangeSuffix="W"
    description="Watts"
    onChange={(v) => applySettings({ tdp: v })}
  />
</PanelSectionRow>
```

The `description` is a small left-aligned hint ("Watts",
"Mapped to governor + EPP"). The `Range: min-max<unit>` row goes on
the right. Together they give users enough to pick a useful value
without trial-and-error.

### Categorical sliders - `SliderWithIcons`

Use when the user is picking between named options that have natural
icons:

- Cooling profile (Auto / Quiet / Balanced / Aggressive)
- Platform profile (power-saver / balanced / performance)
- Thermal policy (Quiet / Balanced / Aggressive / Performance)
- CPU governor or EPP
- ROG Ally fan mode (Stop / Spin)
- Battery charge limit (Empty / Half / Full)
- Controller emulation mode
- P-state mode

```
┌──────────────────────────────────┐
│        [balance]                 │
│  ●━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━ │
│     [cog] [mute] [balance] [fan]  │
│  [balance] Moderate - Balanced cooling
└──────────────────────────────────┘
```

The active notch's icon is highlighted in cyan. The slider itself
has **no label** (the icons carry the meaning). A `DescriptionRow`
under the slider names the active choice in plain language:
`<displayName> - <description>`.

If a section has multiple categorical sliders (e.g. ROG Ally fans
have CPU + GPU), each slider gets a short label so the user knows
which is which, and no `DescriptionRow` - the slider label plus the
highlighted notch icon is enough.

Always pair a single-control `SliderWithIcons` with a `DescriptionRow`
when the active choice has a friendly name + description. If only
the raw key exists (e.g. unfamiliar 3rd-party IDs), just show the key
on its own.

### Toggles - `ToggleField`

```tsx
<ToggleField
  label="USB Auto-suspend"
  description="May disrupt some peripherals"
  checked={value}
  onChange={(v) => applySettings({ usbAutosuspend: v })}
/>
```

- Short imperative labels. No question marks, no trailing colons.
- Use `description` for warnings, tradeoffs, and what the toggle
  actually does (when it isn't obvious from the label).
- Don't add a caption below the toggle - the description should be
  enough.

### Info display - `InfoRow`

Two-column key/value display for static or slowly-changing data:

```tsx
<InfoRow
  icon={<FaPlug />}
  label="Power"
  value={state.ac_power ? "AC Connected" : "On Battery"}
  valueColor={state.ac_power ? COLORS.statusOk : COLORS.statusWarn}
/>
```

Use for:
- Device / model
- Power source (green when AC, amber on battery)
- Active profile / active game
- TDP range (so users see what the slider's been capped at)
- Battery charge limit (with the percentage styled as a status)

Avoid using `InfoRow` for things the user can change - those should
be controls.

### Status display - `DescriptionRow`

Plain-language explanation beneath a control:

```tsx
<DescriptionRow
  icon={<FaBalanceScale />}
  text={`${profile.governor} - ${GOVERNOR_DESCRIPTIONS[profile.governor]}`}
/>
```

The leading icon is always `COLORS.accent` so the row reads as an
inline help bubble.

## Section ordering

Order inside the panel, top to bottom:

1. **Device Status** - glanceable device + power source + active profile
2. **TDP Control** - the headline control on every handheld
3. **CPU Control** - cores, SMT, boost, governor, EPP
4. **GPU Control** - power mode + frequency sliders
5. **Cooling Profile**
6. **Platform Profile** (when the device exposes one and TDP control
   is not)
7. **Battery Management** (when supported)
8. **ROG Ally** sections (Platform Profile / Thermal / Fans /
   Extras) - capability-gated, only the ones the device actually has
9. **Advanced Power Management** (collapsed by default)
10. **Controller** (when InputPlumber is available)
11. **Per-Game Profiles** toggle (last so it's discoverable but not
    intrusive)
12. **Updates**

## Colour palette

All colours are exported from `components/shared.tsx` as the `COLORS`
constant. Reuse these - don't inline hex values in sections.

| Token              | Value     | Use                              |
|--------------------|-----------|----------------------------------|
| `COLORS.accent`    | `#00d4ff` | Active notch, icons, highlights  |
| `COLORS.statusOk`  | `#4CAF50` | AC connected, healthy state      |
| `COLORS.statusWarn`| `#FF9800` | On battery, attention needed     |
| `COLORS.statusError`| `#F44336`| Hardware write failed            |
| `COLORS.textPrimary`  | `#ffffff` | Default body text            |
| `COLORS.textSecondary`| `#888`    | Captions, descriptions        |
| `COLORS.textTertiary` | `#666`    | Footnotes, legalese           |

## Iconography

Icons come from `react-icons/fa` (FontAwesome solid). Don't reach for
emoji - they look out of place in the SteamOS overlay.

Semantic mapping (use these consistently):

| Concept            | Icon                      |
|--------------------|---------------------------|
| Battery save       | `FaBatteryFull` / `FaBatteryThreeQuarters` |
| Balanced           | `FaBalanceScale`          |
| Performance        | `FaRocket`                |
| Quiet / passive    | `FaVolumeOff`             |
| Cooling            | `FaFan` / `FaCog`         |
| Thermal            | `FaThermometerHalf` / `FaFire` |
| Aggressive         | `FaFire`                  |
| Device / chip      | `FaMicrochip`             |
| Power source       | `FaPlug`                  |
| Active game        | `FaGamepad`               |
| Profile (default)  | `FaShieldAlt`             |
| Range / slider     | `FaTachometerAlt`         |
| Range mode         | `FaSlidersH`              |
| Fixed mode         | `FaBullseye`              |
| Auto / dynamic     | `FaSyncAlt`               |

## What NOT to do

- Bare `SliderField` with no suffix and no value inline. The user
  shouldn't have to drag to find out what number is selected.
- Categorical controls without a `DescriptionRow`. The icons alone
  aren't enough context.
- Inlined hex colours - import from `COLORS` in `shared.tsx`.
- Modules under `components/sections/` importing from each other.
  Shared concerns go in `shared.tsx` or `api.ts`.
- Hand-rolled wrapping `<div>` styling for things `InfoRow` /
  `DescriptionRow` / `LabeledSlider` already cover.
- React hooks (`useState`, `useEffect`) outside `SettingsProvider`
  for state that should live in the backend.

## Adding a new control

Checklist for a new section file under `components/sections/`:

1. Pull state with `useSettings()`. Return `null` if not loaded.
2. Capability-gate on `state.capabilities` or `state.device_info`.
3. Pick the right primitive:
   - Numeric continuous -> `LabeledSlider`
   - Categorical / named options -> `SliderWithIcons` + `DescriptionRow`
   - On/off -> `ToggleField`
4. Wire `onChange` to `applySettings({ key: value })`. Don't call
   `await` on individual backends - `applySettings` is the only write
   path.
5. Cross-reference icons from the semantic table above.
6. Add it to the section ordering list above if it's a new top-level
   section.

## Touching the wire format

When the backend adds a new field:

- Add the field to `PowerProfile` in `src/types.ts`.
- Add a description entry in `api.ts` if it has a categorical
  mapping.
- Add a UI control in the relevant section component using the right
  primitive.
- If it's a new top-level capability, add it to `BackendState.capabilities`
  in `types.ts` and surface it in Device Status if it's glanceable.
