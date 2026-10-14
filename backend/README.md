# GreenPulse Agentic AI Core

Component 1 of 4 (Dissanayake D A, IT23306622): LLM integration, the Environment and Plant Doctor
agents, agent orchestration, prompts and final care-tip generation.

It runs two ways:

- **Live:** `python -m greenpulse_ai.bridge` connects to the MQTT broker, analyses real ESP32
  readings together with the live weather forecast and the reminders in your email, publishes the
  advice for Node-RED and the priority for the RGB LED, and runs the water pump when auto-watering
  is on. For the whole setup (wiring, firmware, broker, Node-RED), see
  [docs/integration.md](../docs/integration.md); for the cloud server, see
  [docs/deployment.md](../docs/deployment.md).
- **Offline demo:** `python -m greenpulse_ai` runs on **hardcoded dummy data**
  (`greenpulse_ai/dummy_data.py`): seven scenarios of sensor readings, weather and inbox messages,
  plus a fake ESP32 that streams readings over a simulated day.

The bridge also serves the **dashboard API** for the Next.js dashboard ([dashboard/](../dashboard/README.md)),
including the **Chat Agent** that answers questions such as "How is my plant doing?".
`python -m greenpulse_ai.bridge --demo` runs all of it against a simulated ESP32, without hardware or a broker.

## Quick start (Windows PowerShell)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m greenpulse_ai --list                 # the dummy scenarios
python -m greenpulse_ai                        # run the default scenario (drying_fast)
python -m greenpulse_ai --scenario overwatered --json   # show the full MQTT payloads
python -m greenpulse_ai --all                  # every scenario as a table
python -m greenpulse_ai --simulate             # fake ESP32 stream through the service
python -m greenpulse_ai --live-context         # dummy sensors + live weather and your real mailbox
python -m pytest                               # 168 tests, no API key, broker or network needed

python -m greenpulse_ai.bridge                 # live: real ESP32 readings over MQTT (MQTT_HOST in .env)
python -m greenpulse_ai.bridge --offline       # live, but rule-based agents only (no LLM cost)
python -m greenpulse_ai.bridge --demo          # simulated ESP32 + dashboard API, for the Next.js dashboard
```

With no API key everything runs in **offline mode**: the agents use their rule-based reasoning.
To use the LLM, copy `.env.example` to `.env` and paste your key. The example uses Groq
(`GROQ_API_KEY`, `LLM_MODEL=groq:openai/gpt-oss-120b`). For OpenAI, set `OPENAI_API_KEY` and
`LLM_MODEL=openai:gpt-5.4-mini` instead. Any LangChain `provider:model` string works if the
provider's package is installed.

## How it works

```
SensorReading ─┬─> Environment Agent  ─┐
               │   Weather Agent      ─┼─> Plant Doctor Agent ─> guardrail ─> MQTT payloads
               │   Notification Agent ─┘
               └─> reading history (moisture trend, hours until dry)
