# Deploying GreenPulse to the cloud (AWS EC2 + AWS IoT Core)

In the final setup, the laptop is no longer needed. The ESP32, the AI backend and Node-RED all
connect to AWS IoT Core, and the backend, Node-RED and the Next.js plant dashboard run on one EC2
instance:

```
ESP32 ──MQTT/TLS──▶ AWS IoT Core ◀──MQTT/TLS── EC2: AI backend (bridge) ──▶ Groq LLM, Open-Meteo, Gmail
                        ▲                          ▲ dashboard API (127.0.0.1:8000, server only)
                        │                          └── EC2: Next.js plant dashboard ◀── your browser (port 3000)
                        └────────MQTT/TLS───── EC2: Node-RED dashboard ◀── your browser (port 1880)
```

**Before you start:** AWS IoT Core must be set up as in [aws-iot.md](aws-iot.md): three Things
(`greenpulse-01`, `greenpulse-backend`, `greenpulse-nodered`), each with its own certificate and
policy, and the data-log rule. You need the backend's and Node-RED's certificate files and the IoT
Core endpoint (AWS IoT console → **Settings** → *Device data endpoint*).

## 1. Launch the EC2 instance

In the EC2 console, choose **Launch instance**:

| Setting | Value |
|---|---|
| Region | The same as AWS IoT Core (e.g. Asia Pacific (Mumbai) `ap-south-1`) |
| AMI | Ubuntu Server 24.04 LTS |
| Instance type | `t3.micro` is enough for the bridge and Node-RED; `t3.small` if it feels slow |
| Key pair | Create one (e.g. `greenpulse`) and keep the downloaded `.pem` file safe |
| Storage | 16 GB gp3 |
| Security group, inbound | SSH (22) from **My IP**; Custom TCP 1880 from **My IP** (Node-RED); Custom TCP 3000 from **My IP** (plant dashboard) |

Leave outbound traffic open (the default). The backend connects out to IoT Core (8883), Groq and
Open-Meteo (443), the mailbox (IMAP 993) and, for email alerts, its SMTP server (465); nothing needs
to connect in except you.

Never open ports 1880 or 3000 to `0.0.0.0/0`: both dashboards can run the pump, and every chat
question costs an LLM call. When your IP changes (different Wi-Fi, a demo room), update the rules
instead. Port 8000 (the dashboard API) needs no rule: it only listens on the server itself.

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
EMAIL_IMAP_HOST=imappro.zoho.com       # only for Zoho; Gmail is the default
SMTP_HOST=smtppro.zoho.com             # optional: email alerts (smtp.gmail.com for Gmail)
DASHBOARD_URL=http://<public-ip>:3000  # optional: the link in the emails
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

## 6. Run the plant dashboard (Next.js)

Node.js is already installed (the Node-RED installer added it). Build the dashboard and run it as a
service:

```bash
cd ~/green-pulse/dashboard
npm ci
npm run build
sudo cp ~/green-pulse/deploy/greenpulse-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now greenpulse-dashboard
systemctl status greenpulse-dashboard        # should say "active (running)"
```

Open `http://<public-ip>:3000`. It reads from the bridge's dashboard API on `127.0.0.1:8000`, so
the bridge must be running too. If `npm run build` is killed on a `t3.micro` (out of memory), add
a swap file once and build again:

```bash
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

The auto-watering switch on this dashboard makes the backend publish `pump/auto`, so the backend's
IoT policy must allow it ([aws-iot.md](aws-iot.md), `GreenPulseBackendPolicy`).

## 7. Final integration test

With the ESP32 on AWS IoT Core (`MQTT_USE_TLS 1` in `config.h`) and powered:

| # | Check | Expected |
|---|---|---|
| 1 | `systemctl status greenpulse-bridge nodered greenpulse-dashboard` | All three `active (running)` |
| 2 | AWS IoT console → **MQTT test client** → subscribe to `greenpulse/#` | A `sensors` message every 10 s, plus `ai/input`, `ai/care` and `priority` after each analysis |
| 3 | `journalctl -u greenpulse-bridge -f` | One line per reading and an analysis line with `llm via groq:...` |
| 4 | Dashboard, top row | Gauges move, **ESP32: Online**, the advice card fills in |
| 5 | **Weather & reminders** card | `live · Open-Meteo` with the current weather for your location |
| 6 | Send yourself "Reminder: fertilise the money plant this weekend" | Listed under *Email reminders* within 10 minutes |
| 7 | ESP32 RGB LED | Same colour as the priority chip on the advice card |
| 8 | **Water now**, then **Auto-watering** with the probe out of the soil | As in [integration.md, section 6](integration.md#6-test-it-end-to-end) |
| 9 | Unplug the ESP32 | Dashboard shows **ESP32: Offline** within about a minute (MQTT last will) |
| 10 | `sudo reboot`, wait 2 minutes, reload the dashboard | Everything comes back by itself; the last advice is still shown (retained) |
| 11 | `http://<public-ip>:3000`, ask "How is my plant doing?" | The headline and lamp match Node-RED's advice card; the chat answers within a few seconds and says what it looked at |
| 12 | Flip auto-watering on the plant dashboard | The Node-RED switch follows within a second, and the bridge stays connected |

Note the results (with screenshots) for the final report.

## Updating and costs

To deploy a new version:

```bash
cd ~/green-pulse && git pull
backend/.venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart greenpulse-bridge
(cd dashboard && npm ci && npm run build) && sudo systemctl restart greenpulse-dashboard
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
| Plant dashboard: "Can't reach the GreenPulse server" | `greenpulse-bridge` not running, or another process holds port 8000 (`sudo ss -ltnp \| grep 8000`) |
| Plant dashboard doesn't load | Port 3000 not allowed from your current IP, or `greenpulse-dashboard` not running (`journalctl -u greenpulse-dashboard`) |
