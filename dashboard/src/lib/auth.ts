// Dashboard accounts (backend/greenpulse_ai/accounts.py): the session cookie, who is signed in, and where
// to go after signing in or out.

export const SESSION_COOKIE = "gp_session";

export interface Account {
  id: string;
  name: string;
  email: string;
  created_at: string;
}

export interface Me {
  account: Account | null;
  registration_open: boolean;
}

/** The page to open after signing in: ?next=… when it is a page on this site, else the overview. */
export function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

/** The sign-in page, coming back to this page afterwards. */
export function loginUrl(): string {
  const here = window.location.pathname + window.location.search;
  return here === "/" ? "/login" : `/login?next=${encodeURIComponent(here)}`;
}

/** End the session, forget this browser's chat (the next person to sign in here shouldn't see it), and go
 * to the sign-in page. */
export async function signOut(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST", cache: "no-store" });
  } finally {
    try {
      Object.keys(localStorage)
        .filter((key) => key.startsWith("greenpulse-chat:"))
        .forEach((key) => localStorage.removeItem(key));
    } catch {
      // storage blocked: nothing was saved
    }
    window.location.assign("/login");
  }
}
