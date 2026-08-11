import { useState } from "react";
import { PanelSection, PanelSectionRow, ButtonItem, ToggleField } from "@decky/ui";
import { FaSpinner, FaDownload, FaCog, FaCheckCircle, FaSearch, FaExclamationTriangle, FaBell } from "react-icons/fa";

import {
  checkForUpdates,
  stageUpdate,
  installStagedUpdate,
} from "../../api";

import { useSettings } from "../../settings/SettingsProvider";
type Phase =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "ready"
  | "installing"
  | "completed"
  | "error";

export function UpdatesSection() {
  const { state, setPerGameEnabled } = useSettings();
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string>("");
  const [info, setInfo] = useState<{ latest?: string; downloadUrl?: string } | null>(null);

  if (!state) return null;

  const busy = phase === "checking" || phase === "downloading" || phase === "installing";

  const handleButton = async () => {
    if (phase === "idle") {
      setPhase("checking");
      setMessage("Checking for updates...");
      const result = await checkForUpdates();
      if (result.error) {
        setPhase("error");
        setMessage(`Check failed: ${result.error}`);
        return;
      }
      if (result.update_available) {
        setPhase("available");
        setMessage(`Update available: ${result.current_version} -> ${result.latest_version}`);
        setInfo({ latest: result.latest_version, downloadUrl: result.download_url });
      } else {
        setPhase("idle");
        setMessage(`Latest version installed: ${result.current_version}`);
        setTimeout(() => setMessage(""), 3000);
      }
    } else if (phase === "available" && info?.downloadUrl && info.latest) {
      setPhase("downloading");
      setMessage("Downloading update...");
      const r = await stageUpdate(info.downloadUrl, info.latest);
      if (r.success) {
        setPhase("ready");
        setMessage(`Update ready to install: ${info.latest}`);
      } else {
        setPhase("error");
        setMessage(`Download failed: ${r.error || "unknown error"}`);
      }
    } else if (phase === "ready") {
      setPhase("installing");
      setMessage("Installing update...");
      const r = await installStagedUpdate();
      if (r.success) {
        setPhase("completed");
        setMessage(`Updated to ${info?.latest}! Plugin loader will restart.`);
        setTimeout(() => {
          setPhase("idle");
          setMessage("");
          setInfo(null);
        }, 5000);
      } else {
        setPhase("error");
        setMessage(`Install failed: ${r.error || "unknown error"}`);
      }
    } else if (phase === "error") {
      setPhase("idle");
      setMessage("");
      setInfo(null);
    }
  };

  const buttonLabel = () => {
    switch (phase) {
      case "checking":
        return (
          <>
            <FaSpinner style={{ animation: "spin 1s linear infinite", marginRight: 6 }} />
            Checking for Updates...
          </>
        );
      case "available":
        return (
          <>
            <FaDownload style={{ marginRight: 6 }} />
            Download Update
          </>
        );
      case "downloading":
        return (
          <>
            <FaSpinner style={{ animation: "spin 1s linear infinite", marginRight: 6 }} />
            Downloading...
          </>
        );
      case "ready":
        return (
          <>
            <FaCog style={{ marginRight: 6 }} />
            Install Update
          </>
        );
      case "installing":
        return (
          <>
            <FaCog style={{ animation: "spin 1s linear infinite", marginRight: 6 }} />
            Installing...
          </>
        );
      case "completed":
        return (
          <>
            <FaCheckCircle style={{ marginRight: 6 }} />
            Update Complete!
          </>
        );
      case "error":
        return (
          <>
            <FaExclamationTriangle style={{ marginRight: 6 }} />
            Retry Update
          </>
        );
      default:
        return (
          <>
            <FaSearch style={{ marginRight: 6 }} />
            Check for Updates
          </>
        );
    }
  };

  const messageColor = phase === "error" ? "#ff6b6b" : phase === "completed" ? "#51cf66" : "#868e96";
  const footerColor = state.update_status.update_available
    ? "#ff6b35"
    : phase === "checking"
    ? "#4a9eff"
    : "#4a9eff";

  return (
    <>
      <PanelSection title="Plugin Management">
        <PanelSectionRow>
          <ToggleField
            label="Per-Game Profiles"
            description="Enable different power settings for each game"
            checked={state.per_game_profiles_enabled}
            onChange={(v) => setPerGameEnabled(v as boolean)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={handleButton}>
            {buttonLabel()}
          </ButtonItem>
          {message && (
            <div
              style={{
                fontSize: "0.85em",
                color: messageColor,
                textAlign: "center",
                marginTop: 8,
                padding: "4px 8px",
                borderRadius: 4,
                backgroundColor: "rgba(255,255,255,0.05)",
              }}
            >
              {message}
            </div>
          )}
        </PanelSectionRow>
      </PanelSection>

      <PanelSection>
        <PanelSectionRow>
          <div
            style={{
              fontSize: "1.0em",
              color: "#ccc",
              textAlign: "center",
              padding: "0 0 8px 0",
              marginTop: -4,
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            <div style={{ fontWeight: 500 }}>PowerDeck v{state.plugin_version}</div>
            <div
              style={{
                fontSize: "0.9em",
                color: footerColor,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
              }}
            >
              {phase === "checking" ? (
                <>
                  <FaSpinner style={{ animation: "spin 1s linear infinite" }} />
                  Checking for updates...
                </>
              ) : state.update_status.update_available ? (
                <>
                  <FaBell />
                  Update v{state.update_status.latest_version} available
                </>
              ) : (
                <>
                  <FaCheckCircle />
                  Up to date
                </>
              )}
              {state.update_status.hours_since_last_check !== null && phase !== "checking" && (
                <div
                  style={{
                    fontSize: "0.8em",
                    color: "#888",
                    marginTop: 2,
                    fontStyle: "italic",
                  }}
                >
                  Last checked: {Math.round(state.update_status.hours_since_last_check * 10) / 10}h ago
                </div>
              )}
            </div>
          </div>
        </PanelSectionRow>
      </PanelSection>

      <style>{`@keyframes spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
