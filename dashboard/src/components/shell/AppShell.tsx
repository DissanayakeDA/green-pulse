"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { TriangleAlert } from "lucide-react";
import { DashboardProvider, useDashboard } from "@/lib/dashboard";
import { ChatDrawer } from "./ChatDrawer";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <DashboardProvider>
      <Shell>{children}</Shell>
    </DashboardProvider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();
  const { error } = useDashboard();

  useEffect(() => setNavOpen(false), [pathname]);

  return (
    <div className="min-h-dvh lg:pl-64">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-h-dvh flex-col">
        <Topbar onMenu={() => setNavOpen(true)} />
        <main className="mx-auto w-full max-w-[96rem] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {error && (
            <div role="alert" className="mb-6 flex items-start gap-3 rounded-xl border border-critical/30 bg-critical-bg px-4 py-3 text-sm">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden />
              <p className="text-ink-2">
                <span className="font-semibold text-critical-ink">Can&apos;t reach the GreenPulse server.</span> {error} This page
                reconnects by itself.
              </p>
            </div>
          )}
          {children}
        </main>
      </div>
      <ChatDrawer />
    </div>
  );
}
