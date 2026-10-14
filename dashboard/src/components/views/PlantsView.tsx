"use client";

import { useCallback, useState } from "react";
import { Leaf, Pencil, Plus, Trash2 } from "lucide-react";
import type { PlantProfile } from "@/lib/types";
import { PLANT_SOURCE, rangeText } from "@/lib/format";
import { api, usePolling } from "@/lib/hooks";
import { useDashboard } from "@/lib/dashboard";
import { PlantEditor, type EditorMode } from "../PlantEditor";
import { Badge } from "../ui/Badge";
import { Card, PageHeader } from "../ui/Card";
import { Loading } from "./Loading";

export function PlantsView() {
  const { deviceId, snapshot: s, refresh } = useDashboard();
  const list = usePolling<{ default: string; plants: PlantProfile[] }>("/api/plants", 30_000);
  const [editor, setEditor] = useState<EditorMode | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeKey = s?.plant.key ?? null;

  const reload = useCallback(() => {
    list.refresh();
    refresh();
  }, [list, refresh]);

  async function act(key: string, request: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await request();
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setConfirming(null);
    }
  }

  const use = (key: string) =>
    deviceId && act(key, () => api(`/api/devices/${encodeURIComponent(deviceId)}/plant`, { method: "PUT", body: JSON.stringify({ key }) }));
  const remove = (key: string) => act(key, () => api(`/api/plants/${key}`, { method: "DELETE" }));

  if (!s) return <Loading />;
  const plants = list.data?.plants ?? [];

  return (
    <>
      <PageHeader
        title="Plant profiles"
        description="Every plant needs different care. The sensors, the Plant Doctor, auto-watering and the assistant all judge against the active plant's profile."
        actions={
          <button
            type="button"
            onClick={() => setEditor({ kind: "add" })}
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-3.5 py-2 text-sm font-semibold text-white shadow-card hover:bg-brand-strong"
          >
            <Plus className="size-4" aria-hidden /> Add plant
          </button>
        }
      />

      <Card bodyClassName="p-5">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] lg:items-center">
          <div className="flex gap-4">
            <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-brand-soft">
              <Leaf className="size-6 text-brand" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-ink-3">{deviceId} is watching</p>
              <p className="text-xl font-bold tracking-tight text-ink">{s.plant.name}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {s.plant.scientific_name && <span className="text-sm text-ink-2 italic">{s.plant.scientific_name}</span>}
                <Badge tone={PLANT_SOURCE[s.plant.source].tone}>{PLANT_SOURCE[s.plant.source].label}</Badge>
              </div>
              {s.plant.care_notes && <p className="mt-2 text-sm text-ink-2">{s.plant.care_notes}</p>}
            </div>
          </div>
          <dl className="grid grid-cols-3 divide-x divide-line rounded-lg border border-line bg-brand-softer">
            {(
              [
                ["Soil moisture", s.plant.moisture, "%"],
                ["Temperature", s.plant.temperature, "°C"],
                ["Air humidity", s.plant.humidity, "%"],
              ] as const
            ).map(([label, range, unit]) => (
              <div key={label} className="px-3 py-3 text-center">
                <dt className="text-[0.7rem] text-ink-3">{label}</dt>
                <dd className="mt-0.5 text-base font-semibold text-ink tabular-nums">{rangeText(range, unit)}</dd>
              </div>
            ))}
          </dl>
        </div>
        <p className="mt-4 border-t border-line pt-3 text-xs text-ink-3">
          When you switch plants or edit the active one, the Plant Doctor re-checks with the next reading (within about 10 seconds).
        </p>
      </Card>

      {error && (
        <p role="alert" className="mt-6 rounded-xl border border-critical/30 bg-critical-bg px-4 py-3 text-sm text-critical-ink">
          {error}
        </p>
      )}

      <Card className="mt-6" title="All plants" subtitle="Built-in profiles and the plants you added" bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[52rem] text-left text-sm">
            <thead className="bg-sunk text-xs text-ink-3">
              <tr>
                <th className="px-5 py-2.5 font-medium">Plant</th>
                <th className="px-4 py-2.5 font-medium">Soil moisture</th>
                <th className="px-4 py-2.5 font-medium">Temperature</th>
                <th className="px-4 py-2.5 font-medium">Air humidity</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-5 py-2.5 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {plants.map((plant) => {
                const active = plant.key === activeKey;
                const editable = plant.source !== "built-in";
                return (
                  <tr key={plant.key} className={`border-t border-line ${active ? "bg-brand-softer" : "hover:bg-hover"}`}>
                    <td className="px-5 py-3">
                      <p className="font-medium text-ink">{plant.name}</p>
                      {plant.scientific_name && <p className="text-xs text-ink-3 italic">{plant.scientific_name}</p>}
                    </td>
                    <td className="px-4 py-3 text-ink-2 tabular-nums">{rangeText(plant.moisture, "%")}</td>
                    <td className="px-4 py-3 text-ink-2 tabular-nums">{rangeText(plant.temperature, "°C")}</td>
                    <td className="px-4 py-3 text-ink-2 tabular-nums">{rangeText(plant.humidity, "%")}</td>
                    <td className="px-4 py-3">
                      <Badge tone={PLANT_SOURCE[plant.source].tone}>{PLANT_SOURCE[plant.source].label}</Badge>
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center justify-end gap-1.5">
                        {active ? (
                          <Badge tone="good" dot>
                            Active
                          </Badge>
                        ) : (
                          <button
                            type="button"
                            onClick={() => use(plant.key)}
                            disabled={busy !== null || !deviceId}
                            className="rounded-lg border border-brand/30 px-2.5 py-1 text-xs font-semibold text-brand-ink hover:bg-brand-soft disabled:opacity-50"
                          >
                            {busy === plant.key ? "Switching…" : "Use"}
                          </button>
                        )}
                        {editable && (
                          <>
                            <button
                              type="button"
                              onClick={() => setEditor({ kind: "edit", plant })}
                              aria-label={`Edit ${plant.name}`}
                              className="rounded-lg p-1.5 text-ink-3 hover:bg-hover hover:text-ink"
                            >
                              <Pencil className="size-4" />
                            </button>
                            {confirming === plant.key ? (
                              <button
                                type="button"
                                onClick={() => remove(plant.key)}
                                disabled={busy !== null}
                                className="rounded-lg bg-critical px-2.5 py-1 text-xs font-semibold text-white"
                              >
                                Delete?
                              </button>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setConfirming(plant.key)}
                                aria-label={`Delete ${plant.name}`}
                                className="rounded-lg p-1.5 text-ink-3 hover:bg-critical-bg hover:text-critical-ink"
                              >
                                <Trash2 className="size-4" />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {plants.length > 0 && plants.every((p) => p.source === "built-in") && (
          <p className="border-t border-line px-5 py-3 text-xs text-ink-3">
            Growing something else? Use <span className="font-semibold text-ink-2">Add plant</span> and the AI drafts its care profile.
          </p>
        )}
      </Card>

      {editor && (
        <PlantEditor
          mode={editor}
          deviceId={deviceId}
          activeKey={activeKey}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null);
            reload();
          }}
        />
      )}
    </>
  );
}
