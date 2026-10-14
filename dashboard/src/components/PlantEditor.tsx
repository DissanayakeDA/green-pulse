"use client";

import { useEffect, useId, useState } from "react";
import { CircleCheck, ShieldAlert, Sparkles, TriangleAlert, X } from "lucide-react";
import type { PlantProfile, ProfileDraft, Range } from "@/lib/types";
import { modelName } from "@/lib/format";
import { api } from "@/lib/hooks";
import { Badge } from "./ui/Badge";

export type EditorMode = { kind: "add" } | { kind: "edit"; plant: PlantProfile };

type Field = "moisture" | "temperature" | "humidity";
const FIELDS: { field: Field; label: string; unit: string; hint?: string }[] = [
  { field: "moisture", label: "Soil moisture", unit: "%", hint: "Sensor scale: 0% is bone-dry soil, 100% is soil standing in water" },
  { field: "temperature", label: "Temperature", unit: "°C" },
  { field: "humidity", label: "Air humidity", unit: "%" },
];

interface Form {
  name: string;
  scientific_name: string;
  moisture: [string, string];
  temperature: [string, string];
  humidity: [string, string];
  care_notes: string;
  source: "ai" | "custom";
}

const pair = ([low, high]: Range): [string, string] => [String(low), String(high)];
const fromPlant = (p: Pick<PlantProfile, "name" | "scientific_name" | Field | "care_notes">, source: Form["source"]): Form => ({
  name: p.name,
  scientific_name: p.scientific_name,
  moisture: pair(p.moisture),
  temperature: pair(p.temperature),
  humidity: pair(p.humidity),
  care_notes: p.care_notes,
  source,
});

