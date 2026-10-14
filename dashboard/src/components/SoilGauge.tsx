"use client";

import { useId } from "react";
import type { Metric } from "@/lib/types";
import { STATE_WORDS } from "@/lib/format";
import { StateIcon } from "./StateIcon";

// The pot, in viewBox units. Soil moisture 0 % sits at the bottom of the pot, 100 % at the soil surface.
const SOIL_TOP = 136;
const POT_BOTTOM = 292;
const BODY = "M62,126 L202,126 L189,284 Q188,292 180,292 L84,292 Q76,292 75,284 Z";
const LEAF = "M0,0 C-7,5 -25,3 -26,-15 C-27,-31 -12,-40 0,-52 C12,-40 27,-31 26,-15 C25,3 7,5 0,0 Z";

// Three pothos leaves on their stems. `lean` is the direction each one droops in.
const LEAVES = [
  { x: 98, y: 66, angle: -38, scale: 1.05, lean: -1, stem: "M132,132 C128,104 110,84 98,66" },
  { x: 166, y: 58, angle: 32, scale: 1, lean: 1, stem: "M132,132 C138,100 156,78 166,58" },
  { x: 130, y: 36, angle: -4, scale: 0.8, lean: -0.7, stem: "M132,132 C131,96 131,62 130,36" },
];

const DROOP: Partial<Record<Metric["state"], number>> = { low: 18, too_low: 42 };

const levelY = (percent: number) => POT_BOTTOM - (Math.min(Math.max(percent, 0), 100) / 100) * (POT_BOTTOM - SOIL_TOP);
const rightWallX = (y: number) => 202 - (13 * (y - 126)) / 158;

