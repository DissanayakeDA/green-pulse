"use client";

import { usePathname } from "next/navigation";
import { ChevronRight, Menu, Sparkles } from "lucide-react";
import { navItem } from "@/lib/nav";
import { useDashboard } from "@/lib/dashboard";
import { Ago } from "../ui/Ago";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const pathname = usePathname();
  const { devices, deviceId, selectDevice, snapshot, setChatOpen } = useDashboard();
  const page = navItem(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-surface/90 px-4 backdrop-blur sm:px-6 lg:px-8">
      <button type="button" onClick={onMenu} className="-ml-1 rounded-md p-1.5 text-ink-2 hover:bg-hover lg:hidden" aria-label="Open menu">
        <Menu className="size-5" />
      </button>

      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
        <span className="hidden text-ink-3 sm:inline">GreenPulse</span>
        <ChevronRight className="hidden size-3.5 text-ink-3 sm:inline" aria-hidden />
        <span className="truncate font-semibold text-ink">{page.label}</span>
      </nav>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        {devices.length > 1 ? (
          <label className="hidden items-center gap-2 text-xs text-ink-3 md:flex">
            Device
            <select
              value={deviceId ?? ""}
              onChange={(event) => selectDevice(event.target.value)}
              className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink"
            >
              {devices.map((d) => (
                <option key={d.device_id} value={d.device_id}>
                  {d.device_id}
                </option>
              ))}
            </select>
          </label>
        ) : (
          deviceId && <span className="hidden rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 md:inline">{deviceId}</span>
        )}

        <span className="hidden items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 sm:flex">
          <span className={`size-2 rounded-full ${snapshot?.online ? "bg-good" : "bg-line-strong"}`} aria-hidden />
          {snapshot?.online ? (
            <>
              Live · <Ago time={snapshot.last_seen} />
            </>
          ) : snapshot?.last_seen ? (
            <>
              Offline · <Ago time={snapshot.last_seen} />
            </>
          ) : (
            "Waiting for device"
          )}
        </span>

        {pathname !== "/assistant" && (
          <button
            type="button"
            onClick={() => setChatOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-3 py-2 text-sm font-semibold text-white shadow-card transition-colors hover:bg-brand-strong"
          >
            <Sparkles className="size-4" aria-hidden />
            <span className="hidden sm:inline">Ask AI</span>
          </button>
        )}
      </div>
    </header>
  );
}
