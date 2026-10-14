"use client";

import { useCallback, useEffect, useState } from "react";
import { loginUrl } from "./auth";

/** An error answer from the bridge: its message, status and, for some, a `reason` the page can act on. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly reason?: string,
  ) {
    super(message);
  }
}

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    headers: init?.body ? { "content-type": "application/json" } : undefined,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    // Signed out or the session ran out: sign in again, then come back here.
    if (response.status === 401 && !url.startsWith("/api/auth/")) window.location.assign(loginUrl());
    const detail = body?.detail;
    // 429 without a detail comes from Nginx's limit on sign-in attempts.
    const message =
      typeof detail === "string"
        ? detail
        : response.status === 429
          ? "Too many attempts. Wait a minute and try again."
          : `The server answered ${response.status}.`;
    throw new ApiError(message, response.status, body?.reason);
  }
  return body as T;
}

/** Fetch `url` now and every `intervalMs` (slower while the tab is hidden). The last good data stays
 * on screen while a new URL loads, so charts keep their frame instead of flashing empty. */
export function usePolling<T>(url: string | null, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const body = await api<T>(url);
        if (!cancelled) {
          setData(body);
          setLoadedUrl(url);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) timer = setTimeout(load, document.hidden ? intervalMs * 4 : intervalMs);
      }
    };
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [url, intervalMs, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, refresh, stale: url !== loadedUrl };
}

/** The current time, updated every `intervalMs`, for "8 s ago" labels. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
