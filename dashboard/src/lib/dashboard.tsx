"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { DeviceSummary, History, Snapshot } from "./types";
import { loginUrl, type Account, type Me } from "./auth";
import { useChat, type Chat } from "./chat";
import { usePolling } from "./hooks";

export interface Health {
  ok: boolean;
  default_device: string;
  llm: string | null;
  demo?: boolean;
  location?: string;
  watering?: { pulse_s: number; cooldown_s: number; max_per_day: number };
}

interface DashboardState {
  devices: DeviceSummary[];
  deviceId: string | null;
  selectDevice: (deviceId: string) => void;
  /** "/api/devices/<id>", for pages that fetch more */
  base: string | null;
  snapshot: Snapshot | null;
  history: History | null;
  health: Health | null;
  /** who is signed in */
  account: Account | null;
  error: string | null;
  refresh: () => void;
  chat: Chat;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
}

const DashboardContext = createContext<DashboardState | null>(null);
const DEVICE_KEY = "greenpulse-device";

/** Polls the bridge once for the whole app: device status every 5 s, the 24-hour history every minute. */
export function DashboardProvider({ children }: { children: ReactNode }) {
  const devices = usePolling<{ devices: DeviceSummary[] }>("/api/devices", 15_000);
  const [chosen, setChosen] = useState<string | null>(null);

  useEffect(() => {
    try {
      setChosen(localStorage.getItem(DEVICE_KEY));
    } catch {
      // storage blocked: use the most recent device
    }
  }, []);

  const list = devices.data?.devices ?? [];
  const deviceId = (chosen && list.some((d) => d.device_id === chosen) ? chosen : list[0]?.device_id) ?? null;
  const base = deviceId ? `/api/devices/${encodeURIComponent(deviceId)}` : null;

  const snapshot = usePolling<Snapshot>(base, 5_000);
  const history = usePolling<History>(base && `${base}/history?hours=24`, 60_000);
  const health = usePolling<Health>("/api/health", 60_000);
  const me = usePolling<Me>("/api/auth/me", 300_000);
  const chat = useChat(deviceId);
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    if (me.data && !me.data.account) window.location.assign(loginUrl()); // the session ran out
  }, [me.data]);

  const selectDevice = useCallback((id: string) => {
    setChosen(id);
    try {
      localStorage.setItem(DEVICE_KEY, id);
    } catch {
      // not remembered; still selected for this visit
    }
  }, []);

  const { refresh: refreshSnapshot } = snapshot;
  const { refresh: refreshHistory } = history;
  const refresh = useCallback(() => {
    refreshSnapshot();
    refreshHistory();
  }, [refreshSnapshot, refreshHistory]);

  return (
    <DashboardContext.Provider
      value={{
        devices: list,
        deviceId,
        selectDevice,
        base,
        snapshot: snapshot.data,
        history: history.data,
        health: health.data,
        account: me.data?.account ?? null,
        error: devices.error ?? snapshot.error,
        refresh,
        chat,
        chatOpen,
        setChatOpen,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardState {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboard must be used inside DashboardProvider");
  return value;
}
