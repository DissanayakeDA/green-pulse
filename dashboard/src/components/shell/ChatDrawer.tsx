"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { plantName } from "@/lib/format";
import { useDashboard } from "@/lib/dashboard";
import { ChatPanel } from "../ChatPanel";

/** The chat as a slide-over from the right, on every page except the AI Assistant page itself. */
export function ChatDrawer() {
  const pathname = usePathname();
  const { chat, chatOpen, setChatOpen, snapshot } = useDashboard();
  const open = chatOpen && pathname !== "/assistant";
  const plant = snapshot ? plantName(snapshot.plant).name : "plant";

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => event.key === "Escape" && setChatOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open, setChatOpen]);

  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/20" onClick={() => setChatOpen(false)} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Ask AI"
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-line bg-surface shadow-2xl"
      >
        <ChatPanel chat={chat} plant={plant} onClose={() => setChatOpen(false)} />
      </div>
    </>
  );
}
