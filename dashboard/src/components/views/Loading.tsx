"use client";

import { useDashboard } from "@/lib/dashboard";

export function Loading() {
  const { error } = useDashboard();
  if (error) return null; // the shell already explains what's wrong
  return (
    <div className="grid place-items-center rounded-xl border border-line bg-surface py-24 text-sm text-ink-3 shadow-card">
      Connecting to your GreenPulse…
    </div>
  );
}