```

| Agent | Owner | What it does |
|---|---|---|
| Environment | Dissanayake | Code checks each reading against the plant profile's ideal range, fits the soil-drying trend and computes hours until dry and a **baseline priority**. The LLM turns those facts into a plain-language assessment. |
| Weather | Thashmila | `OpenMeteoWeatherAgent` reads the live forecast for the next 12 h from [Open-Meteo](https://open-meteo.com) (free, no API key) and flags heat or rain. |
| Notification | Thashmila | `ImapNotificationAgent` reads the last 7 days of a Gmail inbox over IMAP and keeps the watering, fertilising, repotting and travel messages. |
| Plant Doctor | Dissanayake | The LLM combines the three reports into a headline, message, actions, priority and reasoning (LangChain structured output). |
| Chat | Dissanayake | Answers the owner's questions on the Next.js dashboard. The LLM picks from four read-only tools (live readings, Plant Doctor report, sensor history, watering log), then answers. See [below](#dashboard-api-and-the-chat-agent). |
| Plant Profile | Dissanayake | Drafts the care profile (ideal ranges, care notes) for a plant the owner names on the dashboard; a checkpoint corrects any impossible range before the owner reviews it. See [Plant profiles](#plant-profiles). |

The three analysis agents run in parallel. If the weather or notification agent fails, the Plant
Doctor still advises from the sensors alone. The offline demo and the tests use `DummyWeatherAgent`
and `DummyNotificationAgent` instead, which run the same summarising code on the scenario's
hardcoded forecast and inbox.

## Weather and email (the external agents)

**Weather.** No setup is needed. The forecast is for `WEATHER_LATITUDE` / `WEATHER_LONGITUDE`
(default: Colombo); change both together with `LOCATION`, which is only the name shown in the
advice. One request is reused for 15 minutes. If Open-Meteo can't be reached, the last forecast is
reused for up to 3 hours, and after that the weather is reported as unavailable.

**Email.** Without `EMAIL_ADDRESS` and `EMAIL_APP_PASSWORD`, the report says email is not connected.
To connect a Gmail account:

1. Turn on 2-Step Verification for the Google account.
2. Create an app password at <https://myaccount.google.com/apppasswords>.
3. Put the address and the 16-letter app password in `.env`. Never use the normal account password.
4. Test it without the ESP32: `python -m greenpulse_ai --live-context --offline`. The
   NOTIFICATIONS line should start with `[email]`.

To try it, send yourself an email such as "Reminder: fertilise the money plant this weekend".

**Privacy.** The mailbox is opened read-only, and messages are fetched with `BODY.PEEK`, so nothing
is marked as read. Only messages that match a plant-care or travel keyword (whole words, so
"waterproof" doesn't count) are passed on, at most five, with the body cut to 300 characters. The
rest of the inbox never reaches the LLM. To limit it further, create a Gmail label (for example
`GreenPulse`), add a filter that applies it to plant reminders, and set `EMAIL_FOLDER=GreenPulse`.
The mailbox is checked at most every 10 minutes.

**Priority levels**, sent to the ESP32 for the RGB LED:

| priority | code | LED | meaning |
|---|---|---|---|
| low | 0 | green | fine, nothing needed in the next 24 h |
| medium | 1 | yellow | act today |
| high | 2 | orange | act within about 2 h |
| critical | 3 | red | act now |

**Safety guardrail:** the LLM may raise the sensor baseline priority, but may lower it by at most one
level. A hallucinated "all fine" cannot turn the LED green while the soil is bone dry.

**Fallbacks:** if there is no API key, or an LLM call fails or times out, that agent falls back to
its rule-based logic. The `source` field records which path ran (`llm`, `rules` or `rules-fallback`).

**Prompt-injection guard:** email content is marked as untrusted data in the Plant Doctor prompt, and
the model is told never to follow instructions found inside it.

**Cost control:** `PlantCareService` stores every reading but runs the LLM pipeline only on:

- the first reading
- every `ANALYSIS_INTERVAL_S`
- a moisture change of at least `MOISTURE_CHANGE_TRIGGER` points
- a change in the sensor baseline priority

## Email alerts and daily summaries

The bridge can email people when the plant needs them. Set `SMTP_HOST` in `.env` (Zoho on your own
domain: `smtppro.zoho.com`; Gmail: `smtp.gmail.com`). Emails are sent from `EMAIL_ADDRESS` with the
same app password the Notification Agent uses. Restart the bridge, then add addresses on the
dashboard's **Email alerts** page.

- **Sign-up code.** A new address gets a 6-digit code and nothing else until the code is entered on
  the page. Codes expire after 15 minutes and allow 5 wrong tries. At most 10 codes go out per hour
  and the list holds 10 addresses.
- **Plant alerts** go out when the Plant Doctor's priority reaches high or critical. Each address
  picks "high and critical" or "critical only". You get one email when a problem starts, another if
  it gets worse (high → critical), and a reminder every 6 hours while it lasts. After it clears, a new
  alert waits at least an hour after the last one, so a reading that flickers around the threshold
  doesn't flood the inbox.
- **Device offline.** A device that sends nothing for 15 minutes gets one email per outage.
- **Daily summary** at `DAILY_SUMMARY_HOUR` (default 8, in `TIMEZONE`). It covers each device's
  readings, the latest advice, the waterings in the last 24 hours and the reminders found in the inbox.

The list is saved to `ALERTS_FILE` (`data/alerts.json`). Only a hash of each pending code is stored.
Alerts are sent from a background thread, so a slow mail server never holds up the analysis.
Every email carries an `X-GreenPulse` header. The Notification Agent skips messages with that header,
so an alert that lands in the same inbox is never read back as a reminder.

## Auto-watering (the water pump)

After each analysis, `WateringPolicy` (`greenpulse_ai/watering.py`) decides whether to send a pump
pulse. The LLM cannot switch the pump on by itself. All of these must hold:

- auto-watering is on (`AUTO_WATERING` in `.env`, or the Node-RED switch, which overrides it)
- the soil sensor itself reads below the plant's ideal range, so a working sensor is required
- the Plant Doctor rates the situation `high` or `critical`
- no watering (auto or manual) in the last `WATER_COOLDOWN_S`, so the last pulse has time to soak in
- fewer than `WATER_MAX_PER_DAY` pulses in 24 h

Each pulse lasts `WATER_PULSE_S` seconds. The ESP32 adds its own hard limits (maximum run time, rest
time, refusing to pump into wet soil), so a bad MQTT message cannot flood the pot. The decision and
its reason go out in `ai/care` under `watering`.

## Plant profiles

Every plant needs different care: 25 % soil moisture is dry for a pothos (35–65 %) but fine for a
snake plant (15–40 %), and 40 % is too wet for an aloe. So every reading is judged against the
profile of the plant that device is watching: its ideal soil-moisture, temperature and humidity
ranges and its care notes.

- **Built-in profiles** (`plant_profiles.py`): pothos, snake plant, peace lily, generic houseplant.
- **Added plants** (dashboard → *Plant profiles* → *Add plant*): the owner types a name, and the
  **Plant Profile Agent** (`agents/profile.py`) drafts the profile with the LLM (structured output,
  `schemas.PlantCareProfile`). Without an LLM it uses a built-in profile with that name, typical
  ranges for the kind of plant ("cactus", "fern"…), or generic ranges, and says which.
- **The checkpoint** (`plant_profiles.checkpoint`) runs on every draft and every save. It keeps each
  range within what the sensors measure and what makes sense indoors (soil 5–95 %, 5–40 °C, humidity
  10–95 %), fixes a swapped range, and widens one that is too narrow to act on. It lists each change,
  and the dashboard shows the list, so a wrong LLM answer is visible and corrected before the owner
  saves it. A save whose ranges would need correcting is refused with the reason.
- **Which plant a device watches** is chosen on the dashboard; devices without a choice use
  `PLANT_PROFILE`. Added plants and the choices are saved in `PLANTS_FILE` (default
  `data/plants.json`, git-ignored), so they survive restarts.

`PlantLibrary.profile_for(device_id)` (`plant_library.py`) feeds the profile to every agent: the
Environment Agent's range checks and baseline priority, the Plant Doctor's prompt, the auto-watering
decision (it acts on the Environment Agent's dry/wet states), the dashboard's live readings, and the
Chat Agent's prompt. When a device's plant changes, or the active plant is edited, the next reading is
re-analysed at once (trigger `plant profile changed`).

## Dashboard API and the Chat Agent

The bridge keeps what the dashboard needs in memory (`device_state.py`): the last 24 hours of
readings, the last Plant Doctor result and the recent pump events. It serves them, and the chat,
over HTTP on `API_HOST:API_PORT` (default `127.0.0.1:8000`; `--no-api` turns it off). The Next.js
server forwards `/api/*` to it, so it stays on localhost. Interactive docs: <http://127.0.0.1:8000/api/docs>.

| Endpoint | What it does |
|---|---|
| `GET /api/devices` | devices heard from, most recent first (always includes `DEVICE_ID`) |
| `GET /api/devices/{id}` | live status: the latest reading checked against the plant's ranges every 10 s, the drying trend, the last advice with its weather and reminders, and watering |
| `GET /api/devices/{id}/history?hours=24` | chart data: 144 averaged points, `null` where there was no reading, plus the waterings |
| `GET /api/devices/{id}/pump/events?hours=24` | the pump activity log (runs, finishes, refusals), newest first |
| `POST /api/devices/{id}/chat` | `{"message": "...", "history": [{"role": "user", "content": "..."}, ...]}` → `{"answer", "source", "tools", "model"}` |
| `POST /api/devices/{id}/pump/water` | one manual pulse of `WATER_PULSE_S`, the same command as Node-RED's *Water now* |
| `PUT /api/devices/{id}/pump/auto` | `{"enabled": true}`: the auto-watering switch, published retained on `pump/auto` so Node-RED shows it too |
| `PUT /api/devices/{id}/plant` | `{"key": "aloe-vera"}`: which plant this device watches |
| `GET /api/plants` | built-in and added profiles, each with the devices watching it |
| `POST /api/plants/suggest` | `{"name": "Aloe vera"}` → the Plant Profile Agent's draft, after the checkpoint (not saved) |
| `POST /api/plants`, `PUT /api/plants/{key}`, `DELETE /api/plants/{key}` | save, change or remove an added profile (built-ins are read-only) |
| `GET /api/alerts` | the email list, the sending rules and the last 25 emails sent |
| `POST /api/alerts/recipients` | `{"email": ...}`: add an address and send it a sign-up code |
| `POST /api/alerts/recipients/{id}/verify`, `.../code` | `{"code": "123456"}` to confirm; `code` sends a new one |
| `PUT /api/alerts/recipients/{id}`, `DELETE ...` | `{"alerts": true, "min_priority": "high", "daily": true}`; remove the address |
| `POST /api/alerts/recipients/{id}/test` | send a test email to a confirmed address |
| `GET /api/auth/me` | `{"account": {...} or null, "registration_open": true}` |
| `POST /api/auth/register` | `{"name", "email", "password"}`: create an account and email it a 6-digit code |
| `POST /api/auth/confirm`, `POST /api/auth/code` | `{"email", "code"}`: confirm the address and sign in; `{"email"}`: send a new code |
| `POST /api/auth/login`, `POST /api/auth/logout` | `{"email", "password"}` to sign in (403 with `"reason": "unconfirmed"` until confirmed); sign out |

Readings, advice and history start empty after a restart; the DynamoDB log is the long-term record.

**Sign-in** (`accounts.py`). Everything except `/api/auth/*` answers 401 without the `gp_session`
cookie that signing in sets. Anyone can create an account on the dashboard's Register page; it works
once its owner enters the 6-digit code emailed to the address (sent with the email-alert settings, so
registration needs `SMTP_HOST`; without it, registration is closed). Codes last 15 minutes and allow 5
tries; a new one can be sent every 60 s, and at most 20 go out per hour in all, so the server can't be
used to email strangers. Accounts and sessions are saved to `USERS_FILE` (`data/users.json`,
git-ignored): passwords as scrypt hashes, codes and sessions as SHA-256 hashes. Sessions last 30 days.
Five wrong passwords in a row lock an account for 5 minutes. Unconfirmed addresses are forgotten after
a day. Every account can do everything; to remove one, delete it from the file and restart the bridge.

**Chat Agent** (`agents/chat.py`). For each question the LLM gets the plant, the location, the local
time (`TIMEZONE`) and four tools:

| Tool | Returns |
|---|---|
| `current_status` | latest readings against the ideal ranges, drying trend, hours until dry, device online |
| `plant_doctor_report` | the last advice and priority, with the weather and email reminders behind it, and the last auto-watering decision |
| `sensor_history(hours)` | first, last, lowest and highest value of each sensor (with times), soil moisture over time, number of waterings |
| `watering_log(hours)` | pump runs and refusals, the auto-watering setting, why the last automatic decision did or didn't water |

It runs at most 4 LLM calls per question; a normal answer takes 2 (look up, then answer). It has
**no tool that acts**: it can't water the plant or flip the switch, and email text is marked as
untrusted, as in the Plant Doctor prompt. Without an LLM, or when a call fails, it answers from
`rule_based_answer()` instead (`source` = `rules` or `rules-fallback`).

**Demo mode** (`demo.py`). `--demo [SOIL]` replaces the MQTT client with a simulated ESP32 that
publishes a reading every 10 s into the bridge's normal message handler and runs a pretend pump with
the firmware's limits (15 s maximum, 60 s rest, refuses above 75 % soil moisture). It also fills in a
simulated past day for the chart. Everything else, from the agents to the watering policy and the API,
is the live code.

## MQTT contract (proposed; Karunarathna to finalise)

| Topic | Direction | Payload |
|---|---|---|
| `greenpulse/<device_id>/sensors` | ESP32 → backend, Node-RED | `{"soil_moisture": 41.5, "temperature": 29.1, "humidity": 58.0}`. `device_id` and `timestamp` are optional; use `null` for a failed sensor read. Extra fields (`soil_raw`, `rssi`) are ignored. |
| `greenpulse/<device_id>/status` | ESP32 → Node-RED | `{"online": true, "ip": ..., "firmware": ...}`, **retained**. Last will: `{"online": false}`. |
| `greenpulse/<device_id>/ai/input` | backend → Node-RED | Reading plus the Environment, Weather and Notification reports (the AI input). |
| `greenpulse/<device_id>/ai/care` | backend → Node-RED | `priority`, `priority_code`, `led`, `headline`, `message`, `actions`, `reasoning`, `source`, `model`, `guardrail_note`, `trigger`, `duration_ms`, `watering`. **Retained**, so the dashboard shows the last advice after a restart. |
| `greenpulse/<device_id>/priority` | backend → ESP32 | `{"priority": "high", "priority_code": 2, "led": "orange"}`. **Retained**, so the ESP32 gets the current priority when it reconnects. |
| `greenpulse/<device_id>/pump/command` | backend or Node-RED → ESP32 | `{"action": "on", "duration_s": 5, "source": "auto", "reason": ...}` or `{"action": "off"}`. **Never retained**: the ESP32 would re-run a stale command on every reconnect. |
| `greenpulse/<device_id>/pump/state` | ESP32 → backend, Node-RED | `{"state": "on" \| "off" \| "rejected", "source": ..., "duration_s" / "ran_s" / "detail": ...}` |
| `greenpulse/<device_id>/pump/auto` | Node-RED or backend → backend | `true` / `false`, **retained**: the auto-watering switch. The backend publishes it when the switch is flipped on the Next.js dashboard. |

Run `python -m greenpulse_ai --json` to see full example payloads.

## Integration points

**Cloud MQTT (Karunarathna).** `greenpulse_ai/bridge.py` is a ready subscriber. For AWS IoT Core, set
`MQTT_HOST`, `MQTT_PORT=8883` and the three certificate paths in `.env`, and allow the topics above
in the IoT policy. To embed the service in your own subscriber instead:

```python
import json
from greenpulse_ai import Settings, Topics, build_messages, build_service, create_chat_model, parse_sensor_payload

settings = Settings.from_env()
service = build_service(settings, create_chat_model(settings))
topics = Topics(settings.topic_prefix)

def on_sensor_message(topic: str, payload: bytes) -> None:
    reading = parse_sensor_payload(payload, device_id=topic.split("/")[1])
    result = service.handle_reading(reading)   # None = no new analysis needed
    if result:
        for out_topic, body in build_messages(result, topics):
            publish(out_topic, json.dumps(body), retain=out_topic in topics.retained(result.device_id))
```

`handle_reading` blocks while the LLM runs (a few seconds). Call it off the MQTT network thread, for
example through a queue or worker thread.

**Weather and Notification agents (Thashmila).** `live_context_agents(settings)` builds the real
agents from `.env`; the bridge passes them as
`build_service(settings, llm, weather_agent=..., notification_agent=...)`. To use another source
(say, a different weather API), write a class with `name` and a `run()` method that returns a
`WeatherReport` or `NotificationReport` (see `greenpulse_ai/schemas.py`) and pass that instead.

**Firmware (Bandara).** `firmware/greenpulse_esp32/` implements the device side of the contract:
sensors, the 16x2 LCD, RGB LED from `priority_code` (0–3) and the pump relay.

**Dashboard (Thashmila).** Import `node-red/greenpulse-flow.json` (needs
`@flowfuse/node-red-dashboard`). The "Weather & reminders" card shows what the two external agents
reported for the last analysis (from `ai/input`).

## Layout

```
greenpulse_ai/
  agents/environment.py    Environment Agent (rules + LLM)
  agents/plant_doctor.py   Plant Doctor Agent, guardrail, rule-based fallback
  agents/weather.py        Weather Agent: Open-Meteo forecast + dummy stand-in
  agents/notification.py   Notification Agent: IMAP mailbox + dummy stand-in
  agents/chat.py           Chat Agent: questions from the dashboard, read-only tools, rule-based fallback
  agents/profile.py        Plant Profile Agent: drafts a plant's care profile from its name
  orchestrator.py          parallel agent pipeline, PlantCareService (history, throttling), live agents
  prompts.py               LangChain prompt templates
  llm.py                   chat model setup (init_chat_model) / offline switch
  schemas.py               Pydantic data contracts, including the LLM output schemas
  plant_profiles.py        built-in plant profiles and the checkpoint for ideal ranges
  plant_library.py         built-in + added plants, which plant each device watches (PLANTS_FILE)
  mqtt_payloads.py         topics, ESP32 payload parsing, outgoing payloads
  watering.py              auto-watering decision (pump safety gates)
  bridge.py                live MQTT bridge: python -m greenpulse_ai.bridge
  device_state.py          what the dashboard shows: recent readings, last result, pump events
  api.py                   dashboard API (FastAPI) for the Next.js dashboard, served by the bridge
  alerts.py                email alerts, offline notices and daily summaries; the sign-up list (ALERTS_FILE)
  accounts.py              dashboard sign-in: accounts confirmed by email code, password hashes, sessions (USERS_FILE)
  email_templates.py       the text and HTML of every email
  mailer.py                SMTP sending (SMTP_HOST)
  demo.py                  simulated ESP32 for --demo
  dummy_data.py            hardcoded scenarios + fake ESP32 stream
  __main__.py              CLI demo
tests/                     pytest suite (fake LLM, MQTT client, weather API and IMAP server; no network)
```
