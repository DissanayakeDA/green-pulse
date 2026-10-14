import type { MetricKey, MetricState, PlantProfile, Priority, Range } from "./types";

export type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "brand" | "info";

/** The device's RGB LED colour for each priority, and what it asks of the owner. */
export const PRIORITY: Record<Priority, { label: string; led: string; color: string; tone: Tone }> = {
  low: { label: "All good", led: "green", color: "var(--good)", tone: "good" },
  medium: { label: "Act today", led: "yellow", color: "var(--warning)", tone: "warning" },
  high: { label: "Act within 2 hours", led: "orange", color: "var(--serious)", tone: "serious" },
  critical: { label: "Act now", led: "red", color: "var(--critical)", tone: "critical" },
};

/** 0 = low ... 3 = critical, as in the backend (schemas.priority_code). */
export function priorityCode(priority: Priority): number {
  return (["low", "medium", "high", "critical"] as Priority[]).indexOf(priority);
}

export const STATE_WORDS: Record<MetricKey, Record<MetricState, string>> = {
  soil_moisture: {
    too_low: "Very dry",
    low: "A bit dry",
    optimal: "Just right",
    high: "A bit wet",
    too_high: "Waterlogged",
    sensor_error: "Sensor not responding",
  },
  temperature: {
    too_low: "Too cold",
    low: "A bit cool",
    optimal: "Just right",
    high: "A bit warm",
    too_high: "Too hot",
    sensor_error: "Sensor not responding",
  },
  humidity: {
    too_low: "Very dry air",
    low: "A bit dry",
    optimal: "Just right",
    high: "A bit humid",
    too_high: "Very humid",
    sensor_error: "Sensor not responding",
  },
};

/** Severity of a reading's state, for its icon and colour. */
export function stateTone(state: MetricState): "good" | "warning" | "critical" | "unknown" {
  if (state === "optimal") return "good";
  if (state === "low" || state === "high") return "warning";
  if (state === "sensor_error") return "unknown";
  return "critical";
}

/** "Pothos (Money Plant)" -> { name: "Pothos", alias: "Money Plant", latin: "Epipremnum aureum" } */
export function plantName(plant: Pick<PlantProfile, "name" | "scientific_name">) {
  const match = plant.name.match(/^(.*?)\s*\((.*)\)$/);
  return { name: match ? match[1] : plant.name, alias: match ? match[2] : null, latin: plant.scientific_name || null };
}

export const PLANT_SOURCE: Record<PlantProfile["source"], { label: string; tone: Tone }> = {
  "built-in": { label: "Built-in", tone: "neutral" },
  ai: { label: "AI-drafted", tone: "brand" },
  custom: { label: "Custom", tone: "info" },
};

export function rangeText([low, high]: Range, unit: string): string {
  return `${low}–${high}${unit === "%" ? "%" : ` ${unit}`}`;
}

export function ago(time: string | number | null, now: number): string {
  if (time === null) return "never";
  const seconds = Math.max(0, (now - new Date(time).getTime()) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)} s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  const days = Math.floor(seconds / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function clock(time: string | number): string {
  return new Date(time).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** "groq:openai/gpt-oss-120b" -> "gpt-oss-120b" */
export function modelName(model: string | null): string | null {
  return model ? model.split(":").pop()!.split("/").pop()! : null;
}

export function formatValue(value: number | null, unit: string, digits = 0): string {
  if (value === null) return "--";
  return `${value.toFixed(digits)}${unit === "%" ? "%" : ` ${unit}`}`;
}

export function pumpSource(source: string): string {
  return source === "auto" ? "automatic" : source === "manual" ? "manual" : source;
}
