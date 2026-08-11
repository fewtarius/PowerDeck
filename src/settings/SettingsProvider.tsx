import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Router } from "@decky/ui";

import {
  applySettings as applySettingsApi,
  getAcPowerStatus as getAcPowerStatusApi,
  getState as getStateApi,
  setControllerMode as setControllerModeApi,
  setRogAllyFanMode as setRogAllyFanModeApi,
  setRogAllyMcuPowersave as setRogAllyMcuPowersaveApi,
  setRogAllyPlatformProfile as setRogAllyPlatformProfileApi,
  setPerGameProfilesEnabled as setPerGameEnabledApi,
} from "../api";
import { BackendState, PowerProfile } from "../types";

export interface SettingsContextValue {
  state: BackendState | null;
  loading: boolean;
  error: string | null;

  applySettings: (
    partial: Partial<PowerProfile>,
    opts?: { immediate?: boolean; targetProfileId?: string }
  ) => Promise<boolean>;

  setPerGameEnabled: (enabled: boolean) => Promise<void>;
  setControllerMode: (mode: string) => Promise<void>;

  setRogAllyThermalPolicy: (policy: number) => Promise<boolean>;
  setRogAllyFanMode: (fanId: number, mode: number) => Promise<boolean>;
  setRogAllyMcuPowersave: (enabled: boolean) => Promise<boolean>;
  setRogAllyPlatformProfile: (profile: string) => Promise<boolean>;

  refresh: () => Promise<void>;
}

const SettingsContext = createContext<SettingsContextValue>(null as unknown as SettingsContextValue);

export function useSettings(): SettingsContextValue {
  return useContext(SettingsContext);
}

interface DebouncedPending {
  partial: Partial<PowerProfile>;
  targetProfileId?: string;
  resolve: (ok: boolean) => void;
}

const DEBOUNCE_MS = 200;
const POLL_INTERVAL_MS = 5000;

function currentGameId(): { id: string; name: string } {
  const appId = Router.MainRunningApp?.appid || "default";
  const displayName = Router.MainRunningApp?.display_name || "Default";
  let id = appId;
  if (displayName !== "Default" && displayName !== "Steam") {
    const clean = displayName.replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
    if (clean && (appId === "default" || appId === "00000000" || appId.length < 3)) {
      let hash = 0;
      for (let i = 0; i < clean.length; i++) {
        hash = (hash << 5) - hash + clean.charCodeAt(i);
        hash |= 0;
      }
      id = `nonsteam_${Math.abs(hash)}`;
    }
  }
  return { id, name: displayName };
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<BackendState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const stateRef = useRef<BackendState | null>(null);
  stateRef.current = state;

  const refresh = useCallback(async () => {
    try {
      const next = await getStateApi();
      setState(next);
      setError(null);
    } catch (e) {
      setError(`Failed to load state: ${e}`);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const next = await getStateApi();
        setState(next);
      } catch (e) {
        setError(`Failed to load state: ${e}`);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const applyImmediate = useCallback(
    async (partial: Partial<PowerProfile>, targetProfileId?: string): Promise<boolean> => {
      try {
        const payload: any = { ...partial };
        if (targetProfileId) payload.target_profile_id = targetProfileId;
        const ok = await applySettingsApi(payload);
        if (ok) {
          await refresh();
        }
        return ok;
      } catch (e) {
        setError(`Failed to apply: ${e}`);
        return false;
      }
    },
    [refresh]
  );

  const pendingRef = useRef<DebouncedPending | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushPending = useCallback(async () => {
    const pending = pendingRef.current;
    pendingRef.current = null;
    if (!pending) return;
    const ok = await applyImmediate(pending.partial, pending.targetProfileId);
    pending.resolve(ok);
  }, [applyImmediate]);

  const applySettings = useCallback(
    (
      partial: Partial<PowerProfile>,
      opts?: { immediate?: boolean; targetProfileId?: string }
    ): Promise<boolean> => {
      return new Promise((resolve) => {
        const immediate = opts?.immediate === true;
        const targetProfileId = opts?.targetProfileId;
        if (immediate) {
          resolve(applyImmediate(partial, targetProfileId));
          return;
        }
        const combined: Partial<PowerProfile> = pendingRef.current
          ? { ...pendingRef.current.partial, ...partial }
          : { ...partial };
        pendingRef.current = {
          partial: combined,
          targetProfileId: targetProfileId ?? pendingRef.current?.targetProfileId,
          resolve,
        };
        if (debounceTimer.current) clearTimeout(debounceTimer.current);
        debounceTimer.current = setTimeout(() => {
          debounceTimer.current = null;
          flushPending();
        }, DEBOUNCE_MS);
      });
    },
    [applyImmediate, flushPending]
  );

  const setPerGameEnabled = useCallback(
    async (enabled: boolean) => {
      const ok = await setPerGameEnabledApi(enabled);
      if (ok) await refresh();
    },
    [refresh]
  );

  const setControllerMode = useCallback(
    async (mode: string) => {
      const ok = await setControllerModeApi(mode);
      if (ok) await refresh();
    },
    [refresh]
  );

  const setRogAllyThermalPolicy = useCallback(
    async (policy: number) => applyImmediate({ thermalPolicy: policy }),
    [applyImmediate]
  );

  const setRogAllyFanMode = useCallback(
    async (fanId: number, mode: number): Promise<boolean> => {
      const ok = await setRogAllyFanModeApi(fanId, mode);
      if (ok) await refresh();
      return ok;
    },
    [refresh]
  );

  const setRogAllyMcuPowersave = useCallback(
    async (enabled: boolean): Promise<boolean> => {
      const ok = await setRogAllyMcuPowersaveApi(enabled);
      if (ok) await refresh();
      return ok;
    },
    [refresh]
  );

  const setRogAllyPlatformProfile = useCallback(
    async (profile: string): Promise<boolean> => {
      const ok = await setRogAllyPlatformProfileApi(profile);
      if (ok) await refresh();
      return ok;
    },
    [refresh]
  );

  useEffect(() => {
    if (loading) return;
    const id = setInterval(async () => {
      const cur = stateRef.current;
      if (!cur) return;

      let newAc = cur.ac_power;
      if (cur.per_game_profiles_enabled) {
        try {
          newAc = await getAcPowerStatusApi();
        } catch {}
      }

      let gameId = "00000000";
      if (cur.per_game_profiles_enabled) {
        const game = currentGameId();
        if (game.id !== "default" && game.id !== "00000000") gameId = game.id;
      }
      const targetId = `${gameId}${newAc ? "_ac" : "_battery"}`;
      if (targetId === cur.current_profile_id && newAc === cur.ac_power) return;
      await applyImmediate({}, targetId);
      await refresh();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loading, applyImmediate, refresh]);

  const value = useMemo<SettingsContextValue>(
    () => ({
      state,
      loading,
      error,
      applySettings,
      setPerGameEnabled,
      setControllerMode,
      setRogAllyThermalPolicy,
      setRogAllyFanMode,
      setRogAllyMcuPowersave,
      setRogAllyPlatformProfile,
      refresh,
    }),
    [
      state,
      loading,
      error,
      applySettings,
      setPerGameEnabled,
      setControllerMode,
      setRogAllyThermalPolicy,
      setRogAllyFanMode,
      setRogAllyMcuPowersave,
      setRogAllyPlatformProfile,
      refresh,
    ]
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}
