import { CloudRain, CloudSun, Droplet, Mail, Plane, Shovel, Sprout, Sun } from "lucide-react";
import type { Analysis, Reminder } from "@/lib/types";
import { Ago } from "./ui/Ago";
import { Badge } from "./ui/Badge";
import { Card, Empty } from "./ui/Card";

/** What the Weather Agent told the Plant Doctor at its last check-up. */
export function WeatherCard({ analysis, className = "" }: { analysis: Analysis | null; className?: string }) {
  const weather = analysis?.weather;
  const available = weather && weather.source !== "unavailable";

  return (
    <Card
      className={className}
      title={
        <span className="flex items-center gap-2">
          <CloudSun className="size-4 text-brand" aria-hidden /> Weather outside
        </span>
      }
      action={available && <span className="text-xs text-ink-3">{weather.location}</span>}
    >
      {!weather ? (
        <Empty>The weather is checked at each Plant Doctor check-up.</Empty>
      ) : !available ? (
        <Empty>The forecast can&apos;t be reached right now, so the advice uses the sensors alone.</Empty>
      ) : (
        <>
          <dl className="grid grid-cols-3 divide-x divide-line rounded-lg border border-line">
            <Figure label="Now" value={weather.temperature_c} unit="°C" />
            <Figure label="High" value={weather.max_temperature_c} unit="°C" />
            <Figure label="Humidity" value={weather.humidity} unit="%" />
          </dl>
          <p className="mt-3 text-sm leading-relaxed text-ink-2">{weather.summary}</p>
          {(weather.heat_alert || weather.rain_expected) && (
            <div className="mt-3 flex flex-wrap gap-2">
              {weather.heat_alert && (
                <Badge tone="serious">
                  <Sun className="size-3.5" aria-hidden /> Hot day: soil dries faster
                </Badge>
              )}
              {weather.rain_expected && (
                <Badge tone="info">
                  <CloudRain className="size-3.5" aria-hidden /> Rain won&apos;t water an indoor plant
                </Badge>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function Figure({ label, value, unit }: { label: string; value: number | null; unit: string }) {
  return (
    <div className="px-3 py-2.5">
      <dt className="text-[0.7rem] text-ink-3">{label}</dt>
      <dd className="text-lg font-semibold text-ink">{value === null ? "--" : `${Math.round(value)}${unit}`}</dd>
    </div>
  );
}

const REMINDER_ICONS: Record<Reminder["kind"], typeof Mail> = {
  watering: Droplet,
  fertilising: Sprout,
  repotting: Shovel,
  travel: Plane,
  other: Mail,
};

/** Plant-care and travel emails the Notification Agent found in the owner's inbox. */
export function RemindersCard({ analysis, className = "" }: { analysis: Analysis | null; className?: string }) {
  const notifications = analysis?.notifications;

  let empty: string | null = null;
  if (!notifications) empty = "Inbox reminders are checked at each Plant Doctor check-up.";
  else if (notifications.source === "not-configured")
    empty = "Email isn't connected, so inbox reminders aren't included. Set EMAIL_ADDRESS in the backend to add them.";
  else if (notifications.source === "unavailable") empty = "The inbox can't be reached right now.";
  else if (notifications.reminders.length === 0) empty = "No plant-care or travel emails in the last 7 days.";

  return (
    <Card
      className={className}
      title={
        <span className="flex items-center gap-2">
          <Mail className="size-4 text-brand" aria-hidden /> Inbox reminders
        </span>
      }
      action={notifications && !empty && <Badge tone="brand">{notifications.reminders.length}</Badge>}
    >
      {empty ? (
        <Empty>{empty}</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {notifications!.reminders.map((reminder, i) => {
            const Icon = REMINDER_ICONS[reminder.kind] ?? Mail;
            return (
              <li key={i} className="flex gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-brand-soft">
                  <Icon className="size-4 text-brand" aria-hidden />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{reminder.title}</p>
                  {reminder.detail && <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{reminder.detail}</p>}
                  {reminder.received && (
                    <p className="mt-0.5 text-xs text-ink-3">
                      <Ago time={reminder.received} />
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
