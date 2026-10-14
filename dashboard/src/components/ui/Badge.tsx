import type { CSSProperties, ReactNode } from "react";
import type { MetricKey, MetricState, Priority } from "@/lib/types";
import { PRIORITY, STATE_WORDS, stateTone, type Tone } from "@/lib/format";

const TONES: Record<Tone, string> = {
  good: "bg-good-bg text-good-ink",
  warning: "bg-warning-bg text-warning-ink",
  serious: "bg-serious-bg text-serious-ink",
  critical: "bg-critical-bg text-critical-ink",
  neutral: "bg-sunk text-ink-2 ring-1 ring-inset ring-line",
  brand: "bg-brand-soft text-brand-ink",
  info: "bg-info-bg text-info-ink",
};

export function Badge({ tone = "neutral", dot = false, children }: { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

/** The Plant Doctor's priority, with a dot in the colour of the device's LED. */
export function PriorityBadge({ priority }: { priority: Priority }) {
  const p = PRIORITY[priority];
  return (
    <span className={`inline-flex items-center gap-2 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${TONES[p.tone]}`}>
      <span className="lamp" data-priority={priority} style={{ "--lamp": p.color } as CSSProperties} aria-hidden />
      {p.label}
    </span>
  );
}

const STATE_TONE: Record<ReturnType<typeof stateTone>, Tone> = {
  good: "good",
  warning: "warning",
  critical: "critical",
  unknown: "neutral",
};

export function StateBadge({ metricKey, state }: { metricKey: MetricKey; state: MetricState }) {
  return (
    <Badge tone={STATE_TONE[stateTone(state)]} dot>
      {STATE_WORDS[metricKey][state]}
    </Badge>
  );
}
