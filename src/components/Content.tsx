import { PanelSection, PanelSectionRow } from "@decky/ui";

import { SettingsProvider, useSettings } from "../settings/SettingsProvider";
import { DeviceStatusSection } from "./sections/DeviceStatus";
import { CoolingSection } from "./sections/Cooling";
import { RogAllyFansSection } from "./sections/RogAllyFans";
import { TdpSection } from "./sections/Tdp";
import { PlatformProfileSection } from "./sections/PlatformProfile";
import { RogAllyThermalSection } from "./sections/RogAllyThermal";
import { CpuSection } from "./sections/Cpu";
import { GpuSection } from "./sections/Gpu";
import { BatterySection } from "./sections/Battery";
import { ControllerSection } from "./sections/Controller";
import { AdvancedSection } from "./sections/Advanced";
import { RogAllyExtrasSection } from "./sections/RogAllyExtras";
import { UpdatesSection } from "./sections/Updates";

function Sections() {
  const { state, loading, error } = useSettings();

  if (loading) {
    return (
      <PanelSection title="PowerDeck">
        <PanelSectionRow>
          <div style={{ padding: 20, textAlign: "center" }}>Loading PowerDeck...</div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  if (error || !state) {
    return (
      <PanelSection title="PowerDeck">
        <PanelSectionRow>
          <div style={{ padding: 20, color: "#ff6b6b" }}>
            {error || "Unable to load PowerDeck state"}
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const device = state.device_info;
  const caps = state.capabilities;
  const isRogAlly = !!(caps.rog_ally?.device_name);
  // A watt slider is only honest when a real watt backend is reachable.
  // "platform_profile" owns EC fan and power policy; on hardware where
  // ryzenadj also works (Emdoor N161L / Strix Halo) the platform profile
  // never writes the SMU power limit, so it cannot back this slider.
  const tdpMethod = caps.tdp_control.method;
  const hasWattControl =
    caps.tdp_control.available && (tdpMethod === "native_tdp" || tdpMethod === "intel_rapl");

  return (
    <>
      <DeviceStatusSection />

      {device.has_fan_control && !isRogAlly && <CoolingSection />}
      {isRogAlly && caps.rog_ally?.available_controls?.fan_control && <RogAllyFansSection />}

      {hasWattControl && <TdpSection />}
      {!caps.tdp_control.available && caps.tdp_control.has_soft_control && <TdpSection softMode />}
      {device.powerControl?.platform_profile_available && <PlatformProfileSection />}

      {isRogAlly && caps.rog_ally?.available_controls?.thermal_policy && <RogAllyThermalSection />}

      <CpuSection />
      <GpuSection />

      {device.battery_charge_limit_available && <BatterySection />}
      {caps.controller.available && <ControllerSection />}

      {isRogAlly && caps.rog_ally?.available_controls?.mcu_powersave && <RogAllyExtrasSection />}

      <AdvancedSection />
      <UpdatesSection />
    </>
  );
}

export function Content() {
  return (
    <SettingsProvider>
      <Sections />
    </SettingsProvider>
  );
}
