"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogOut, X } from "lucide-react";
import { NAV } from "@/lib/nav";
import { plantName } from "@/lib/format";
import { useDashboard } from "@/lib/dashboard";
import { signOut } from "@/lib/auth";
import { Badge } from "../ui/Badge";

export function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="8" fill="var(--brand)" />
        <path d="M16 26 C 10 25 6.5 21 6.5 16.5 C 6.5 11 11 8 16 4.5 C 21 8 25.5 11 25.5 16.5 C 25.5 21 22 25 16 26 Z" fill="#fff" />
        <path d="M16 25 L16 8.5" stroke="var(--brand)" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      <span className="leading-tight">
        <span className="block text-[0.95rem] font-bold tracking-tight text-ink">GreenPulse</span>
        <span className="block text-[0.7rem] text-ink-3">Smart plant care</span>
      </span>
    </span>
  );
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { snapshot, deviceId, health, account } = useDashboard();
  const plant = snapshot ? plantName(snapshot.plant) : null;

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-ink/30 lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-line bg-surface transition-transform lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Main navigation"
      >
        <div className="flex h-16 items-center justify-between border-b border-line px-5">
          <Logo />
          <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-3 hover:bg-hover lg:hidden" aria-label="Close menu">
            <X className="size-5" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5">
          {NAV.map((group) => (
            <div key={group.group} className="mb-6">
              <p className="mb-2 px-3 text-[0.7rem] font-semibold tracking-wider text-ink-3 uppercase">{group.group}</p>
              <ul className="space-y-0.5">
                {group.items.map(({ href, label, icon: Icon }) => {
                  const active = pathname === href;
                  return (
                    <li key={href}>
                      <Link
                        href={href}
                        aria-current={active ? "page" : undefined}
                        className={`relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                          active ? "bg-brand-soft font-semibold text-brand-ink" : "text-ink-2 hover:bg-hover hover:text-ink"
                        }`}
                      >
                        {active && <span className="absolute inset-y-1.5 left-0 w-1 rounded-r bg-brand" aria-hidden />}
                        <Icon className={`size-4.5 ${active ? "text-brand" : "text-ink-3"}`} aria-hidden />
                        {label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="m-3 rounded-xl border border-line bg-brand-softer p-3.5">
          <p className="text-xs text-ink-3">Monitoring</p>
          <p className="mt-0.5 text-sm font-semibold text-ink">{plant ? plant.name : "Your plant"}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone={snapshot?.online ? "good" : "neutral"} dot>
              {snapshot?.online ? "Online" : snapshot?.last_seen ? "Offline" : "Waiting"}
            </Badge>
            {deviceId && <span className="text-xs text-ink-3">{deviceId}</span>}
          </div>
          {health?.demo && (
            <p className="mt-2">
              <Badge tone="info">Demo · simulated data</Badge>
            </p>
          )}
        </div>

        {account && (
          <div className="flex items-center gap-3 border-t border-line px-4 py-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-bold text-brand-ink" aria-hidden>
              {initials(account.name)}
            </span>
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-sm font-semibold text-ink">{account.name}</p>
              <p className="truncate text-xs text-ink-3">{account.email}</p>
            </div>
            <button
              type="button"
              onClick={signOut}
              title="Sign out"
              className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-hover hover:text-ink"
            >
              <LogOut className="size-4" aria-hidden />
              <span className="sr-only">Sign out</span>
            </button>
          </div>
        )}
      </aside>
    </>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}
