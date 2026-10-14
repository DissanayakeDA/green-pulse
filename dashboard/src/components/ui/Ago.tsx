"use client";

import { ago } from "@/lib/format";
import { useNow } from "@/lib/hooks";

/** "8 s ago", kept current. Its own timer, so the rest of the page doesn't re-render every second. */
export function Ago({ time }: { time: string | number | null }) {
  const now = useNow();
  return <time dateTime={time === null ? undefined : new Date(time).toISOString()}>{ago(time, now)}</time>;
}
