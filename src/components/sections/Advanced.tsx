import { useState } from "react";
import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

import { useSettings } from "../../settings/SettingsProvider";
import { DescriptionRow } from "../shared";

export function AdvancedSection() {
  const { state, applySettings } = useSettings();
  const [showAdvanced, setShowAdvanced] = useState(false);
  if (!state) return null;
  const profile = state.current_profile;

  const wifi = profile.wifiPowerSave ?? false;
  const usb = profile.usbAutosuspend ?? false;
  const pcie = profile.pcieAspm ?? false;
  const pci = profile.pciRuntimePm ?? false;

  return (
    <PanelSection title="Advanced Power Management">
      <PanelSectionRow>
        <ToggleField
          label="Show Advanced Options"
          checked={showAdvanced}
          onChange={(v) => setShowAdvanced(v as boolean)}
        />
      </PanelSectionRow>
      {showAdvanced && (
        <>
          {state.device_info.supports_wifi_power_save && (
            <PanelSectionRow>
              <ToggleField
                label="WiFi Power Save"
                checked={wifi}
                onChange={(v) =>
                  applySettings({ wifiPowerSave: v as boolean })
                }
              />
            </PanelSectionRow>
          )}
          {state.device_info.supports_usb_power_mgmt && (
            <PanelSectionRow>
              <ToggleField
                label="USB Auto-suspend"
                checked={usb}
                onChange={(v) =>
                  applySettings({ usbAutosuspend: v as boolean })
                }
              />
            </PanelSectionRow>
          )}
          {state.device_info.supports_pcie_aspm && (
            <PanelSectionRow>
              <ToggleField
                label="PCIe ASPM"
                checked={pcie}
                onChange={(v) =>
                  applySettings({ pcieAspm: v as boolean })
                }
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ToggleField
              label="PCI Runtime PM"
              checked={pci}
              onChange={(v) =>
                applySettings({ pciRuntimePm: v as boolean })
              }
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DescriptionRow text="Toggling off will revert settings to OS defaults." />
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}
