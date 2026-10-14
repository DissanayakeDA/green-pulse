"use client";

import { useEffect, useState, type FormEvent } from "react";
import { BellRing, Mail, Send, ShieldCheck, Sunrise, Trash2, WifiOff } from "lucide-react";
import type { AlertRecipient, AlertSettings, SentEmail } from "@/lib/types";
import { clock, type Tone } from "@/lib/format";
import { api, usePolling } from "@/lib/hooks";
import { Ago } from "../ui/Ago";
import { Badge } from "../ui/Badge";
import { Card, Empty, PageHeader, Segmented } from "../ui/Card";
import { Switch } from "../ui/Switch";
import { Loading } from "./Loading";

type Prefs = Pick<AlertRecipient, "alerts" | "min_priority" | "daily">;

const KIND: Record<SentEmail["kind"], { label: string; tone: Tone }> = {
  alert: { label: "Plant alert", tone: "serious" },
  offline: { label: "Device offline", tone: "warning" },
  daily: { label: "Daily summary", tone: "info" },
  code: { label: "Sign-up code", tone: "neutral" },
  test: { label: "Test", tone: "neutral" },
};

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function hour(h: number): string {
  return `${String(h).padStart(2, "0")}:00`;
}

export function AlertsView() {
  const { data, error, refresh } = usePolling<AlertSettings>("/api/alerts", 15_000);
  const [justAdded, setJustAdded] = useState<string | null>(null);

  if (!data) {
    return error ? (
      <p role="alert" className="rounded-xl border border-critical/30 bg-critical-bg px-4 py-3 text-sm text-critical-ink">
        {error}
      </p>
    ) : (
      <Loading />
    );
  }

  return (
    <>
      <PageHeader title="Email alerts" description="Get an email when your plant needs you, and a short summary every morning." />

      {!data.configured && <SetupNote />}

      <div className="grid gap-6 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Who gets emails"
          subtitle={data.sender ? `Sent from ${data.sender}` : "Not sending yet"}
          bodyClassName="p-0"
        >
          <AddRecipient
            disabled={!data.configured}
            onAdded={(id) => {
              setJustAdded(id);
              refresh();
            }}
          />
          {data.recipients.length === 0 ? (
            <div className="p-5">
              <Empty>No one gets emails yet. Add an address above.</Empty>
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {data.recipients.map((r) => (
                <RecipientRow key={r.id} recipient={r} settings={data} autoFocus={r.id === justAdded} onChange={refresh} />
              ))}
            </ul>
          )}
        </Card>

        <Card title="What gets sent">
          <ul className="space-y-4 text-sm">
            <li className="flex gap-3">
              <BellRing className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
              <p className="text-ink-2">
                <span className="font-semibold text-ink">Plant alerts</span> when the Plant Doctor says &ldquo;Act within 2
                hours&rdquo; or &ldquo;Act now&rdquo;. One email when it starts, another if it gets worse, and a reminder every{" "}
                {data.rules.repeat_after_h} hours while it lasts.
              </p>
            </li>
            <li className="flex gap-3">
              <WifiOff className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
              <p className="text-ink-2">
                <span className="font-semibold text-ink">Device offline</span>, once, when a device hasn&apos;t reported for{" "}
                {data.rules.offline_after_min} minutes. Sent to everyone with plant alerts on.
              </p>
            </li>
            <li className="flex gap-3">
              <Sunrise className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
              <p className="text-ink-2">
                <span className="font-semibold text-ink">Daily summary</span> at {hour(data.daily_hour)} ({data.timezone}): each
                plant&apos;s state, the latest advice, the waterings and the reminders found in your inbox.
              </p>
            </li>
          </ul>
          <div className="mt-5 flex items-start gap-3 rounded-lg bg-brand-softer px-3.5 py-3 text-xs text-ink-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
            <p>Every new address gets a 6-digit code first. Nothing else is sent to it until the code is entered here.</p>
          </div>
        </Card>
      </div>

      <Card className="mt-6" title="Recent emails" subtitle="The last 25 since the server started, newest first" bodyClassName="p-0">
        {data.recent.length === 0 ? (
          <div className="p-5">
            <Empty>No emails sent since the server started.</Empty>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-left text-sm">
              <thead className="bg-sunk text-xs text-ink-3">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Sent</th>
                  <th className="px-4 py-2.5 font-medium">To</th>
                  <th className="px-4 py-2.5 font-medium">Type</th>
                  <th className="px-4 py-2.5 font-medium">Subject</th>
                  <th className="px-5 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((e, i) => (
                  <tr key={`${e.at}-${e.to}-${i}`} className="border-t border-line align-top">
                    <td className="px-5 py-3 whitespace-nowrap text-ink-2">
                      {clock(e.at)}
                      <span className="block text-xs text-ink-3">
                        <Ago time={e.at} />
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-2">{e.to}</td>
                    <td className="px-4 py-3">
                      <Badge tone={KIND[e.kind].tone}>{KIND[e.kind].label}</Badge>
                    </td>
                    <td className="px-4 py-3 text-ink">
                      {e.subject}
                      {e.error && <span className="mt-0.5 block text-xs text-critical-ink">{e.error}</span>}
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={e.ok ? "good" : "critical"} dot>
                        {e.ok ? "Sent" : "Failed"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function SetupNote() {
  return (
    <Card className="mb-6" title="Sending email isn't set up yet">
      <p className="text-sm text-ink-2">
        GreenPulse sends from the mailbox it reads reminders from. Add <code className="font-mono">SMTP_HOST</code> to{" "}
        <code className="font-mono">backend/.env</code> next to the address and app password, then restart the bridge:
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg bg-sunk p-3 font-mono text-xs text-ink-2">
        {"EMAIL_ADDRESS=you@yourdomain.com\nEMAIL_APP_PASSWORD=your-app-password\nSMTP_HOST=smtppro.zoho.com     # Gmail: smtp.gmail.com"}
      </pre>
    </Card>
  );
}

function AddRecipient({ disabled, onAdded }: { disabled: boolean; onAdded: (id: string) => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const added = await api<AlertRecipient>("/api/alerts/recipients", {
        method: "POST",
        body: JSON.stringify({ email: email.trim() }),
      });
      setEmail("");
      onAdded(added.id);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="border-b border-line p-5">
      <label htmlFor="alert-email" className="text-sm font-semibold text-ink">
        Add an email address
      </label>
      <p className="mt-0.5 text-xs text-ink-3">It gets a 6-digit code to confirm that it&apos;s right and that its owner wants the emails.</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          id="alert-email"
          type="email"
          required
          autoComplete="email"
          maxLength={254}
          placeholder="you@example.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={disabled}
          className="w-full rounded-lg border border-line-strong px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:bg-sunk"
        />
        <button
          type="submit"
          disabled={disabled || busy || !email.trim()}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white shadow-card hover:bg-brand-strong disabled:cursor-not-allowed disabled:bg-line-strong"
        >
          <Send className="size-4" aria-hidden />
          {busy ? "Sending code…" : "Send code"}
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-critical-ink">
          {error}
        </p>
      )}
    </form>
  );
}

function RecipientRow({
  recipient: r,
  settings,
  autoFocus,
  onChange,
}: {
  recipient: AlertRecipient;
  settings: AlertSettings;
  autoFocus: boolean;
  onChange: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"verify" | "code" | "test" | "remove" | "prefs" | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [pending, setPending] = useState<Prefs | null>(null); // shown until the server agrees
  const prefs: Prefs = pending ?? { alerts: r.alerts, min_priority: r.min_priority, daily: r.daily };
  const path = `/api/alerts/recipients/${r.id}`;

  useEffect(() => setPending(null), [r.alerts, r.min_priority, r.daily]);

  async function run(kind: NonNullable<typeof busy>, request: () => Promise<unknown>, success?: string) {
    setBusy(kind);
    setNote(null);
    try {
      await request();
      if (success) setNote({ ok: true, text: success });
      onChange();
    } catch (e) {
      if (kind === "prefs") setPending(null);
      setNote({ ok: false, text: message(e) });
    } finally {
      setBusy(null);
    }
  }

  const verify = (event: FormEvent) => {
    event.preventDefault();
    run(
      "verify",
      () => api(`${path}/verify`, { method: "POST", body: JSON.stringify({ code }) }),
      "Confirmed. This address now gets the emails you choose below.",
    );
  };
  const resend = () => {
    setCode("");
    run("code", () => api(`${path}/code`, { method: "POST" }), `A new code is on its way to ${r.email}.`);
  };
  const save = (change: Partial<Prefs>) => {
    const next = { ...prefs, ...change };
    setPending(next);
    run("prefs", () => api(path, { method: "PUT", body: JSON.stringify(next) }));
  };
  const test = () => run("test", () => api(`${path}/test`, { method: "POST" }), `Test email sent. Check the inbox (and the spam folder).`);
  const remove = () => run("remove", () => api(path, { method: "DELETE" }));

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-soft">
            <Mail className="size-4 text-brand" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">{r.email}</p>
            <p className="text-xs text-ink-3">
              Added <Ago time={r.added_at} />
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {r.verified ? (
            <Badge tone="good" dot>
              Confirmed
            </Badge>
          ) : (
            <Badge tone="warning" dot>
              Waiting for code
            </Badge>
          )}
          {r.verified && (
            <button
              type="button"
              onClick={test}
              disabled={busy !== null || !settings.configured}
              className="rounded-lg border border-brand/30 px-2.5 py-1 text-xs font-semibold text-brand-ink hover:bg-brand-soft disabled:opacity-50"
            >
              {busy === "test" ? "Sending…" : "Send test"}
            </button>
          )}
          {confirmingRemove ? (
            <button
              type="button"
              onClick={remove}
              disabled={busy !== null}
              className="rounded-lg bg-critical px-2.5 py-1 text-xs font-semibold text-white"
            >
              Remove?
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingRemove(true)}
              aria-label={`Remove ${r.email}`}
              className="rounded-lg p-1.5 text-ink-3 hover:bg-critical-bg hover:text-critical-ink"
            >
              <Trash2 className="size-4" />
            </button>
          )}
        </div>
      </div>

      {!r.verified ? (
        <form onSubmit={verify} className="mt-3 rounded-lg bg-sunk p-3.5">
          <label htmlFor={`code-${r.id}`} className="text-xs font-medium text-ink-2">
            {r.code_pending
              ? `Enter the 6-digit code sent to ${r.email}. It can take a minute; check the spam folder too.`
              : "That code can't be used any more. Send a new one."}
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              id={`code-${r.id}`}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="000000"
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              autoFocus={autoFocus}
              disabled={!r.code_pending}
              className="w-32 rounded-lg border border-line-strong bg-surface px-3 py-1.5 text-center text-base font-semibold tracking-[0.3em] tabular-nums outline-none focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:bg-sunk"
            />
            <button
              type="submit"
              disabled={code.length !== 6 || busy !== null || !r.code_pending}
              className="rounded-lg bg-brand px-3.5 py-1.5 text-sm font-semibold text-white hover:bg-brand-strong disabled:cursor-not-allowed disabled:bg-line-strong"
            >
              {busy === "verify" ? "Checking…" : "Confirm"}
            </button>
            <button
              type="button"
              onClick={resend}
              disabled={busy !== null || !settings.configured}
              className="px-1 text-xs font-semibold text-brand-ink hover:underline disabled:opacity-50"
            >
              {busy === "code" ? "Sending…" : "Send a new code"}
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="flex items-start justify-between gap-4 rounded-lg border border-line p-3.5">
            <div className="min-w-0">
              <p id={`alerts-${r.id}`} className="text-sm font-semibold text-ink">
                Plant alerts
              </p>
              <p className="mt-0.5 text-xs text-ink-3">When the plant needs you soon, or a device goes offline</p>
              {prefs.alerts && (
                <div className="mt-2.5">
                  <Segmented
                    label="Send plant alerts at"
                    options={[
                      { value: "high", label: "High and critical" },
                      { value: "critical", label: "Critical only" },
                    ]}
                    value={prefs.min_priority}
                    onChange={(min_priority) => save({ min_priority })}
                  />
                </div>
              )}
            </div>
            <Switch checked={prefs.alerts} onChange={(alerts) => save({ alerts })} disabled={busy !== null} labelledBy={`alerts-${r.id}`} />
          </div>
          <div className="flex items-start justify-between gap-4 rounded-lg border border-line p-3.5">
            <div className="min-w-0">
              <p id={`daily-${r.id}`} className="text-sm font-semibold text-ink">
                Daily summary
              </p>
              <p className="mt-0.5 text-xs text-ink-3">
                Every day at {hour(settings.daily_hour)} ({settings.timezone})
              </p>
            </div>
            <Switch checked={prefs.daily} onChange={(daily) => save({ daily })} disabled={busy !== null} labelledBy={`daily-${r.id}`} />
          </div>
        </div>
      )}

      {note && (
        <p role={note.ok ? "status" : "alert"} className={`mt-2 text-xs ${note.ok ? "text-good-ink" : "text-critical-ink"}`}>
          {note.text}
        </p>
      )}
    </li>
  );
}
