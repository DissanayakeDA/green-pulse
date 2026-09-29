# GreenPulse Agentic AI Core

Component 1 of 4 (Dissanayake D A, IT23306622): LLM integration, the Environment and Plant Doctor
agents, agent orchestration, prompts and final care-tip generation.

The ESP32 and the AWS IoT Core link are not built yet, so this component runs on **hardcoded dummy
data** (`greenpulse_ai/dummy_data.py`): seven scenarios of sensor readings, weather and inbox
messages, plus a fake ESP32 that streams readings over a simulated day. The same code will take real
readings from MQTT later without changes to the agents.

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
python -m pytest                               # 50 tests, no API key needed
```

With no API key everything runs in **offline mode**: the agents use their rule-based reasoning.
To use the LLM, copy `.env.example` to `.env` and set `OPENAI_API_KEY`. The model is set by
`LLM_MODEL` (default `openai:gpt-5.4-mini`). Any LangChain `provider:model` string works if the
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
| Weather | Thashmila (stand-in here) | `DummyWeatherAgent` summarises a hardcoded forecast and flags heat or rain. |
| Notification | Thashmila (stand-in here) | `DummyNotificationAgent` filters a hardcoded inbox for watering, fertilising, repotting or travel messages. |
| Plant Doctor | Dissanayake | The LLM combines the three reports into a headline, message, actions, priority and reasoning (LangChain structured output). |

The three analysis agents run in parallel. If the weather or notification agent fails, the Plant
Doctor still advises from the sensors alone.

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

## MQTT contract (proposed; Karunarathna to finalise)

| Topic | Direction | Payload |
|---|---|---|
| `greenpulse/<device_id>/sensors` | ESP32 → backend | `{"soil_moisture": 41.5, "temperature": 29.1, "humidity": 58.0}`. `device_id` and `timestamp` are optional; use `null` for a failed sensor read. |
| `greenpulse/<device_id>/ai/input` | backend → Node-RED | Reading plus the Environment, Weather and Notification reports (the AI input). |
| `greenpulse/<device_id>/ai/care` | backend → Node-RED | `priority`, `priority_code`, `led`, `headline`, `message`, `actions`, `reasoning`, `source`, `model`, `guardrail_note`, `trigger`, `duration_ms` |
| `greenpulse/<device_id>/priority` | backend → ESP32 | `{"priority": "high", "priority_code": 2, "led": "orange"}`. Publish it **retained**, so the ESP32 gets the current priority when it reconnects. |

Run `python -m greenpulse_ai --json` to see full example payloads.

## Integration points

**Cloud MQTT (Karunarathna).** Call the service from your subscriber and publish what comes back:

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
            publish(out_topic, json.dumps(body), retain=out_topic.endswith("/priority"))
```

`handle_reading` blocks while the LLM runs (a few seconds). Call it off the MQTT network thread, for
example through a queue or worker thread.

**Weather and Notification agents (Thashmila).** Write a class with `name` and a `run()` method that
returns a `WeatherReport` or `NotificationReport` (see `greenpulse_ai/schemas.py`). Pass it as
`build_service(settings, llm, weather_agent=..., notification_agent=...)`. Nothing else changes.

**Firmware (Bandara).** Subscribe to `greenpulse/<device_id>/priority` and map `priority_code`
(0–3) to the LED colour. Publish soil moisture as a calibrated 0–100 %.

## Layout

```
greenpulse_ai/
  agents/environment.py    Environment Agent (rules + LLM)
  agents/plant_doctor.py   Plant Doctor Agent, guardrail, rule-based fallback
  agents/weather.py        Weather Agent interface + dummy stand-in
  agents/notification.py   Notification Agent interface + dummy stand-in
  orchestrator.py          parallel agent pipeline + PlantCareService (history, throttling)
  prompts.py               LangChain prompt templates
  llm.py                   chat model setup (init_chat_model) / offline switch
  schemas.py               Pydantic data contracts, including the LLM output schemas
  plant_profiles.py        ideal ranges per plant type
  mqtt_payloads.py         topics, ESP32 payload parsing, outgoing payloads
  dummy_data.py            hardcoded scenarios + fake ESP32 stream
  __main__.py              CLI demo
tests/                     pytest suite (uses a fake LLM, no network)
```
