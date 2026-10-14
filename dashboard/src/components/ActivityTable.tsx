import type { PumpEvent } from "@/lib/types";
import { clock, pumpSource, type Tone } from "@/lib/format";
import { Badge } from "./ui/Badge";
import { Empty } from "./ui/Card";

function eventKind(event: PumpEvent): { label: string; tone: Tone } {
  if (event.state === "on") return { label: "Watered", tone: "brand" };
  if (event.state === "rejected") return { label: "Refused", tone: "critical" };
  return event.detail === "done" ? { label: "Finished", tone: "neutral" } : { label: "Stopped", tone: "warning" };
}

/** Pump reports from the device, newest first. */
export function ActivityTable({ events, empty = "No pump activity yet." }: { events: PumpEvent[]; empty?: string }) {
  if (!events.length) return <Empty>{empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs text-ink-3">
            <th className="py-2 pr-4 font-medium">Time</th>
            <th className="py-2 pr-4 font-medium">Event</th>
            <th className="py-2 pr-4 font-medium">Source</th>
            <th className="py-2 pr-4 text-right font-medium">Duration</th>
            <th className="py-2 font-medium">Details</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => {
            const kind = eventKind(event);
            return (
              <tr key={`${event.at}-${event.state}`} className="border-b border-line last:border-0 hover:bg-hover">
                <td className="py-2.5 pr-4 whitespace-nowrap text-ink-2 tabular-nums">
                  {new Date(event.at).toLocaleDateString([], { day: "numeric", month: "short" })}, {clock(event.at)}
                </td>
                <td className="py-2.5 pr-4">
                  <Badge tone={kind.tone} dot>
                    {kind.label}
                  </Badge>
                </td>
                <td className="py-2.5 pr-4 text-ink-2 capitalize">{pumpSource(event.source)}</td>
                <td className="py-2.5 pr-4 text-right text-ink-2 tabular-nums">{event.seconds === null ? "—" : `${event.seconds} s`}</td>
                <td className="py-2.5 text-ink-3">{event.detail && event.detail !== "done" ? event.detail : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
