# Connecting the ESP32, the AI backend and Node-RED

Nothing talks to anything directly. The ESP32, the AI backend and Node-RED each connect to the same
MQTT broker and exchange messages through topics:

```
                   greenpulse/<id>/sensors, status, pump/state
   ┌─────────┐  ─────────────────────────────────────────────▶  ┌─────────────┐  ──▶  ┌────────────────────┐
   │  ESP32  │                                                  │ MQTT broker │       │ AI backend (bridge)│
   │ sensors │  ◀─────────────────────────────────────────────  │ Mosquitto / │  ◀──  │ 4 agents + pump    │
   │ LED pump│         greenpulse/<id>/priority, pump/command   │ AWS IoT Core│       │ decision           │
   └─────────┘                                                  └─────────────┘       └────────────────────┘
                                                                  ▲         │
                                          pump/command, pump/auto │         │ everything (greenpulse/#)
                                                                  │         ▼
                                                              ┌────────────────────┐
                                                              │ Node-RED dashboard │
                                                              └────────────────────┘
```

| Part | Where | Run |
|---|---|---|
| Firmware | `firmware/greenpulse_esp32/` | Arduino IDE → Upload |
| AI backend | `backend/` | `python -m greenpulse_ai.bridge` |
| Dashboard | `node-red/greenpulse-flow.json` | import into Node-RED |

