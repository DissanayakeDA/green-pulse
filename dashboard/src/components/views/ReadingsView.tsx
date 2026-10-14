"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import type { History, MetricKey } from "@/lib/types";
import { clock, formatValue } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import { useDashboard } from "@/lib/dashboard";
import { MetricChart, SERIES } from "../MetricChart";
import { StateBadge } from "../ui/Badge";
import { Card, Empty, PageHeader, Segmented } from "../ui/Card";
import { Loading } from "./Loading";

const KEYS: MetricKey[] = ["soil_moisture", "temperature", "humidity"];
const RANGES = [1, 6, 24];
const PAGE = 24;

export function ReadingsView() {
  const { base, snapshot: s, history: day } = useDashboard();
  const [hours, setHours] = useState(24);
  const [rows, setRows] = useState(PAGE);
  // The last 24 hours are already polled for the whole app; shorter ranges are fetched here.
  const own = usePolling<History>(base && hours !== 24 ? `${base}/history?hours=${hours}` : null, 60_000);
  const history = hours === 24 ? day : own.data?.hours === hours ? own.data : null;

  if (!s) return <Loading />;
  const points = history?.points ?? [];
  const logged = [...points].reverse().filter((p) => KEYS.some((k) => p[k] !== null));
  const range = hours === 1 ? "last hour" : `last ${hours} hours`;

  return (
    <>
      <PageHeader
        title="Readings"
        description={`Soil moisture, temperature and air humidity from ${s.device_id}, ${range}`}
        actions={
          <>
            <Segmented
              label="Time range"
              options={RANGES.map((h) => ({ value: h, label: `${h} h` }))}
              value={hours}
              onChange={(h) => {
                setHours(h);
                setRows(PAGE);
              }}
            />
            <button
              type="button"
              disabled={!logged.length}
              onClick={() => downloadCsv(logged, s.device_id, hours)}
              className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-2 shadow-card hover:bg-hover disabled:opacity-50"
            >
              <Download className="size-4" aria-hidden /> Export CSV
            </button>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        {KEYS.map((key) => {
          const metric = s.metrics?.[key] ?? null;
          const values = points.map((p) => p[key]).filter((v): v is number => v !== null);
          const stat = (v: number | null) => formatValue(v, SERIES[key].unit, 1);
          return (
            <Card key={key} bodyClassName="p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-medium text-ink-3">{SERIES[key].label} now</p>
                  <p className="mt-1 text-2xl font-semibold tracking-tight">{formatValue(metric?.value ?? null, SERIES[key].unit, 1)}</p>
                </div>
                {metric && <StateBadge metricKey={key} state={metric.state} />}
              </div>
              <dl className="mt-4 grid grid-cols-3 divide-x divide-line rounded-lg border border-line text-center">
                {[
                  ["Low", values.length ? Math.min(...values) : null],
                  ["Average", values.length ? values.reduce((a, b) => a + b, 0) / values.length : null],
                  ["High", values.length ? Math.max(...values) : null],
                ].map(([label, value]) => (
                  <div key={label as string} className="px-2 py-2">
                    <dt className="text-[0.7rem] text-ink-3">{label}</dt>
                    <dd className="text-sm font-semibold text-ink tabular-nums">{stat(value as number | null)}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          );
        })}
      </div>

      <Card className="mt-6" title="Soil moisture" subtitle={`${range} · blue lines mark waterings`}>
        <MetricChart history={history} metric="soil_moisture" ideal={s.metrics?.soil_moisture} height={300} />
      </Card>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="Temperature" subtitle={range}>
          <MetricChart history={history} metric="temperature" ideal={s.metrics?.temperature} height={230} />
        </Card>
        <Card title="Air humidity" subtitle={range}>
          <MetricChart history={history} metric="humidity" ideal={s.metrics?.humidity} height={230} />
        </Card>
      </div>

      <Card className="mt-6" title="Readings log" subtitle="Averaged per interval, newest first" bodyClassName="p-0">
        {!logged.length ? (
          <div className="p-5">
            <Empty>No readings in this time range yet.</Empty>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] text-left text-sm">
                <thead className="bg-sunk text-xs text-ink-3">
                  <tr>
                    <th className="px-5 py-2.5 font-medium">Time</th>
                    {KEYS.map((key) => (
                      <th key={key} className="px-5 py-2.5 text-right font-medium">
                        {SERIES[key].label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {logged.slice(0, rows).map((p) => (
                    <tr key={p.t} className="border-t border-line hover:bg-hover">
                      <td className="px-5 py-2 text-ink-2">
                        {new Date(p.t).toLocaleDateString([], { day: "numeric", month: "short" })}, {clock(p.t)}
                      </td>
                      {KEYS.map((key) => (
                        <td key={key} className="px-5 py-2 text-right text-ink">
                          {formatValue(p[key], SERIES[key].unit, 1)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-line px-5 py-3 text-xs text-ink-3">
              <span>
                Showing {Math.min(rows, logged.length)} of {logged.length}
              </span>
              {rows < logged.length && (
                <button type="button" onClick={() => setRows((r) => r + PAGE)} className="font-semibold text-brand hover:text-brand-strong">
                  Show more
                </button>
              )}
            </div>
          </>
        )}
      </Card>
    </>
  );
}

function downloadCsv(points: History["points"], deviceId: string, hours: number) {
  const header = "time,soil_moisture_pct,temperature_c,humidity_pct";
  const lines = [...points]
    .reverse()
    .map((p) => [new Date(p.t).toISOString(), p.soil_moisture ?? "", p.temperature ?? "", p.humidity ?? ""].join(","));
  const url = URL.createObjectURL(new Blob([[header, ...lines].join("\n")], { type: "text/csv" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: `${deviceId}-last-${hours}h.csv` });
  link.click();
  URL.revokeObjectURL(url);
}