export function SoilGauge({
  metric,
  trend,
  hoursUntilDry,
  pumpRunning,
}: {
  metric: Metric | null;
  trend: number | null;
  hoursUntilDry: number | null;
  pumpRunning: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const value = metric?.value ?? null;
  const known = value !== null && metric?.state !== "sensor_error";
  const y = known ? levelY(value) : POT_BOTTOM;
  const droop = metric ? (DROOP[metric.state] ?? 0) : 0;
  const labelY = Math.min(Math.max(y + 12, 160), 270); // baseline of the number, centred on the waterline
  const idealTop = levelY(metric?.ideal_max ?? 65);
  const idealBottom = levelY(metric?.ideal_min ?? 35);

  const label = known
    ? `Soil moisture ${value.toFixed(0)}%, ideal ${metric!.ideal_min}–${metric!.ideal_max}%`
    : "Soil moisture unknown";

  return (
    <figure className="flex flex-col items-center">
      <svg viewBox="0 0 300 300" role="img" aria-label={label} className="w-full max-w-76 overflow-visible">
        <defs>
          <clipPath id={`${id}-body`}>
            <path d={BODY} />
          </clipPath>
          <pattern id={`${id}-grain`} width="9" height="9" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="0.9" fill="var(--soil-grain)" />
            <circle cx="6.5" cy="6" r="0.7" fill="var(--soil-grain)" />
          </pattern>
        </defs>

        {/* Leaves first, so the rim hides where the stems leave the soil. */}
        {LEAVES.map((leaf, i) => (
          <g key={i}>
            <path d={leaf.stem} fill="none" stroke="var(--leaf)" strokeWidth="2.5" strokeLinecap="round" />
            <g
              className="gauge-leaf"
              style={{
                transformOrigin: "0 0",
                transform: `translate(${leaf.x}px, ${leaf.y}px) rotate(${leaf.angle + droop * leaf.lean}deg) scale(${leaf.scale})`,
              }}
            >
              <path d={LEAF} fill="var(--leaf)" />
              <path d="M0,-3 L0,-46" stroke="var(--leaf-vein)" strokeWidth="1.4" strokeLinecap="round" opacity="0.85" />
              <path d="M-5,-12 C-13,-17 -16,-26 -11,-34" fill="none" stroke="var(--leaf-vein)" strokeWidth="1.6" strokeLinecap="round" opacity="0.45" />
            </g>
          </g>
        ))}

        {pumpRunning &&
          [
            [112, 70, 0],
            [132, 58, 0.3],
            [151, 72, 0.6],
          ].map(([x, top, delay]) => (
            <g key={x} transform={`translate(${x} ${top})`}>
              <path className="gauge-drop" style={{ animationDelay: `${delay}s` }} d="M0,-6 C3,-1 4,2 0,5 C-4,2 -3,-1 0,-6 Z" fill="var(--water)" />
            </g>
          ))}

        {/* Soil: dry on top, wet below the waterline. */}
        <g clipPath={`url(#${id}-body)`}>
          <rect x="50" y={SOIL_TOP} width="170" height="160" fill="var(--soil-dry)" />
          <g className="gauge-level" style={{ transform: `translateY(${y - SOIL_TOP}px)` }}>
            <rect x="50" y={SOIL_TOP} width="170" height="160" fill="var(--soil-wet)" />
            {known && <line x1="50" x2="220" y1={SOIL_TOP} y2={SOIL_TOP} stroke="var(--water)" strokeWidth="3" />}
          </g>
          <rect x="50" y={SOIL_TOP} width="170" height="160" fill={`url(#${id}-grain)`} opacity="0.16" />
        </g>

        {/* The pot */}
        <path d={BODY} fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinejoin="round" />
        <rect x="52" y="104" width="160" height="24" rx="5" fill="var(--surface)" stroke="var(--ink)" strokeWidth="2" />

        {/* Ideal range, as a bracket on the left */}
        <g stroke="var(--ink-3)" strokeWidth="1.5" strokeLinecap="round">
          <line x1="46" x2="46" y1={idealTop} y2={idealBottom} />
          <line x1="46" x2="54" y1={idealTop} y2={idealTop} />
          <line x1="46" x2="54" y1={idealBottom} y2={idealBottom} />
        </g>
        <text x="40" y={(idealTop + idealBottom) / 2 - 3} textAnchor="end" fontSize="12" fontWeight="600" fill="var(--ink-2)">
          ideal
        </text>
        <text x="40" y={(idealTop + idealBottom) / 2 + 12} textAnchor="end" fontSize="11" fill="var(--ink-3)">
          {metric ? `${metric.ideal_min}–${metric.ideal_max}%` : ""}
        </text>

        {/* The reading, level with the waterline */}
        <g className="gauge-level" style={{ transform: `translateY(${labelY - 200}px)` }}>
          {known && (
            <line x1={rightWallX(y) + 4} x2="226" y1={200 + y - labelY} y2={200 + y - labelY} stroke="var(--water)" strokeWidth="1.5" />
          )}
          <text x="230" y="200" className="display" fontSize="40" fill="var(--ink)">
            {known ? `${value.toFixed(0)}%` : "--"}
          </text>
          <text x="231" y="218" fontSize="12" fill="var(--ink-3)">
            soil moisture
          </text>
        </g>
      </svg>

      <figcaption className="mt-3 text-center text-sm text-ink-2">
        {metric && (
          <span className="inline-flex items-center gap-1.5 font-semibold text-ink">
            <StateIcon state={metric.state} />
            {STATE_WORDS.soil_moisture[metric.state]}
          </span>
        )}
        <span className="block">{trendText(trend, hoursUntilDry, pumpRunning)}</span>
      </figcaption>
    </figure>
  );
}

function trendText(trend: number | null, hoursUntilDry: number | null, pumpRunning: boolean): string {
  if (pumpRunning) return "Watering now";
  if (trend === null) return "Trend appears after about 15 minutes of readings";
  if (trend > 0.05) return `Getting wetter, ${trend.toFixed(1)}% an hour`;
  if (trend > -0.05) return "Holding steady";
  const drying = `Drying ${Math.abs(trend).toFixed(1)}% an hour`;
  if (hoursUntilDry === null) return drying;
  if (hoursUntilDry === 0) return `${drying}, already below ideal`;
  return `${drying}, dry in about ${hoursUntilDry < 1.5 ? "an hour" : `${Math.round(hoursUntilDry)} h`}`;
}
