"use client";

import { CircleCheck, Sparkles, Stethoscope } from "lucide-react";
import type { Snapshot } from "@/lib/types";
import { PRIORITY, modelName } from "@/lib/format";
import { useDashboard } from "@/lib/dashboard";
import { Ago } from "./ui/Ago";
import { Badge, PriorityBadge } from "./ui/Badge";
import { Card, Empty } from "./ui/Card";

export const TRIGGERS: Record<string, string> = {
  "first reading": "the first reading came in",
  "interval elapsed": "it re-checks every few minutes",
  "moisture changed": "the soil moisture changed",
  "sensor priority changed": "a reading moved out of (or back into) its ideal range",
  forced: "auto-watering was switched on",
};

export function sourceLabel(source: string, model: string | null): string {
  if (source === "llm") return `AI · ${modelName(model) ?? "LLM"}`;
  return source === "rules" ? "Rule-based (AI off)" : "Rule-based (AI unavailable)";
}

/** The Plant Doctor's latest advice: priority, what to do, and why. */
export function AdviceCard({ snapshot, className = "" }: { snapshot: Snapshot; className?: string }) {
  const { setChatOpen } = useDashboard();
  const analysis = snapshot.analysis;

  return (
    <Card
      className={className}
      title={
        <span className="flex items-center gap-2">
          <Stethoscope className="size-4 text-brand" aria-hidden /> Plant Doctor advice
        </span>
      }
      action={
        analysis && (
          <span className="flex items-center gap-2 text-xs text-ink-3">
            <Badge tone={analysis.source === "llm" ? "brand" : "neutral"}>{sourceLabel(analysis.source, analysis.model)}</Badge>
            <Ago time={analysis.generated_at} />
          </span>
        )
      }
    >
      {!analysis ? (
        <Empty>
          {snapshot.reading
            ? "The Plant Doctor is checking the first reading. Its advice appears here in a few seconds."
            : "Advice appears as soon as the device sends its first reading."}
        </Empty>
      ) : (
        <div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <PriorityBadge priority={analysis.priority} />
            <span className="text-xs text-ink-3">Device light: {PRIORITY[analysis.priority].led}</span>
          </div>
          <p className="mt-3 text-2xl font-bold tracking-tight text-ink">{analysis.headline}</p>
          <p className="mt-2 max-w-[70ch] text-sm leading-relaxed text-ink-2">{analysis.message}</p>

          {analysis.actions.length > 0 && (
            <ul className="mt-4 grid gap-2 sm:grid-cols-2" aria-label="What to do, most important first">
              {analysis.actions.map((action, i) => (
                <li key={i} className="flex gap-2.5 rounded-lg border border-line bg-brand-softer px-3 py-2.5 text-sm text-ink">
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
                  {action}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
            <details className="text-sm">
              <summary className="cursor-pointer font-medium text-ink-2 hover:text-ink">Why this advice</summary>
              <div className="mt-2 max-w-[70ch] space-y-2 text-ink-2">
                <p>{analysis.reasoning}</p>
                {analysis.guardrail_note && <p className="text-xs">Safety check: {analysis.guardrail_note}</p>}
                <p className="text-xs text-ink-3">Checked because {TRIGGERS[analysis.trigger] ?? analysis.trigger}.</p>
              </div>
            </details>
            <button
              type="button"
              onClick={() => setChatOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-brand/30 px-3 py-1.5 text-sm font-medium text-brand-ink hover:bg-brand-softer"
            >
              <Sparkles className="size-4" aria-hidden /> Ask a follow-up
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