/** Add a plant (the AI drafts its profile from the name) or edit one, as a panel from the right. */
export function PlantEditor({
  mode,
  deviceId,
  activeKey,
  onClose,
  onSaved,
}: {
  mode: EditorMode;
  deviceId: string | null;
  activeKey: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const ids = useId();
  const editing = mode.kind === "edit" ? mode.plant : null;
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<ProfileDraft | null>(null);
  const [form, setForm] = useState<Form | null>(editing ? fromPlant(editing, editing.source === "ai" ? "ai" : "custom") : null);
  const [useForDevice, setUseForDevice] = useState(!editing);
  const [busy, setBusy] = useState<"suggest" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  async function suggest() {
    setBusy("suggest");
    setError(null);
    try {
      const suggestion = await api<ProfileDraft>("/api/plants/suggest", { method: "POST", body: JSON.stringify({ name: query.trim() }) });
      setDraft(suggestion);
      setForm(fromPlant(suggestion, suggestion.source === "llm" ? "ai" : "custom"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function enterManually() {
    setDraft(null);
    setForm({ name: query.trim(), scientific_name: "", moisture: ["30", "65"], temperature: ["16", "30"], humidity: ["40", "75"], care_notes: "", source: "custom" });
  }

  async function save() {
    if (!form) return;
    const problem = validate(form);
    if (problem) return setError(problem);
    setBusy("save");
    setError(null);
    const body = JSON.stringify({
      name: form.name.trim(),
      scientific_name: form.scientific_name.trim(),
      moisture: form.moisture.map(Number),
      temperature: form.temperature.map(Number),
      humidity: form.humidity.map(Number),
      care_notes: form.care_notes.trim(),
      source: form.source,
    });
    try {
      const saved = editing
        ? await api<PlantProfile>(`/api/plants/${editing.key}`, { method: "PUT", body })
        : await api<PlantProfile>("/api/plants", { method: "POST", body });
      if (useForDevice && deviceId) {
        await api(`/api/devices/${encodeURIComponent(deviceId)}/plant`, { method: "PUT", body: JSON.stringify({ key: saved.key }) });
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f));
  const setRange = (field: Field, index: 0 | 1, value: string) =>
    setForm((f) => (f ? { ...f, [field]: (index === 0 ? [value, f[field][1]] : [f[field][0], value]) as [string, string] } : f));

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/20" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-labelledby={`${ids}-title`} className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-line bg-surface shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 id={`${ids}-title`} className="text-sm font-semibold text-ink">
              {editing ? `Edit ${editing.name}` : "Add a plant"}
            </h2>
            <p className="text-xs text-ink-3">The ranges every reading is checked against</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-ink-3 hover:bg-hover hover:text-ink">
            <X className="size-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5">
          {!form && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (query.trim().length >= 2) suggest();
              }}
            >
              <label htmlFor={`${ids}-query`} className="text-sm font-medium text-ink">
                Plant name
              </label>
              <input
                id={`${ids}-query`}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                maxLength={60}
                autoFocus
                placeholder="e.g. Aloe vera, Monstera, Boston fern"
                className="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
              />
              <p className="mt-2 text-xs leading-relaxed text-ink-3">
                The AI drafts this plant&apos;s ideal soil moisture, temperature and humidity. A checkpoint keeps its numbers within
                what the sensors can measure, and you can change everything before saving.
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  type="submit"
                  disabled={query.trim().length < 2 || busy !== null}
                  className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white shadow-card hover:bg-brand-strong disabled:bg-line-strong"
                >
                  <Sparkles className="size-4" aria-hidden />
                  {busy === "suggest" ? "Drafting the profile…" : "Get care profile"}
                </button>
                <button type="button" onClick={enterManually} disabled={busy !== null} className="text-sm font-medium text-ink-2 hover:text-ink">
                  Enter ranges myself
                </button>
              </div>
            </form>
          )}

          {form && draft && <Checkpoint draft={draft} />}

          {form && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField id={`${ids}-name`} label="Name" value={form.name} onChange={(name) => set({ name })} maxLength={60} />
                <TextField
                  id={`${ids}-latin`}
                  label="Scientific name (optional)"
                  value={form.scientific_name}
                  onChange={(scientific_name) => set({ scientific_name })}
                  maxLength={80}
                />
              </div>

              <fieldset className="rounded-lg border border-line">
                <legend className="ml-3 px-1 text-sm font-medium text-ink">Ideal ranges</legend>
                <div className="divide-y divide-line">
                  {FIELDS.map(({ field, label, unit, hint }) => (
                    <div key={field} className="px-3.5 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm text-ink-2">{label}</span>
                        <span className="flex items-center gap-2 text-sm">
                          <NumberInput label={`${label} lowest`} value={form[field][0]} onChange={(v) => setRange(field, 0, v)} />
                          <span className="text-ink-3">to</span>
                          <NumberInput label={`${label} highest`} value={form[field][1]} onChange={(v) => setRange(field, 1, v)} />
                          <span className="w-6 text-ink-3">{unit}</span>
                        </span>
                      </div>
                      {hint && <p className="mt-1 text-[0.7rem] text-ink-3">{hint}</p>}
                    </div>
                  ))}
                </div>
              </fieldset>

              <div>
                <label htmlFor={`${ids}-notes`} className="text-sm font-medium text-ink">
                  Care notes
                </label>
                <textarea
                  id={`${ids}-notes`}
                  value={form.care_notes}
                  onChange={(event) => set({ care_notes: event.target.value })}
                  maxLength={400}
                  rows={3}
                  placeholder="How this plant likes to be watered"
                  className="mt-1.5 w-full resize-none rounded-lg border border-line-strong px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
                />
                <p className="text-[0.7rem] text-ink-3">The Plant Doctor and the assistant read these with every answer.</p>
              </div>

              {deviceId && editing?.key !== activeKey && (
                <label className="flex items-center gap-2.5 text-sm text-ink">
                  <input type="checkbox" checked={useForDevice} onChange={(event) => setUseForDevice(event.target.checked)} className="size-4 accent-[var(--brand)]" />
                  Use this plant for {deviceId} now
                </label>
              )}
            </div>
          )}

          {error && (
            <p role="alert" className="rounded-lg border border-critical/30 bg-critical-bg px-3.5 py-2.5 text-sm text-critical-ink">
              {error}
            </p>
          )}
        </div>

        {form && (
          <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3.5">
            <button type="button" onClick={onClose} className="rounded-lg px-3.5 py-2 text-sm font-medium text-ink-2 hover:bg-hover">
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={busy !== null}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white shadow-card hover:bg-brand-strong disabled:bg-line-strong"
            >
              {busy === "save" ? "Saving…" : editing ? "Save changes" : "Save plant"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}

/** What the AI suggested, and what the checkpoint changed before showing it. */
function Checkpoint({ draft }: { draft: ProfileDraft }) {
  const fromAi = draft.source === "llm";
  return (
    <div className="rounded-xl border border-line bg-sunk p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={fromAi ? "brand" : "neutral"}>{fromAi ? `AI draft · ${modelName(draft.model) ?? "LLM"}` : "Offline suggestion"}</Badge>
        {!draft.recognised && <Badge tone="warning">Plant not recognised</Badge>}
      </div>
      {draft.note && (
        <p className={`mt-3 flex gap-2 text-xs ${draft.recognised ? "text-ink-2" : "text-warning-ink"}`}>
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {draft.note}
        </p>
      )}
      {draft.checks.length ? (
        <div className="mt-3 text-xs">
          <p className="flex items-center gap-2 font-semibold text-serious-ink">
            <ShieldAlert className="size-3.5" aria-hidden /> Checkpoint corrected {draft.checks.length} range{draft.checks.length > 1 ? "s" : ""}
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-2">
            {draft.checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-3 flex items-center gap-2 text-xs text-good-ink">
          <CircleCheck className="size-3.5" aria-hidden /> Checkpoint passed: every range is within what the sensors measure
        </p>
      )}
    </div>
  );
}

function TextField({ id, label, value, onChange, maxLength }: { id: string; label: string; value: string; onChange: (v: string) => void; maxLength: number }) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        maxLength={maxLength}
        className="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
      />
    </div>
  );
}

function NumberInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="number"
      inputMode="decimal"
      step="any"
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-20 rounded-lg border border-line-strong px-2.5 py-1.5 text-right text-sm tabular-nums outline-none focus:border-brand focus:ring-2 focus:ring-brand/15"
    />
  );
}

function validate(form: Form): string | null {
  if (form.name.trim().length < 2) return "Give the plant a name.";
  for (const { field, label } of FIELDS) {
    const [low, high] = form[field].map((v) => (v.trim() === "" ? NaN : Number(v)));
    if (Number.isNaN(low) || Number.isNaN(high)) return `${label}: enter both numbers.`;
    if (low >= high) return `${label}: the lowest value must be below the highest.`;
  }
  return null;
}
