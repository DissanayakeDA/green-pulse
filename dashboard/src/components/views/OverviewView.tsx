"use client";

import { useState, type CSSProperties } from "react";
import Link from "next/link";
import { Clock, Droplet, HeartPulse, Thermometer, Waves } from "lucide-react";
import type { MetricKey } from "@/lib/types";
import { PRIORITY, formatValue, plantName, pumpSource } from "@/lib/format";
import { useDashboard } from "@/lib/dashboard";
import { ActivityTable } from "../ActivityTable";
import { AdviceCard } from "../AdviceCard";
import { RemindersCard, WeatherCard } from "../ContextCards";
import { MetricChart, SERIES, recent } from "../MetricChart";
import { SoilGauge } from "../SoilGauge";
import { WateringControls } from "../WateringControls";
import { Ago } from "../ui/Ago";
import { Badge, StateBadge } from "../ui/Badge";
import { Card, PageHeader, Segmented } from "../ui/Card";
import { Kpi } from "../ui/Kpi";
import { Sparkline } from "../ui/Sparkline";
import { Loading } from "./Loading";

export function OverviewView() {
  const { snapshot: s, history } = useDashboard();
  const [metric, setMetric] = useState<MetricKey>("soil_moisture");
  if (!s) return <Loading />;

  const plant = plantName(s.plant).name;
  const analysis = s.analysis;
  const lastRun = s.watering.events.find((e) => e.state === "on");

  const reading = (key: MetricKey, icon: typeof Droplet) => {
    const m = s.metrics?.[key] ?? null;
    return (
      <Kpi
        icon={icon}
        label={SERIES[key].label}
        value={formatValue(m?.value ?? null, m?.unit ?? SERIES[key].unit, key === "temperature" ? 1 : 0)}
        trend={<Sparkline values={recent(history, key, 6)} color={SERIES[key].color} label={`${SERIES[key].label}, last 6 hours`} />}
      >
        {m && <StateBadge metricKey={key} state={m.state} />}
        {m && (
          <span>
            Ideal {m.ideal_min}–{m.ideal_max}
            {m.unit === "%" ? "%" : ` ${m.unit}`}
          </span>
        )}
      </Kpi>
    );
  };

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          <>
            Live status of your {plant}
            {s.last_seen && (
              <>
                {" "}
                · last reading <Ago time={s.last_seen} />
              </>
            )}
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi
          icon={HeartPulse}
          label="Care priority"
          className="sm:col-span-2 xl:col-span-1"
          value={
            analysis ? (
              <span className="flex items-center gap-2.5">
                <span className="lamp" data-priority={analysis.priority} style={{ "--lamp": PRIORITY[analysis.priority].color } as CSSProperties} aria-hidden />
                {PRIORITY[analysis.priority].label}
              </span>
            ) : (
              "Checking…"
            )
          }
        >
          {analysis ? <span className="font-medium text-ink-2">{analysis.headline}</span> : "Waiting for the Plant Doctor"}
        </Kpi>
        {reading("soil_moisture", Droplet)}
        {reading("temperature", Thermometer)}
        {reading("humidity", Waves)}
        <Kpi icon={Clock} label="Last watered" value={s.watering.last_watered ? <Ago time={s.watering.last_watered} /> : "Not yet"}>
          {lastRun && (
            <span>
              {pumpSource(lastRun.source)}
              {lastRun.seconds !== null && ` · ${lastRun.seconds} s`}
            </span>
          )}
          <Badge tone={s.watering.auto_enabled ? "brand" : "neutral"} dot>
            Auto {s.watering.auto_enabled ? "on" : "off"}
          </Badge>
        </Kpi>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <AdviceCard snapshot={s} className="xl:col-span-2" />
        <Card title="Soil moisture level" subtitle="Wet soil rises to the current level">
          <SoilGauge
            metric={s.metrics?.soil_moisture ?? null}
            trend={s.moisture_trend_per_hour}
            hoursUntilDry={s.hours_until_dry}
            pumpRunning={s.watering.pump_running}
          />
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Last 24 hours"
          subtitle={metric === "soil_moisture" ? "Blue lines mark waterings" : undefined}
          action={
            <Segmented
              label="Reading"
              options={(Object.keys(SERIES) as MetricKey[]).map((k) => ({ value: k, label: SERIES[k].label }))}
              value={metric}
              onChange={setMetric}
            />
          }
        >
          <MetricChart history={history} metric={metric} ideal={s.metrics?.[metric]} height={280} />
        </Card>
        <WateringControls snapshot={s} />
      </div>

      <div className="mt-6 grid items-start gap-6 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Recent pump activity"
          action={
            <Link href="/watering" className="text-xs font-semibold text-brand hover:text-brand-strong">
              View all
            </Link>
          }
        >
          <ActivityTable events={s.watering.events} />
        </Card>
        <div className="grid gap-6">
          <WeatherCard analysis={analysis} />
          <RemindersCard analysis={analysis} />
        </div>
      </div>
    </>
  );
}
