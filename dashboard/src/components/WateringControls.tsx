"use client";

import { useEffect, useState } from "react";
import { Droplets } from "lucide-react";
import type { Snapshot } from "@/lib/types";
import { api } from "@/lib/hooks";
import { useDashboard } from "@/lib/dashboard";
import { Ago } from "./ui/Ago";
import { Badge } from "./ui/Badge";
import { Card } from "./ui/Card";
import { Switch } from "./ui/Switch";

/** Water now and the auto-watering switch: the same MQTT commands as the Node-RED dashboard. */
export function WateringControls({ snapshot, className = "" }: { snapshot: Snapshot; className?: string }) {
  const { refresh, health } = useDashboard();
  const { watering, online, device_id: deviceId } = snapshot;
  const [busy, setBusy] = useState<"water" | "auto" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoPending, setAutoPending] = useState<boolean | null>(null); // shown until the server agrees
  const auto = autoPending ?? watering.auto_enabled;

  useEffect(() => setAutoPending(null), [watering.auto_enabled]);

  async function run(kind: "water" | "auto", request: () => Promise<unknown>) {
    setBusy(kind);
    setError(null);
    try {
      await request();
      refresh();
    } catch (e) {
      if (kind === "auto") setAutoPending(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const path = `/api/devices/${encodeURIComponent(deviceId)}/pump`;
  const waterNow = () => run("water", () => api(`${path}/water`, { method: "POST" }));
  const toggleAuto = () => {
    const enabled = !auto;
    setAutoPending(enabled);
    run("auto", () => api(`${path}/auto`, { method: "PUT", body: JSON.stringify({ enabled }) }));
  };
  const decision = watering.last_decision;

  return (
    <Card
      className={className}
      title="Watering"
      action={
        watering.pump_running ? (
          <Badge tone="info" dot>
            Pump running
          </Badge>
        ) : (
          <Badge tone="neutral">Pump idle</Badge>
        )
      }
    >
      <button
        type="button"
        onClick={waterNow}
        disabled={busy !== null || watering.pump_running || !online}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-card transition-colors hover:bg-brand-strong disabled:cursor-not-allowed disabled:bg-line-strong"
      >
        <Droplets className="size-4" aria-hidden />
        {watering.pump_running ? "Watering…" : busy === "water" ? "Sending…" : `Water now${health?.watering ? ` (${health.watering.pulse_s} s)` : ""}`}
      </button>
      <p className="mt-2 text-center text-xs text-ink-3">
        {!online ? (
          "The device is offline"
        ) : watering.last_watered ? (
          <>
            Last watered <Ago time={watering.last_watered} />
          </>
        ) : (
          "No watering recorded yet"
        )}
      </p>

      <div className="mt-4 flex items-start justify-between gap-4 rounded-lg border border-line p-3.5">
        <div>
          <p id="auto-watering-label" className="text-sm font-semibold text-ink">
            Auto-watering
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-ink-3">
            Waters when the soil sensor reads dry and the Plant Doctor says it&apos;s urgent.
          </p>
        </div>
        <Switch checked={auto} onChange={toggleAuto} disabled={busy !== null} labelledBy="auto-watering-label" />
      </div>

      {decision && (
        <div className="mt-3 rounded-lg bg-sunk px-3.5 py-2.5 text-xs">
          <p className="font-semibold text-ink-2">Last AI decision: {decision.decision === "water" ? "watered" : "didn't water"}</p>
          <p className="mt-0.5 text-ink-3">{decision.reason}</p>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-xs text-critical-ink">
          {error}
        </p>
      )}
    </Card>
  );
}
