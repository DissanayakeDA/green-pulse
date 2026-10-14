import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth";

// Pages need the session cookie; without one, go to the sign-in page first. This is only the quick
// redirect: the bridge checks the session itself on every /api call, so a stale or fake cookie gets a
// 401 there and the page then sends the browser to /login (lib/hooks.ts).
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  const login = new URL("/login", request.url);
  if (pathname !== "/") login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except the sign-in pages, the API (it answers 401 itself) and static files.
  matcher: ["/((?!login|register|api|_next/static|_next/image|icon.svg|favicon.ico).*)"],
};
