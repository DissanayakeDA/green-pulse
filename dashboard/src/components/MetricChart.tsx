"use client";

import { useMemo } from "react";
import { Area, CartesianGrid, ComposedChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { History, Metric, MetricKey } from "@/lib/types";
import { clock, pumpSource } from "@/lib/format";
import { Empty } from "./ui/Card";

export const SERIES: Record<MetricKey, { label: string; unit: string; suffix: string; color: string }> = {
  soil_moisture: { label: "Soil moisture", unit: "%", suffix: "%", color: "var(--soil)" },
  temperature: { label: "Temperature", unit: "°C", suffix: "°", color: "var(--temperature)" },
  humidity: { label: "Air humidity", unit: "%", suffix: "%", color: "var(--humidity)" },
};

const TICK_MINUTES = (hours: number) => (hours <= 1 ? 15 : hours <= 6 ? 60 : 240);

/** One reading over time, with the plant's ideal range shaded and (for soil moisture) waterings marked. */
export function MetricChart({
  history,
  metric,
  ideal,
  height = 260,
  showWaterings = metric === "soil_moisture",
}: {
  history: History | null;
  metric: MetricKey;
  ideal?: Metric | null;
  height?: number;
  showWaterings?: boolean;
}) {
  const series = SERIES[metric];

  const { points, start, end, domain, ticks, readings } = useMemo(() => {
    const points = history?.points ?? [];
    const hours = history?.hours ?? 24;
    const end = points.length ? points[points.length - 1].t : Date.now();
    const start = points.length ? points[0].t : end - hours * 3_600_000;
    const values = points.map((p) => p[metric]).filter((v): v is number => v !== null);
    let domain: [number, number] = [0, 100];
    if (metric === "temperature") {
      const all = [...values, ideal?.ideal_min ?? 18, ideal?.ideal_max ?? 32];
      domain = [Math.floor(Math.min(...all) - 2), Math.ceil(Math.max(...all) + 2)];
    }
    return { points, start, end, domain, ticks: timeTicks(start, end, TICK_MINUTES(hours)), readings: values.length };
  }, [history, metric, ideal]);

  if (!history) return <div style={{ height }} />;
  if (readings === 0) return <Empty>No readings in this time range yet.</Empty>;

  const bucketMs = (end - start) / Math.max(points.length - 1, 1);
  const waterings = showWaterings ? history.waterings : [];

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={[start, end]}
            ticks={ticks}
            tickFormatter={(t: number) => clock(t)}
            tick={{ fill: "var(--ink-3)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "var(--line-strong)" }}
          />
          <YAxis
            domain={domain}
            tickFormatter={(v: number) => `${v}${series.suffix}`}
            tick={{ fill: "var(--ink-3)", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          {ideal && (
            <ReferenceArea
              y1={ideal.ideal_min}
              y2={ideal.ideal_max}
              fill="var(--brand)"
              fillOpacity={0.07}
              stroke="none"
              ifOverflow="hidden"
              label={{ value: "Ideal range", position: "insideTopLeft", fill: "var(--brand-ink)", fontSize: 10 }}
            />
          )}
          {waterings.map((w) => (
            <ReferenceLine key={w.t} x={w.t} stroke="var(--water)" strokeOpacity={0.6} strokeWidth={1.5} />
          ))}
          <Area
            dataKey={metric}
            type="monotone"
            stroke={series.color}
            strokeWidth={2}
            fill={series.color}
            fillOpacity={0.1}
            dot={false}
            activeDot={{ r: 4.5, stroke: "var(--surface)", strokeWidth: 2, fill: series.color }}
            isAnimationActive={false}
          />
          <Tooltip
            cursor={{ stroke: "var(--ink-3)", strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length || typeof label !== "number") return null;
              const value = payload[0].value as number | null;
              const watered = waterings.filter((w) => Math.abs(w.t - label) <= bucketMs / 2);
              return (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-card">
                  <p className="text-xs text-ink-3">{clock(label)}</p>
                  <p className="font-semibold text-ink">
                    {value === null ? "No reading" : `${value}${series.unit === "%" ? "%" : ` ${series.unit}`}`}
                    <span className="ml-1.5 font-normal text-ink-3">{series.label.toLowerCase()}</span>
                  </p>
                  {watered.map((w) => (
                    <p key={w.t} className="mt-1 flex items-center gap-1.5 text-xs text-ink-2">
                      <span className="h-3 w-0.5 rounded bg-water" aria-hidden />
                      Watered · {pumpSource(w.source)}
                    </p>
                  ))}
                </div>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Round local times (every 15 min, hour or 4 hours) between start and end. */
function timeTicks(start: number, end: number, stepMinutes: number): number[] {
  const first = new Date(start);
  const minutes = first.getHours() * 60 + first.getMinutes() + (first.getSeconds() || first.getMilliseconds() ? 1 : 0);
  first.setHours(0, Math.ceil(minutes / stepMinutes) * stepMinutes, 0, 0);
  const ticks: number[] = [];
  for (let t = first.getTime(); t <= end; t += stepMinutes * 60_000) ticks.push(t);
  return ticks;
}

/** Values of one reading over the last `hours` hours of a history, for sparklines. */
export function recent(history: History | null, metric: MetricKey, hours: number): (number | null)[] {
  if (!history?.points.length) return [];
  const end = history.points[history.points.length - 1].t;
  return history.points.filter((p) => p.t >= end - hours * 3_600_000).map((p) => p[metric]);
}
