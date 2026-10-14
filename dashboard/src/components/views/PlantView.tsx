"use client";

import Link from "next/link";
import { Cpu, Leaf, Stethoscope } from "lucide-react";
import type { MetricKey } from "@/lib/types";
import { PLANT_SOURCE, formatValue, modelName, plantName } from "@/lib/format";
import { useDashboard } from "@/lib/dashboard";
import { TRIGGERS, sourceLabel } from "../AdviceCard";
import { RemindersCard, WeatherCard } from "../ContextCards";
import { SERIES } from "../MetricChart";
import { Ago } from "../ui/Ago";
import { Badge, PriorityBadge, StateBadge } from "../ui/Badge";
import { Card, Empty, PageHeader } from "../ui/Card";
import { Loading } from "./Loading";

export function PlantView() {
  const { snapshot: s, health } = useDashboard();
  if (!s) return <Loading />;

  const plant = plantName(s.plant);
  const analysis = s.analysis;

  return (
    <>
      <PageHeader title="Plant & device" description="The plant profile the agents work with, the device, and the Plant Doctor's last analysis" />

      <div className="grid gap-6 xl:grid-cols-3">
        <Card
          title={
            <span className="flex items-center gap-2">
              <Leaf className="size-4 text-brand" aria-hidden /> Plant profile
            </span>
          }
          action={
            <Link href="/plants" className="text-xs font-semibold text-brand hover:text-brand-strong">
              Change plant
            </Link>
          }
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-xl font-bold tracking-tight text-ink">{plant.name}</p>
            <Badge tone={PLANT_SOURCE[s.plant.source].tone}>{PLANT_SOURCE[s.plant.source].label}</Badge>
          </div>
          {plant.latin && <p className="text-sm text-ink-2 italic">{plant.latin}</p>}
          {plant.alias && <p className="mt-0.5 text-xs text-ink-3">Also called {plant.alias}</p>}
          {s.plant.care_notes && (
            <p className="mt-4 rounded-lg bg-brand-softer px-3.5 py-3 text-sm leading-relaxed text-ink-2">{s.plant.care_notes}</p>
          )}
        </Card>

        <Card className="xl:col-span-2" title="Ideal ranges" subtitle="Each reading is checked against these every 10 seconds" bodyClassName="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[30rem] text-left text-sm">
              <thead className="bg-sunk text-xs text-ink-3">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Reading</th>
                  <th className="px-5 py-2.5 font-medium">Ideal range</th>
                  <th className="px-5 py-2.5 text-right font-medium">Now</th>
                  <th className="px-5 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {(Object.keys(SERIES) as MetricKey[]).map((key) => {
                  const m = s.metrics?.[key];
                  const unit = SERIES[key].unit;
                  return (
                    <tr key={key} className="border-t border-line">
                      <td className="px-5 py-3 font-medium text-ink">{SERIES[key].label}</td>
                      <td className="px-5 py-3 text-ink-2 tabular-nums">
                        {m ? `${m.ideal_min}–${m.ideal_max}${unit === "%" ? "%" : ` ${unit}`}` : "—"}
                      </td>
                      <td className="px-5 py-3 text-right font-semibold text-ink tabular-nums">{formatValue(m?.value ?? null, unit, 1)}</td>
                      <td className="px-5 py-3">{m ? <StateBadge metricKey={key} state={m.state} /> : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card
          title={
            <span className="flex items-center gap-2">
              <Cpu className="size-4 text-brand" aria-hidden /> Device
            </span>
          }
        >
          <dl className="space-y-3 text-sm">
            <Row label="Device ID" value={<code className="rounded bg-sunk px-1.5 py-0.5 text-xs">{s.device_id}</code>} />
            <Row
              label="Status"
              value={
                <Badge tone={s.online ? "good" : "neutral"} dot>
                  {s.online ? "Online" : s.last_seen ? "Offline" : "Waiting"}
                </Badge>
              }
            />
            <Row label="Last reading" value={s.last_seen ? <Ago time={s.last_seen} /> : "None yet"} />
            <Row label="Connection" value={health?.demo ? <Badge tone="info">Demo (simulated)</Badge> : "MQTT"} />
            <Row label="AI model" value={health?.llm ? modelName(health.llm) : "Off (rule-based)"} />
            {health?.location && <Row label="Location" value={health.location} />}
          </dl>
        </Card>

        <Card
          className="xl:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <Stethoscope className="size-4 text-brand" aria-hidden /> Last Plant Doctor analysis
            </span>
          }
          action={analysis && <Badge tone={analysis.source === "llm" ? "brand" : "neutral"}>{sourceLabel(analysis.source, analysis.model)}</Badge>}
        >
          {!analysis ? (
            <Empty>No analysis yet.</Empty>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              <dl className="space-y-3 text-sm">
                <Row label="Priority" value={<PriorityBadge priority={analysis.priority} />} />
                <Row label="Plant condition" value={<span className="capitalize">{analysis.condition}</span>} />
                <Row label="Checked" value={<Ago time={analysis.generated_at} />} />
                <Row label="Why it ran" value={TRIGGERS[analysis.trigger] ?? analysis.trigger} />
              </dl>
              <div className="space-y-3 text-sm">
                <p className="font-semibold text-ink">{analysis.headline}</p>
                <p className="text-ink-2">{analysis.reasoning}</p>
                {analysis.concerns.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5 text-ink-2">
                    {analysis.concerns.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                )}
                {analysis.guardrail_note && (
                  <p className="rounded-lg bg-warning-bg px-3 py-2 text-xs text-warning-ink">Safety check: {analysis.guardrail_note}</p>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <WeatherCard analysis={analysis} />
        <RemindersCard analysis={analysis} />
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-ink-3">{label}</dt>
      <dd className="text-right text-ink">{value}</dd>
    </div>
  );
}
