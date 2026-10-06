# Setting up AWS IoT Core and the data log (console guide)

Cloud MQTT component (Karunarathna K M D K): AWS IoT Core as the MQTT broker, a certificate and a
least-privilege policy for each client, and an IoT rule that logs the GreenPulse traffic to DynamoDB.
Everything is set up by hand in the AWS console, step by step.

```
ESP32  greenpulse-01      ─┐                   ┌─▶ AI backend  greenpulse-backend
                           ├─ MQTT over TLS ──▶ AWS IoT Core
Node-RED  greenpulse-nodered ─┘   (port 8883)    └─▶ rule greenpulse_log ──▶ DynamoDB table GreenPulseLog
```

The topics are the ones in [backend/README.md](../backend/README.md#mqtt-contract-proposed-karunarathna-to-finalise).
Do this once, in the order below. It takes about an hour. Get each client working on the local
Mosquitto broker first ([integration.md](integration.md)); moving to AWS then only changes
connection settings.

## Cost on free-tier credits

Everything here runs on AWS free-tier credits. At the default reading every 10 s, the estimate is:

| Service | Usage per month | Approx. cost |
|---|---|---|
| IoT Core messages | about 1 million (each reading is published once and delivered to the backend and Node-RED) | about $1 |
| IoT Core connections | 3 clients connected all the time | under $0.05 |
| IoT rule | about 260,000 rule runs and DynamoDB writes | about $0.10 |
| DynamoDB | on-demand, about 260,000 writes, well under 1 GB | about $0.40 (storage stays inside the free 25 GB) |
| CloudWatch Logs | errors only | about $0 |
| EC2 `t3.micro` for the backend and Node-RED ([deployment.md](deployment.md)) | running all the time | about $8, plus about $3.60 for its public IPv4 address |

So the IoT part costs about $1–2 a month; the EC2 server is the main cost, and only while it runs.
Prices change; check them in the [AWS Pricing Calculator](https://calculator.aws/) if in doubt.
To cut the IoT cost to a third, set `SENSOR_INTERVAL_MS 30000` in the ESP32's `config.h`; the
backend only re-analyses every 5 minutes anyway.

## 0. Before you start

1. Sign in to the [AWS console](https://console.aws.amazon.com/).
2. **Region:** top right, choose **Asia Pacific (Mumbai) ap-south-1**, the closest region to Sri Lanka.
   Use this region for every step. Things, rules and tables in another region are invisible here.
3. **Account ID:** click your account name (top right) and copy the 12-digit **Account ID**. The
   policies below need it.
4. Make a private folder for the certificate files, **outside the repository**, for example
   `Documents\greenpulse-aws\` with the subfolders `esp32`, `backend` and `nodered`. Never commit
   these files or send them to anyone.
5. **Check your credits:** search for **Billing and Cost Management** → **Credits** to see what
   you have left.

## 1. Set a budget alert

So that a mistake can never go unnoticed:

1. Search for **Budgets** → **Create budget**.
2. Choose **Use a template (simplified)** → **Monthly cost budget**.
3. Budget name `GreenPulse`, amount **10** (USD), your email address → **Create budget**.

AWS emails you when the month's cost reaches 85 % and 100 % of $10, or is forecast to.

## 2. Create the three IoT policies

A policy says what a certificate may do. Each client gets only the topics it actually uses.
AWS IoT disconnects a client straight away if it publishes or subscribes outside its policy.

For each of the three policies below:

1. Search for **IoT Core**. In the left menu, choose **Security** → **Policies** → **Create policy**.
2. Enter the **Policy name**.
3. Under **Policy document**, click **JSON**, delete what is there and paste the policy.
4. Replace every `ACCOUNT_ID` with your 12-digit account ID (if you chose another region, also
   replace `ap-south-1`). Then click **Create**.

**`GreenPulseDevicePolicy`** (the ESP32). `${iot:Connection.Thing.ThingName}` is filled in by AWS
with the Thing name, so a device can only use its own topics. This is why `DEVICE_ID` in
`config.h` must equal the Thing name. `status` needs `iot:RetainPublish` because both the online
message and the last will (`{"online": false}`) are retained.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:ap-south-1:ACCOUNT_ID:client/${iot:Connection.Thing.ThingName}",
      "Condition": { "Bool": { "iot:Connection.Thing.IsAttached": "true" } }
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/${iot:Connection.Thing.ThingName}/sensors",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/${iot:Connection.Thing.ThingName}/status",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/${iot:Connection.Thing.ThingName}/pump/state"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:RetainPublish",
      "Resource": "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/${iot:Connection.Thing.ThingName}/status"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Subscribe",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/${iot:Connection.Thing.ThingName}/priority",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/${iot:Connection.Thing.ThingName}/pump/command"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:Receive",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/${iot:Connection.Thing.ThingName}/priority",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/${iot:Connection.Thing.ThingName}/pump/command"
      ]
    }
  ]
}
```

**`GreenPulseBackendPolicy`** (the AI backend). It reads every device's readings, pump state and
auto switch, and publishes the advice, the LED priority and pump commands. In the `topic/`
resources, `*` stands for any device ID. The `topicfilter/` resources contain a literal `+`
instead: AWS compares a subscription's topic filter with the policy as text, and a `*` in the
policy does not match the `+` in `greenpulse/+/sensors`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:ap-south-1:ACCOUNT_ID:client/greenpulse-backend"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Subscribe",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/+/sensors",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/+/pump/state",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/+/pump/auto"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:Receive",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/sensors",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/pump/state",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/pump/auto"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/ai/input",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/ai/care",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/priority",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/pump/command"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:RetainPublish",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/ai/care",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/priority"
      ]
    }
  ]
}
```

**`GreenPulseDashboardPolicy`** (Node-RED). It reads everything under `greenpulse/` (the flow
subscribes to `greenpulse/#` and to filters like `greenpulse/+/sensors`) and may only send pump
commands and the auto-watering switch (retained).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:ap-south-1:ACCOUNT_ID:client/greenpulse-nodered"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Subscribe",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/#",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topicfilter/greenpulse/+/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:Receive",
      "Resource": "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": [
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/pump/command",
        "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/pump/auto"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "iot:RetainPublish",
      "Resource": "arn:aws:iot:ap-south-1:ACCOUNT_ID:topic/greenpulse/*/pump/auto"
    }
  ]
}
```

## 3. Create the three Things and their certificates

Each client gets its own Thing and certificate. Do this three times:

| Thing name (= MQTT client ID) | Policy to attach | Save the files in |
|---|---|---|
| `greenpulse-01` | `GreenPulseDevicePolicy` | `greenpulse-aws\esp32` |
| `greenpulse-backend` | `GreenPulseBackendPolicy` | `greenpulse-aws\backend` |
| `greenpulse-nodered` | `GreenPulseDashboardPolicy` | `greenpulse-aws\nodered` |

1. IoT Core left menu: **Manage** → **All devices** → **Things** → **Create things**.
2. **Create single thing** → **Next**.
3. **Thing name:** from the table. Leave the other settings; under **Device Shadow** keep
   **No shadow**. **Next**.
4. **Auto-generate a new certificate (recommended)** → **Next**.
5. Tick the policy from the table → **Create thing**.
6. The **Download certificates and keys** window opens. **This is the only time you can download
   the private key.** Download:
   - **Device certificate** (`…-certificate.pem.crt`)
   - **Private key file** (`…-private.pem.key`)
   - **Amazon Root CA 1** (`AmazonRootCA1.pem`; the same file for all three, so once is enough)

   The public key file is not needed. Click **Done**.

If you closed the window before downloading the private key, delete the certificate
(**Security** → **Certificates** → select it → **Actions** → **Deactivate**, then **Delete**) and
create a new one for the Thing (Thing → **Certificates** → **Create certificate**, then attach the
policy to it).

## 4. Copy the endpoint

IoT Core left menu: **Settings** → copy the **Device data endpoint**. It looks like
`a1b2c3d4e5f6g7-ats.iot.ap-south-1.amazonaws.com`. All three clients connect to this address on
port 8883.

If you can't find it, open **CloudShell** (the `>_` icon in the top bar) and run
`aws iot describe-endpoint --endpoint-type iot:Data-ATS`.

## 5. Turn on IoT Core logging (for troubleshooting)

Without this, a client that breaks its policy is just disconnected, with no reason given.

1. IoT Core left menu: **Settings** → **Logs** → **Manage logs**.
2. **Log role:** **Create new role**, name `GreenPulseIoTLoggingRole`.
3. **Log level:** **Error** → **Update**.

The errors then appear in **CloudWatch** → **Log groups** → `AWSIotLogsV2`. A denied publish or
subscribe shows up as `AUTHORIZATION_FAILURE` together with the client ID and topic.

## 6. Create the DynamoDB table for the data log

One table holds every logged message. The partition key is the full topic and the sort key is the
time AWS received the message, so "all readings from greenpulse-01, newest first" is one query.

1. Search for **DynamoDB** → **Tables** → **Create table**.
2. **Table name:** `GreenPulseLog`
3. **Partition key:** `topic`, type **String**.
4. **Sort key:** `ts`, type **Number**.
5. **Table settings:** **Default settings**. The capacity mode is then **On-demand**: you pay per
   write (about $0.40 a month at one reading every 10 s) and there are no capacity units to set.
6. **Create table**. Wait until the status is **Active**.

The console's *Item count* is refreshed only every few hours; **Get live item count** shows the
current number.

## 7. Create a log group for rule errors

If the rule can't write to the table (a wrong key name, say), the error goes here instead of
disappearing.

1. Search for **CloudWatch** → **Logs** → **Log groups** → **Create log group**.
2. **Log group name:** `/greenpulse/iot-rule-errors`, **Retention setting:** **1 week** →
   **Create**.

## 8. Create the IoT rule that logs the data

1. IoT Core left menu: **Manage** → **Message routing** → **Rules** → **Create rule**.
2. **Rule name:** `greenpulse_log` (letters, digits and underscores only).
   **Description:** `Log GreenPulse readings and events to DynamoDB` → **Next**.
3. **SQL version:** `2016-03-23`. **SQL statement:**

   ```sql
   SELECT *, topic() AS topic, topic(2) AS device_id, timestamp() AS ts
   FROM 'greenpulse/#'
   WHERE topic(3) = 'sensors' OR topic(3) = 'status'
      OR topic(4) = 'care' OR topic(4) = 'state' OR topic(4) = 'command'
   ```

   **Next**.
4. **Rule actions** → **Action 1:** choose **DynamoDBv2** (*Split message into multiple columns of
   a DynamoDB table*).
   - **Table name:** `GreenPulseLog`
   - **IAM role:** **Create new role**, name `GreenPulseIoTDynamoRole` → **Create**. The console
     gives this role permission to write to the table and nothing else.
5. **Error action** → **Add error action** → **CloudWatch logs**.
   - **Log group name:** `/greenpulse/iot-rule-errors`
   - **IAM role:** **Create new role**, name `GreenPulseIoTRuleErrorRole`
6. **Next** → **Create**.

What the rule logs, and why:

| Topic | Logged | Why |
|---|---|---|
| `greenpulse/<id>/sensors` | yes | the readings: soil moisture, temperature, humidity, raw value, Wi-Fi signal |
| `greenpulse/<id>/status` | yes | online/offline history, including the last will when the ESP32 drops off |
| `greenpulse/<id>/ai/care` | yes | every piece of Plant Doctor advice with its priority and the watering decision |
| `greenpulse/<id>/pump/command` | yes | who asked for water (AI or dashboard) and why |
| `greenpulse/<id>/pump/state` | yes | what the pump actually did, including refusals by the ESP32 safety limits |
| `greenpulse/<id>/ai/input` | no | it contains text from the user's emails (Notification Agent); kept out of the database for privacy |
| `greenpulse/<id>/priority` | no | a copy of the priority already in `ai/care` |
| `greenpulse/<id>/pump/auto` | no | just `true`/`false`, not a JSON object |

Each item holds the message's own fields plus three added by the rule:

| Attribute | Example | Meaning |
|---|---|---|
| `topic` (partition key) | `greenpulse/greenpulse-01/sensors` | the topic the message arrived on |
| `ts` (sort key) | `1759567215123` | when AWS IoT received it, in milliseconds since 1 Jan 1970 (UTC), so the ESP32 needs no clock |
| `device_id` | `greenpulse-01` | second level of the topic |

## 9. Test it with the MQTT test client

The test client uses your console login, not the policies, so it works before any device is
connected.

1. IoT Core left menu: **Test** → **MQTT test client**.
2. **Subscribe to a topic** tab: topic filter `greenpulse/#` → **Subscribe**.
3. **Publish to a topic** tab: topic `greenpulse/test-device/sensors`, payload:

   ```json
   {"soil_moisture": 41.5, "temperature": 29.1, "humidity": 58.0}
   ```

   **Publish**. The message appears under the subscription.
