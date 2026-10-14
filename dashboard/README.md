# GreenPulse dashboard (Next.js)

An admin-style dashboard for GreenPulse (light theme, green), next to the technical Node-RED
dashboard. A sidebar leads to five pages:

| Page | What it shows |
|---|---|
| **Overview** | KPI tiles (care priority, soil moisture, temperature, air humidity, last watered) with 6-hour trends; the Plant Doctor's advice; the soil gauge; a 24-hour chart; watering controls; recent pump activity; weather and inbox reminders |
| **Readings** | Low / average / high per reading, a chart for each over 1, 6 or 24 hours, a readings log, and CSV export |
| **Watering** | *Water now* and the auto-watering switch (the same MQTT commands as Node-RED), the auto-watering rules checked against the current state, and the pump activity log |
| **AI Assistant** | The chat on a full page, next to the current readings and what the assistant can look at |
| **Plant profiles** | Which plant the device is watching, every known plant with its ideal ranges, and **Add plant**: type a name, the AI drafts its care profile, a checkpoint corrects impossible ranges, you review and save. *Use* switches the device to that plant; the Plant Doctor re-checks within about 10 s |
| **Plant & device** | The active plant and its ideal ranges, the device, the Plant Doctor's last analysis, weather and inbox reminders |

**Ask AI** in the top bar opens the same chat as a side panel on any page, for questions like "How is
my plant doing?", "Does it need water today?" or "When was it last watered?". The care priority
uses the same colours as the device's RGB LED.

```
browser ──▶ Next.js (this folder, port 3000) ──/api/*──▶ bridge's dashboard API (127.0.0.1:8000)
                                                            │  readings, advice, pump events (in memory)
                                                            │  Chat Agent (LLM + read-only tools)
                                                            └─ MQTT ◀──▶ ESP32
```

The browser only talks to Next.js; `src/app/api/[...path]/route.ts` forwards `/api/*` to the bridge, so
the bridge's API never has to be reachable from outside the server.

## Run it

Needs Node.js 20.9 or later, and the bridge running on the same computer (it serves the API).

```powershell
# terminal 1: the backend
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements.txt               # adds fastapi, uvicorn, tzdata
python -m greenpulse_ai.bridge                # live: the ESP32 over MQTT
python -m greenpulse_ai.bridge --demo         # or: a simulated ESP32, no hardware or broker needed

# terminal 2: the dashboard
cd dashboard
npm install
npm run dev                                   # http://localhost:3000
```

`--demo` fills the last 24 hours with simulated readings and keeps a simulated device running, so
the whole dashboard and the chat can be tried without the hardware. `--demo 25` starts with dry soil
to show the high-priority advice and auto-watering. Add `--offline` to either command to skip the LLM.

If the bridge's API runs somewhere else, copy `.env.example` to `.env.local` and set
`GREENPULSE_API_URL`.

For production: `npm run build`, then `npm run start` (see [docs/deployment.md](../docs/deployment.md)
for the EC2 service).

## Signing in

Every page needs an account. **Register** asks for a name, email, password and the registration code
(`REGISTRATION_CODE` in `backend/.env`, given to the people you trust); **Sign in** takes the email and
password. Your name and a **Sign out** button are at the bottom of the sidebar. Signing out also clears
this browser's saved chat.

`src/proxy.ts` sends anyone without the session cookie to `/login` (and back to the page they wanted
afterwards). That redirect is only for convenience: the bridge checks the session on every `/api` call,
and a 401 from it also leads to `/login`. The cookie is set by the bridge and passed through by the
`/api` route; it is `HttpOnly`, and `Secure` when the site is served over HTTPS.

## The chat

Each question goes to the bridge's Chat Agent (`backend/greenpulse_ai/agents/chat.py`). The LLM
decides which of four read-only tools to call before it answers: **live readings**, the **Plant Doctor
report**, the **sensor history** and the **watering log**. Under each answer the dashboard shows
which ones it looked at.

- It cannot water the plant or change settings; it points to the *Water now* button instead.
- Without an LLM key, or if the LLM fails, it gives a rule-based summary of the current status
  (marked "Quick answer").
- The conversation is kept in this browser (local storage); the last 10 messages go along with
  each question so follow-ups work.

## Email alerts

The **Email alerts** page collects the addresses that get plant alerts, device-offline notices and a
daily summary. Each address is sent a 6-digit code and gets nothing else until the code is entered
on the page. Each address chooses "high and critical" or "critical only", and whether it gets the
daily summary. The page also lists the last emails sent and any sending errors. The bridge sends
the emails (`backend/greenpulse_ai/alerts.py`; set `SMTP_HOST` in `backend/.env`, see the
[backend README](../backend/README.md#email-alerts-and-daily-summaries)).

## Layout

```
src/app/                          one folder per page (readings/, watering/, assistant/, plants/, plant/, alerts/, login/, register/; / is the overview)
src/proxy.ts                      sends signed-out visitors to /login
src/app/api/[...path]/route.ts    forwards /api/* to the bridge
src/components/shell/             sidebar, top bar (device picker, live status, Ask AI), chat side panel
src/components/views/             the content of each page
src/components/ui/                card, badges, KPI tile, sparkline
src/components/MetricChart.tsx    a reading over time (Recharts), ideal range shaded, waterings marked
src/components/SoilGauge.tsx      the pot gauge
src/components/AdviceCard.tsx     the Plant Doctor's advice
src/components/WateringControls.tsx  Water now + auto-watering switch
src/components/ChatPanel.tsx      the chat
src/lib/dashboard.tsx             polls the bridge once for every page (status every 5 s, history every minute)
src/lib/                          API types, formatting, polling and chat hooks, navigation
```

With more than one device, the top bar shows a device picker; the choice is remembered in the browser.
