# Deploying GreenPulse to the cloud (AWS EC2 + AWS IoT Core)

In the final setup, the laptop is no longer needed. The ESP32, the AI backend and Node-RED all
connect to AWS IoT Core, and the backend and Node-RED run on one EC2 instance:

```
ESP32 ──MQTT/TLS──▶ AWS IoT Core ◀──MQTT/TLS── EC2: AI backend (bridge) ──▶ Groq LLM, Open-Meteo, Gmail
                        ▲
                        └────────MQTT/TLS───── EC2: Node-RED dashboard ◀── your browser (port 1880)
```

**Before you start:** AWS IoT Core must be set up as in
[integration.md, section 7](integration.md#7-moving-to-aws-iot-core-final-setup): three Things
(`greenpulse-01`, `greenpulse-backend`, `greenpulse-nodered`), each with its own certificate, and the
policy attached. You need the backend's and Node-RED's certificate files and the IoT Core endpoint
(AWS IoT console → **Settings** → *Device data endpoint*).

## 1. Launch the EC2 instance

In the EC2 console, choose **Launch instance**:

| Setting | Value |
|---|---|
| Region | The same as AWS IoT Core (e.g. Asia Pacific (Mumbai) `ap-south-1`) |
| AMI | Ubuntu Server 24.04 LTS |
| Instance type | `t3.micro` is enough for the bridge and Node-RED; `t3.small` if it feels slow |
| Key pair | Create one (e.g. `greenpulse`) and keep the downloaded `.pem` file safe |
| Storage | 16 GB gp3 |
| Security group, inbound | SSH (22) from **My IP**; Custom TCP 1880 from **My IP** (Node-RED) |

Leave outbound traffic open (the default). The backend connects out to IoT Core (8883), Groq and
Open-Meteo (443) and Gmail (993); nothing needs to connect in except you.

Never open port 1880 to `0.0.0.0/0`. When your IP changes (different Wi-Fi, a demo room), update
the rule instead.

## 2. Install the AI backend

```bash
ssh -i greenpulse.pem ubuntu@<public-ip>

sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/DissanayakeDA/green-pulse.git
cd green-pulse/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p certs
cp .env.example .env
```

If the repository is private, `git clone` asks for a GitHub username and a personal access token
(GitHub → Settings → Developer settings → Personal access tokens), not your password.

From your **laptop**, copy the backend's certificate files to the server:

```powershell
scp -i greenpulse.pem AmazonRootCA1.pem backend-certificate.pem.crt backend-private.pem.key ubuntu@<public-ip>:~/green-pulse/backend/certs/
```

Back on the server, edit `.env` (`nano .env`) and set:

```ini
GROQ_API_KEY=...                       # same as on the laptop
MQTT_HOST=xxxxxxxxxxxxxx-ats.iot.ap-south-1.amazonaws.com
MQTT_PORT=8883
MQTT_CA_FILE=certs/AmazonRootCA1.pem
MQTT_CERT_FILE=certs/backend-certificate.pem.crt
MQTT_KEY_FILE=certs/backend-private.pem.key
MQTT_CLIENT_ID=greenpulse-backend
EMAIL_ADDRESS=...                      # optional, see backend/README.md
EMAIL_APP_PASSWORD=...
```

Then lock the secrets down and run the bridge once in the foreground:

```bash
chmod 600 .env certs/*
.venv/bin/python -m greenpulse_ai.bridge
```

You should see `Connected to xxxxxxxxxxxxxx-ats.iot.ap-south-1.amazonaws.com:8883`. Press Ctrl+C.

## 3. Keep the bridge running (systemd)

```bash
sudo cp ~/green-pulse/deploy/greenpulse-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now greenpulse-bridge
systemctl status greenpulse-bridge           # should say "active (running)"
journalctl -u greenpulse-bridge -f           # live log; Ctrl+C to stop watching
```

The service starts at boot and restarts 10 s after a crash. The service file assumes the user
`ubuntu` and the repo in `/home/ubuntu/green-pulse`; edit it if yours differ.

## 4. Install Node-RED

```bash
bash <(curl -sL https://github.com/node-red/linux-installers/releases/latest/download/install-update-nodered-deb)
```

At the end, the installer runs `node-red admin init`. Answer **Yes** to setting up user security and
create an admin user with full access. Without it, anyone who can reach port 1880 can edit the
flows. Accept the defaults for the other questions.

Install the dashboard and start Node-RED as a service:

```bash
cd ~/.node-red && npm install @flowfuse/node-red-dashboard
sudo systemctl enable --now nodered.service
```

## 5. Import the dashboard and connect it to AWS IoT Core

1. Open `http://<public-ip>:1880` and log in.
2. Menu → **Import** → **select a file to import** → choose `node-red/greenpulse-flow.json` from the
   repo on your laptop → **Import**.
3. Double-click any MQTT node, then the pencil next to **GreenPulse broker**:
   - **Server:** your IoT Core endpoint, **Port:** 8883, **Client ID:** `greenpulse-nodered`
   - Tick **Use TLS**, add a new TLS configuration, and upload (from your laptop) Node-RED's
     certificate, its private key and `AmazonRootCA1.pem` as the CA certificate.
   - **Protocol:** MQTT V3.1.1 or V5 (IoT Core supports both).
4. Click **Update**, **Update**, then **Deploy**. The MQTT nodes should show *connected*.
5. Open the dashboard at `http://<public-ip>:1880/dashboard/greenpulse`.

## 6. Final integration test

With the ESP32 on AWS IoT Core (`MQTT_USE_TLS 1` in `config.h`) and powered:

| # | Check | Expected |
|---|---|---|
| 1 | `systemctl status greenpulse-bridge nodered` | Both `active (running)` |
| 2 | AWS IoT console → **MQTT test client** → subscribe to `greenpulse/#` | A `sensors` message every 10 s, plus `ai/input`, `ai/care` and `priority` after each analysis |
| 3 | `journalctl -u greenpulse-bridge -f` | One line per reading and an analysis line with `llm via groq:...` |
| 4 | Dashboard, top row | Gauges move, **ESP32: Online**, the advice card fills in |
| 5 | **Weather & reminders** card | `live · Open-Meteo` with the current weather for your location |
| 6 | Send yourself "Reminder: fertilise the money plant this weekend" | Listed under *Email reminders* within 10 minutes |
| 7 | ESP32 RGB LED | Same colour as the priority chip on the advice card |
| 8 | **Water now**, then **Auto-watering** with the probe out of the soil | As in [integration.md, section 6](integration.md#6-test-it-end-to-end) |
| 9 | Unplug the ESP32 | Dashboard shows **ESP32: Offline** within about a minute (MQTT last will) |
| 10 | `sudo reboot`, wait 2 minutes, reload the dashboard | Everything comes back by itself; the last advice is still shown (retained) |

Note the results (with screenshots) for the final report.

## Updating and costs

To deploy a new version:

```bash
cd ~/green-pulse && git pull
backend/.venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart greenpulse-bridge
```

If the flow changed, import it again in Node-RED (choose **Replace** for the existing nodes) and
set up the broker node again.

The instance bills while it runs. **Stop** it (don't terminate it) when you're not using it. After a
stop and start it gets a new public IP, so use the new address for SSH and the dashboard, and update
the **My IP** rules if your own IP changed. The services start by themselves.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bridge exits with an SSL or `FileNotFoundError` error | A certificate path in `.env` is wrong; the paths are relative to `backend/` |
| Bridge log: `MQTT connection refused` | Certificate not **Active** in IoT Core, or no policy attached to the backend's certificate |
| Bridge log: `Disconnected from the broker` over and over | Another client uses the same client ID (`greenpulse-backend`), e.g. the bridge still running on a laptop |
| Dashboard doesn't load | Port 1880 not allowed from your current IP, or `nodered` service not running |
| Node-RED MQTT nodes stay *connecting* | TLS configuration missing a file, or the policy doesn't allow `greenpulse-nodered` |
| Retained messages missing after a restart | The policy lacks `iot:RetainPublish` |