4. DynamoDB → **Explore items** → `GreenPulseLog`. There is now an item with
   `topic = greenpulse/test-device/sensors`, a `ts`, `device_id = test-device` and the three
   readings.
5. Publish `{"online": true}` to `greenpulse/test-device/status` → a second item appears.
6. Publish anything to `greenpulse/test-device/ai/input` → **no** new item (not logged).

If no item appears, look in CloudWatch → `/greenpulse/iot-rule-errors`.

Once the real ESP32 is connected, **don't publish to `greenpulse/greenpulse-01/pump/command`
from the test client unless the pump outlet is in the tank**: the pump really runs.

## 10. Connect the AI backend

On the laptop first; the same settings go on the EC2 server later ([deployment.md](deployment.md)).

1. Copy the three files from `greenpulse-aws\backend` into the repo's `backend\certs\` folder
   (git-ignored) and rename them:

   | Downloaded file | Rename to |
   |---|---|
   | `AmazonRootCA1.pem` | `AmazonRootCA1.pem` |
   | `…-certificate.pem.crt` | `backend-certificate.pem.crt` |
   | `…-private.pem.key` | `backend-private.pem.key` |

2. In `backend\.env`, replace the Mosquitto lines with:

   ```ini
   MQTT_HOST=a1b2c3d4e5f6g7-ats.iot.ap-south-1.amazonaws.com
   MQTT_PORT=8883
   MQTT_CA_FILE=certs/AmazonRootCA1.pem
   MQTT_CERT_FILE=certs/backend-certificate.pem.crt
   MQTT_KEY_FILE=certs/backend-private.pem.key
   MQTT_CLIENT_ID=greenpulse-backend
   ```

