"use client";

import { Activity, ChartLine, Droplets, ShieldCheck, Stethoscope } from "lucide-react";
import type { MetricKey } from "@/lib/types";
import { formatValue, plantName } from "@/lib/format";
import { useDashboard } from "@/lib/dashboard";
import { ChatPanel } from "../ChatPanel";
import { SERIES } from "../MetricChart";
import { PriorityBadge, StateBadge } from "../ui/Badge";
import { Card, PageHeader } from "../ui/Card";

const TOOLS = [
  { icon: Activity, name: "Live readings", text: "Soil, temperature and humidity against the ideal ranges, and the drying trend" },
  { icon: Stethoscope, name: "Plant Doctor report", text: "The latest advice, with the weather and inbox reminders behind it" },
  { icon: ChartLine, name: "Sensor history", text: "How the readings changed over the last 24 hours" },
  { icon: Droplets, name: "Watering log", text: "Pump runs, refusals and why auto-watering did or didn't water" },
];

export function AssistantView() {
  const { snapshot: s, chat } = useDashboard();
  const plant = s ? plantName(s.plant).name : "plant";

  return (
    <>
      <PageHeader title="AI Assistant" description={`Ask about your ${plant} in plain words, for example "Does it need water today?"`} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Card className="h-[calc(100dvh-12rem)] min-h-[30rem] overflow-hidden" bodyClassName="flex min-h-0 flex-col">
          <ChatPanel chat={chat} plant={plant} />
        </Card>

        <div className="grid content-start gap-6">
          <Card title="Right now">
            {!s?.metrics ? (
              <p className="text-sm text-ink-3">Waiting for the first reading.</p>
            ) : (
              <dl className="space-y-3 text-sm">
                {s.analysis && (
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-ink-3">Priority</dt>
                    <dd>
                      <PriorityBadge priority={s.analysis.priority} />
                    </dd>
                  </div>
                )}
                {(Object.keys(SERIES) as MetricKey[]).map((key) => {
                  const m = s.metrics![key];
                  return (
                    <div key={key} className="flex items-center justify-between gap-2">
                      <dt className="text-ink-3">{SERIES[key].label}</dt>
                      <dd className="flex items-center gap-2">
                        <span className="font-semibold text-ink tabular-nums">{formatValue(m.value, m.unit, key === "temperature" ? 1 : 0)}</span>
                        <StateBadge metricKey={key} state={m.state} />
                      </dd>
                    </div>
                  );
                })}
              </dl>
            )}
          </Card>

          <Card title="What the assistant looks at">
            <ul className="space-y-3">
              {TOOLS.map(({ icon: Icon, name, text }) => (
                <li key={name} className="flex gap-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand-soft">
                    <Icon className="size-4 text-brand" aria-hidden />
                  </span>
                  <div>
                    <p className="text-sm font-medium text-ink">{name}</p>
                    <p className="text-xs text-ink-3">{text}</p>
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-4 flex gap-2 rounded-lg bg-brand-softer px-3 py-2.5 text-xs text-ink-2">
              <ShieldCheck className="size-4 shrink-0 text-brand" aria-hidden />
              It only reads data. It can&apos;t run the pump or change settings.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}
