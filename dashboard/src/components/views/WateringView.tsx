"use client";

import { Ban, CircleCheck, CircleDashed, Clock, Droplets, Power, ShieldCheck } from "lucide-react";
import type { PumpEvent } from "@/lib/types";
import { priorityCode } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import { useDashboard } from "@/lib/dashboard";
import { ActivityTable } from "../ActivityTable";
import { WateringControls } from "../WateringControls";
import { Ago } from "../ui/Ago";
import { Badge } from "../ui/Badge";
import { Card, PageHeader } from "../ui/Card";
import { Kpi } from "../ui/Kpi";
import { Loading } from "./Loading";

export function WateringView() {
  const { base, snapshot: s, health } = useDashboard();
  const log = usePolling<{ events: PumpEvent[] }>(base && `${base}/pump/events?hours=24`, 10_000);
  if (!s) return <Loading />;

  const events = log.data?.events ?? s.watering.events;
  const runs = events.filter((e) => e.state === "on");
  const refused = events.filter((e) => e.state === "rejected");
  const soil = s.metrics?.soil_moisture;
  const priority = s.analysis?.priority;
  const limits = health?.watering;

  // The conditions auto-watering checks (backend/greenpulse_ai/watering.py), against the current state.
  const conditions: { label: string; met: boolean | null }[] = [
    { label: "Auto-watering is switched on (here or on the Node-RED dashboard)", met: s.watering.auto_enabled },
    {
      label: `The soil sensor reads below the ideal range${soil ? ` (under ${soil.ideal_min}%)` : ""}`,
      met: soil ? soil.state === "low" || soil.state === "too_low" : null,
    },
    { label: "The Plant Doctor rates it high or critical", met: priority ? priorityCode(priority) >= 2 : null },
    {
      label: limits
        ? `At least ${Math.round(limits.cooldown_s / 60)} min since the last watering, so the water can soak in`
        : "Enough time since the last watering for the water to soak in",
      met: null,
    },
    { label: limits ? `Fewer than ${limits.max_per_day} waterings in 24 hours` : "Under the daily watering limit", met: null },
  ];

  return (
    <>
      <PageHeader title="Watering" description="Pump controls, the auto-watering rules and everything the pump did in the last 24 hours" />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Power} label="Auto-watering" value={s.watering.auto_enabled ? "On" : "Off"}>
          {s.watering.auto_enabled ? "The AI may water within the rules below" : "Only manual watering"}
        </Kpi>
        <Kpi icon={Droplets} label="Waterings, last 24 h" value={runs.length}>
          {runs.filter((e) => e.source === "auto").length} automatic · {runs.filter((e) => e.source !== "auto").length} manual
        </Kpi>
        <Kpi icon={Clock} label="Last watered" value={s.watering.last_watered ? <Ago time={s.watering.last_watered} /> : "Not yet"}>
          {runs[0]?.seconds != null ? `${runs[0].seconds} s pulse` : "No run recorded"}
        </Kpi>
        <Kpi icon={Ban} label="Refused by the device, 24 h" value={refused.length}>
          {refused[0] ? refused[0].detail : "No refusals"}
        </Kpi>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <WateringControls snapshot={s} />
        <Card
          className="xl:col-span-2"
          title="How auto-watering decides"
          subtitle="The AI can never switch the pump on alone: every condition must hold"
        >
          <ul className="space-y-2.5">
            {conditions.map((c) => (
              <li key={c.label} className="flex items-start gap-3 text-sm">
                {c.met === true ? (
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-label="Met now" />
                ) : (
                  <CircleDashed className="mt-0.5 size-4 shrink-0 text-ink-3" aria-label={c.met === false ? "Not met now" : "Checked at each decision"} />
                )}
                <span className={c.met === false ? "text-ink-3" : "text-ink"}>{c.label}</span>
                {c.met !== null && (
                  <span className="ml-auto shrink-0">
                    <Badge tone={c.met ? "good" : "neutral"}>{c.met ? "Met" : "Not now"}</Badge>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <div className="mt-4 flex items-start gap-3 rounded-lg bg-brand-softer px-3.5 py-3 text-xs text-ink-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
            <p>
              On top of these, the device itself stops any run after 15 s, rests 60 s between runs and refuses to pump
              into soil wetter than 75%{limits ? `. Each automatic pulse lasts ${limits.pulse_s} s` : ""}.
            </p>
          </div>
        </Card>
      </div>

      <Card className="mt-6" title="Pump activity log" subtitle="Last 24 hours, newest first">
        <ActivityTable events={events} empty="The pump hasn't run in the last 24 hours." />
      </Card>
    </>
  );
}