3. Start it from the `backend` folder (the paths are relative to it):

   ```powershell
   cd backend
   .venv\Scripts\Activate.ps1
   python -m greenpulse_ai.bridge --offline
   ```

   The first line ends with `broker a1b2…amazonaws.com:8883 (TLS)`, followed by
   `Connected to a1b2…amazonaws.com:8883`.
4. In the MQTT test client, publish the reading from step 9 to
   `greenpulse/greenpulse-01/sensors`. The bridge logs it and, a moment later, the test client shows
   `greenpulse/greenpulse-01/ai/input`, `ai/care` and `priority`. This proves the backend's policy
   lets it both receive and publish.

Only one `greenpulse-backend` may be connected at a time. If the bridge also runs on EC2, two
connections with the same client ID keep disconnecting each other.

## 11. Connect the ESP32

1. Open `firmware/greenpulse_esp32/config.h` (git-ignored) and set:

   ```cpp
   #define DEVICE_ID    "greenpulse-01"   // must equal the Thing name
   #define MQTT_USE_TLS 1
   ```

   and, in the `#else` block, `MQTT_HOST` to your endpoint (port stays 8883).
2. Open each file from `greenpulse-aws\esp32` in Notepad or VS Code and paste its **entire** text,
   including the `-----BEGIN …-----` and `-----END …-----` lines, between `R"PEM(` and `)PEM"`:

   | `config.h` constant | File |
   |---|---|
   | `AWS_ROOT_CA` | `AmazonRootCA1.pem` |
   | `DEVICE_CERT` | `…-certificate.pem.crt` |
   | `DEVICE_PRIVATE_KEY` | `…-private.pem.key` |

