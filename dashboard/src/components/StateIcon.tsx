import { CircleCheck, CircleHelp, OctagonAlert, TriangleAlert } from "lucide-react";
import type { MetricState } from "@/lib/types";
import { stateTone } from "@/lib/format";

const ICONS = {
  good: { Icon: CircleCheck, className: "text-good" },
  warning: { Icon: TriangleAlert, className: "text-warning" },
  critical: { Icon: OctagonAlert, className: "text-critical" },
  unknown: { Icon: CircleHelp, className: "text-ink-3" },
};

/** The icon that goes with a reading's state word, so state never relies on colour alone. */
export function StateIcon({ state }: { state: MetricState }) {
  const { Icon, className } = ICONS[stateTone(state)];
  return <Icon aria-hidden className={`size-4 shrink-0 ${className}`} strokeWidth={2.25} />;
}