The topic list and payloads are in [backend/README.md](../backend/README.md#mqtt-contract-proposed-karunarathna-to-finalise).

Set up in this order: broker, then firmware, then backend, then dashboard. Develop against a local
Mosquitto broker first, then switch to AWS IoT Core (section 7), which only changes connection settings.

## 1. Wiring

These are the default pins; all of them can be changed in `config.h`.

| Part | Part pin | ESP32 pin |
|---|---|---|
| Capacitive soil-moisture sensor | VCC / GND / AOUT | **3V3** / GND / **GPIO 34** |
| DHT22 | VCC / DATA / GND | 3V3 / **GPIO 4** / GND (bare 4-pin sensor: 10 kΩ from DATA to 3V3) |
| 16×2 LCD with I2C backpack (address 0x27) | VCC / GND / SDA / SCL | VIN (5 V) / GND / **GPIO 21** / **GPIO 22** |
| RGB LED, common cathode | R / G / B / common | **GPIO 18 / 19 / 5**, each through 220–330 Ω / GND |
| Relay module for the pump | VCC / GND / IN | VIN (5 V from USB) / GND / **GPIO 23** |

- Power the soil sensor from **3V3**, not 5 V. On 5 V its output can go above 3.3 V and damage the pin.
- Analog sensors must use GPIO 32–39 (ADC1). ADC2 pins return nothing while Wi-Fi is on.
- For a common-anode LED (longest leg to 3V3), set `RGB_COMMON_ANODE 1`.
- Using an SSD1306 OLED instead of the LCD? Set `DISPLAY_TYPE 2` and `DISPLAY_ADDRESS 0x3C`, and power it from 3V3.
- If the LCD stays blank, try `DISPLAY_ADDRESS 0x3F`, or turn the contrast screw on the backpack.

### Water pump

The relay is a switch in the pump's own power circuit:

```
 pump supply +5V ───────────── relay COM
                               relay NO ───────── pump (+)
 pump supply GND ──────────────────────────────── pump (−)
```

- **Give the pump its own supply** (a 5 V adapter or USB power bank). Powering it from the ESP32 3V3
  pin will not work, and its start-up surge on the USB 5 V rail resets the ESP32.
- Use the relay's **NO** (normally open) terminal, so the pump stays off whenever the relay is off.
- Most relay modules switch on when IN is LOW (`PUMP_ACTIVE_LOW 1`). **If the pump runs at boot,
  flip that setting.** If the relay clicks unreliably from 3.3 V logic, use a 3.3 V-compatible module.
- Using a MOSFET instead of a relay: use a logic-level N-MOSFET (e.g. IRLZ44N or AO3400), put a
  diode (1N4007 or 1N5819) across the pump, join the pump-supply GND to the ESP32 GND, and set
  `PUMP_ACTIVE_LOW 0`.
- Keep the water tank **lower than the pot**. Otherwise the tube keeps siphoning water after the pump stops.
- Do not let the pump run dry, and keep the electronics away from the water.

Pump safety works in two layers:

| Layer | Limit |
|---|---|
| ESP32 (always on) | at most `PUMP_MAX_RUN_S` (15 s) per run, `PUMP_MIN_REST_S` (60 s) between runs, refuses when soil ≥ `PUMP_WET_CUTOFF` (75 %), and a hardware timer switches the pump off even if the program stalls |
| Backend (auto-watering) | pumps only if the soil sensor reads dry **and** the Plant Doctor says high/critical; one 5 s pulse, then 30 min to soak in; at most 6 pulses a day |

## 2. MQTT broker (development: Mosquitto on the laptop)

1. Install Mosquitto for Windows from <https://mosquitto.org/download/>. It installs as a Windows service.
2. Mosquitto 2.x only accepts connections from the laptop itself by default. To let the ESP32 in, add
   these lines to the end of `C:\Program Files\mosquitto\mosquitto.conf`:
   ```
   listener 1883 0.0.0.0
   allow_anonymous true
   ```
   (Anonymous access is fine on your own Wi-Fi for development. The final setup uses AWS IoT Core
   with certificates.)
3. In an **administrator** PowerShell, restart the broker and open the firewall:
   ```powershell
   Restart-Service mosquitto
   New-NetFirewallRule -DisplayName "Mosquitto 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow
   ```
4. Find the laptop's IP with `ipconfig` (Wi-Fi adapter → IPv4 Address). The ESP32 uses this address.
   The ESP32 and the laptop must be on the same 2.4 GHz network. University and guest Wi-Fi often
   block device-to-device traffic, so use a phone hotspot if the ESP32 cannot connect.
5. Watch all GreenPulse traffic while you test:
   ```powershell
   & "C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -t "greenpulse/#" -v
   ```

## 3. ESP32 firmware

1. Arduino IDE: install the **esp32 by Espressif Systems** board package (3.x) and select
   **ESP32 Dev Module**.
2. Library Manager: install **PubSubClient** (Nick O'Leary), **ArduinoJson** (Benoit Blanchon, v7),
   **DHT sensor library**, **Adafruit Unified Sensor** and **LiquidCrystal I2C** (Frank de Brabander).
   It warns that it is made for AVR, but it works on the ESP32. For an OLED instead, install
   **Adafruit SSD1306** and **Adafruit GFX Library**.
3. Open `firmware/greenpulse_esp32/greenpulse_esp32.ino`. Copy `config.example.h` to `config.h` in the
   same folder and fill in your Wi-Fi details, `MQTT_HOST` (the laptop IP) and any pins you changed.
   `config.h` is git-ignored.
4. Upload and open the Serial Monitor at 115200 baud. You should see:
   ```
   Wi-Fi: connected, IP 192.168.1.23
   MQTT: connecting to 192.168.1.10:1883 as greenpulse-01 ... connected
   soil raw 2310 -> 41.5 %, 29.1 C, 58.0 % RH
   -> greenpulse/greenpulse-01/sensors {"soil_moisture":41.5,...}
   ```
5. **Calibrate the soil sensor.** Note the `soil raw` value with the probe in dry air
   (`SOIL_DRY_RAW`), then in a glass of water up to the line (`SOIL_WET_RAW`). Put both in `config.h`
   and upload again.

The RGB LED is dim blue until the backend sends its first priority. After that it is green (low),
yellow (medium), orange (high) or red (critical).

## 4. AI backend

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # adds paho-mqtt
python -m greenpulse_ai.bridge           # add --offline to skip LLM calls while testing
```

`MQTT_HOST=localhost` in `.env` works because Mosquitto runs on the same laptop. The Weather Agent
needs no setup. To let the Notification Agent read your Gmail reminders, set `EMAIL_ADDRESS` and
`EMAIL_APP_PASSWORD` (an app password, see
[backend/README.md](../backend/README.md#weather-and-email-the-external-agents)). You should see:

```
GreenPulse bridge | broker localhost:1883 | plant: Pothos (Money Plant) | mode: LLM groq:openai/gpt-oss-120b | ...
Weather: Open-Meteo for Colombo, LK (6.9271, 79.8612) | email: you@gmail.com (INBOX)
Listening on greenpulse/+/sensors. Ctrl+C to stop.

16:41:14 INFO    Connected to localhost:1883
16:41:16 INFO    greenpulse-01  soil 29%  29.4°C  61% RH
16:41:16 INFO    greenpulse-01  -> [first reading] HIGH Water within 2 h | pump: Auto-watering is off | llm via groq:openai/gpt-oss-120b
```

## 5. Node-RED dashboard

```powershell
npm install -g --unsafe-perm node-red
node-red
```

1. Open <http://localhost:1880>. Go to Menu → **Manage palette** → Install, and install
   **@flowfuse/node-red-dashboard**.
2. Go to Menu → **Import**, select `node-red/greenpulse-flow.json`, then click **Deploy**.
3. Open the dashboard at <http://localhost:1880/dashboard/greenpulse>.

It shows live gauges, a 24-hour chart, the Plant Doctor's advice, the weather and email reminders
the Plant Doctor was given, the pump controls and the latest message on every GreenPulse topic, with
timestamps (the AI input and output payloads). The device ID
(`greenpulse-01`) and the manual watering time (5 s) are environment variables on the flow tab: in
the editor, double-click the tab to change them.

## 6. Test it end to end

1. The Serial Monitor shows `MQTT ... connected`, and the dashboard shows **ESP32: Online**.
2. The bridge logs a reading every 10 s and a Plant Doctor analysis. The LED changes colour and the
   advice card fills in. The **Weather & reminders** card shows `live · Open-Meteo` with the current
   weather for your location.
3. **Email reminders:** send yourself an email such as "Reminder: fertilise the money plant this
   weekend". The mailbox is checked at most every 10 minutes, so within 10 minutes (sooner if you
   restart the bridge) the card lists it under *Email reminders*, and the Plant Doctor takes it into
   account in its next advice.
4. **Manual pump:** put the pump outlet back into the tank, then press **Water now**. The pump runs
   for 5 s and the Pump line shows `Off · ran 5.0 s, done (manual)`.
5. **Auto-watering:** pull the soil probe out of the soil so it reads dry, then turn on
   **Auto-watering (AI)**. The next reading is analysed at once, and the pump pulses within about
   10 s. The advice card explains the decision. With the probe back in wet soil, the pump stays off.

For a demo, set `WATER_COOLDOWN_S=60` in `.env` so you can show several pulses in a row.

## 7. Moving to AWS IoT Core (final setup)

Each client needs its own certificate and a **unique client ID**. Two connections with the same ID
keep disconnecting each other.

| Client | Client ID / Thing | Configure in |
|---|---|---|
| ESP32 | `greenpulse-01` | `config.h`: `MQTT_USE_TLS 1`, endpoint, and paste the 3 PEMs |
| AI backend | `greenpulse-backend` | `.env`: `MQTT_HOST`, `MQTT_PORT=8883`, `MQTT_CA_FILE`, `MQTT_CERT_FILE`, `MQTT_KEY_FILE` (put the files in `backend/certs/`, which is git-ignored) |
| Node-RED | `greenpulse-nodered` | broker node: port 8883, **Use TLS** with the cert, key and CA |

Attach a policy like this to all three certificates, with your region and account ID. Without
`iot:RetainPublish`, the retained messages (priority, advice, status, auto switch) are rejected.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "iot:Connect",
      "Resource": "arn:aws:iot:REGION:ACCOUNT_ID:client/greenpulse-*" },
    { "Effect": "Allow", "Action": ["iot:Publish", "iot:RetainPublish", "iot:Receive"],
      "Resource": "arn:aws:iot:REGION:ACCOUNT_ID:topic/greenpulse/*" },
    { "Effect": "Allow", "Action": "iot:Subscribe",
      "Resource": "arn:aws:iot:REGION:ACCOUNT_ID:topicfilter/greenpulse/*" }
  ]
}
```

The Node-RED flow already subscribes with QoS 1. AWS IoT Core does not support QoS 2, which is
Node-RED's default.

To run the backend and Node-RED on an EC2 server instead of the laptop, see
[deployment.md](deployment.md).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Serial: `MQTT offline (-2)` | Can't reach the broker: wrong `MQTT_HOST`, firewall, the `listener 1883 0.0.0.0` line is missing, or the Wi-Fi blocks devices from reaching each other |
| Serial: `-2` / `-4` on AWS | Wrong endpoint, certificate not activated, or policy not attached |
| Soil shows `--` | Raw value below 100 or above 4000: loose wire, or the sensor is not on an ADC1 pin |
| Temp/humidity show `--` | DHT wiring, missing pull-up, or wrong `DHT_TYPE` |
| ESP32 resets when the pump starts | The pump shares the ESP32's power; give it its own supply |
| Pump runs at boot or never | Flip `PUMP_ACTIVE_LOW` |
| Pump line says `Refused: ...` | An ESP32 safety limit applied; the reason is shown |
| Advice card says "Waiting…" | The bridge isn't running or can't reach the broker |
| Weather shows "unavailable" | The backend has no internet access, or `WEATHER_LATITUDE` / `WEATHER_LONGITUDE` is not a number |
| Bridge log: `AUTHENTICATIONFAILED` | `EMAIL_APP_PASSWORD` is wrong or revoked, or it is the normal account password; create a new app password |
| Bridge log: `Mailbox folder ... not found` | `EMAIL_FOLDER` doesn't match a Gmail label exactly (labels are case-sensitive) |
| Email reminder not listed | It is older than 7 days, has no plant-care or travel keyword, or the 10-minute mailbox cache hasn't expired yet |
| MQTT nodes show "disconnected" in Node-RED | Wrong broker settings in the "GreenPulse broker" node |