3. Upload and open the Serial Monitor (115200 baud):

   ```
   MQTT: connecting to a1b2c3d4e5f6g7-ats.iot.ap-south-1.amazonaws.com:8883 as greenpulse-01 ... connected
   -> greenpulse/greenpulse-01/sensors {"soil_moisture":41.5,...}
   ```

4. The MQTT test client (subscribed to `greenpulse/#`) shows a reading every 10 s, and DynamoDB
   gets a new `greenpulse/greenpulse-01/sensors` item for each one.

## 12. Connect Node-RED

1. In the Node-RED editor, double-click any MQTT node, then the pencil next to
   **GreenPulse broker**.
2. **Server:** your endpoint, **Port:** `8883`, **Client ID:** `greenpulse-nodered`.
3. Tick **Use TLS** → pencil next to the TLS configuration (add a new one) and upload from
   `greenpulse-aws\nodered`:
   - **Certificate:** `…-certificate.pem.crt`
   - **Private Key:** `…-private.pem.key`
   - **CA Certificate:** `AmazonRootCA1.pem`

   Keep **Verify server certificate** ticked → **Add**.
4. **Update** → **Update** → **Deploy**. The MQTT nodes show *connected*.

The flow already subscribes with QoS 1. AWS IoT Core does not support QoS 2.

