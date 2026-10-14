// Forwards /api/* to the bridge's dashboard API (backend/greenpulse_ai/api.py), so the browser only
// ever talks to this Next.js server and the API itself can stay on localhost.

const API_URL = process.env.GREENPULSE_API_URL ?? "http://127.0.0.1:8000";

export const dynamic = "force-dynamic";

async function forward(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (path.some((segment) => segment === "." || segment === "..")) {
    return Response.json({ detail: "Not found" }, { status: 404 }); // would resolve outside /api/
  }
  const search = new URL(request.url).search;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${search}`, API_URL);
  const hasBody = request.method === "POST" || request.method === "PUT";
  // The session cookie goes to the bridge, which checks it; X-Forwarded-Proto (from Nginx) tells it to mark
  // the cookie Secure.
  const headers = new Headers();
  if (hasBody) headers.set("content-type", "application/json");
  for (const name of ["cookie", "x-forwarded-proto"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(120_000), // a chat answer can take a few LLM calls
    });
    const out = new Headers({
      "content-type": response.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    });
    for (const cookie of response.headers.getSetCookie()) out.append("set-cookie", cookie); // sign in / out
    return new Response(response.body, { status: response.status, headers: out });
  } catch {
    return Response.json(
      { detail: "The GreenPulse server can't be reached. Check that the bridge is running." },
      { status: 502 },
    );
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as DELETE };