## 13. Final check

| # | Check | Expected |
|---|---|---|
| 1 | ESP32 Serial Monitor | `connected`, a reading every 10 s |
| 2 | Bridge log | `Connected to …:8883`, one line per reading, an analysis line |
| 3 | Dashboard | **ESP32: Online**, gauges moving, advice card filled in |
| 4 | **Water now** on the dashboard (pump outlet in the tank) | the pump runs 5 s; DynamoDB gets a `pump/command` item (`source: manual`) and two `pump/state` items (`on`, then `off`) |
| 5 | Unplug the ESP32 | within about a minute the dashboard shows **ESP32: Offline**, and DynamoDB gets a `status` item with `online: false` (the last will) |
| 6 | IoT Core → **Monitor** | connections, messages and rule runs on the graphs |
| 7 | CloudWatch → `AWSIotLogsV2` and `/greenpulse/iot-rule-errors` | no new errors |

## 14. Download the data as CSV

1. DynamoDB → **Explore items** → `GreenPulseLog` → **Query**.
2. **topic (Partition key):** `greenpulse/greenpulse-01/sensors` (or `…/ai/care`,
   `…/pump/state`, `…/status`, `…/pump/command`).
3. Optional: tick **Sort descending** for the newest first.
4. **Run**, select the items (the checkbox at the top selects the page), then **Actions** →
   **Download selected items to CSV**.

The console downloads one page at a time. To turn `ts` into a date in Excel, with `ts` in column
A: `=A2/86400000 + DATE(1970,1,1) + 5.5/24` (Sri Lanka time; leave out `+ 5.5/24` for UTC), then
format the cell as a date and time.

## Keeping it safe and cheap

- One certificate per client, never shared. If a private key leaks (committed, emailed, posted in a
  chat), deactivate that certificate at once (**Security** → **Certificates** → **Actions** →
  **Deactivate**) and create a new one.
- `config.h` and `backend/certs/` are git-ignored. Check `git status` before every commit anyway.
- When you are not using the project, unplug the ESP32 and **stop** the EC2 instance. IoT Core and
  the rule only cost money while messages flow.
- After the project is graded, delete the rule, the table, the Things, the certificates and the
  EC2 instance to end all charges.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| ESP32: `failed (state -2)` over and over | Wrong endpoint, a certificate pasted incompletely (missing BEGIN/END lines), the certificate not attached to the Thing, or no internet |
| A client connects, then drops every few seconds | It published or subscribed outside its policy (find the topic in `AWSIotLogsV2`, look for `AUTHORIZATION_FAILURE`), or two clients use the same client ID |
| ESP32 refused but the policy looks right | `DEVICE_ID` differs from the Thing name, so `${iot:Connection.Thing.ThingName}` doesn't match |
| Bridge: `FileNotFoundError` or an SSL error at start | A certificate path in `.env` is wrong; run the bridge from the `backend` folder |
| Bridge: `MQTT connection refused` | Certificate inactive, or the policy not attached to the backend's certificate |
| Retained messages missing after a restart | `iot:RetainPublish` missing from that client's policy |
| No items in DynamoDB | Look in `/greenpulse/iot-rule-errors`. Usually the key names don't match exactly (`topic` String, `ts` Number) or the rule is disabled |
| `ai/input`, `priority` or `pump/auto` items in DynamoDB | The rule's SQL has no `WHERE` clause; use the statement in step 8 |
| Everything is in the wrong region | Things, rules and tables only show in the region they were created in; switch the region top right |
