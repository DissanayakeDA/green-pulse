/*
  GreenPulse ESP32 firmware

  - Reads soil moisture (capacitive sensor) and temperature/humidity (DHT22) and publishes them over MQTT.
  - The display (16x2 I2C LCD or SSD1306 OLED) shows only the live readings and the Wi-Fi/MQTT status.
  - The RGB LED shows the care priority published by the AI backend (green, yellow, orange, red).
  - The water pump runs only on a pump/command message (auto from the backend, or manual from Node-RED),
    and only within the hard limits in config.h. A hardware timer switches it off even if the loop stalls.

  Topics (<p> = TOPIC_PREFIX/DEVICE_ID):
    publish   <p>/sensors       {"soil_moisture":41.5,"temperature":29.1,"humidity":58.0,"soil_raw":2310,"rssi":-61}
    publish   <p>/status        {"online":true,...}   retained; the broker publishes {"online":false} if we drop off
    publish   <p>/pump/state    {"state":"on"|"off"|"rejected","source":"auto"|"manual",...}
    subscribe <p>/priority      {"priority":"high","priority_code":2,"led":"orange"}
    subscribe <p>/pump/command  {"action":"on","duration_s":5,"source":"manual"}  or  {"action":"off"}

  Libraries (Arduino IDE > Library Manager): PubSubClient (Nick O'Leary), ArduinoJson (Benoit Blanchon, v7),
  DHT sensor library (Adafruit), Adafruit Unified Sensor, plus for the display either LiquidCrystal I2C
  (Frank de Brabander) or Adafruit SSD1306 + Adafruit GFX Library.
  Board: "ESP32 Dev Module" (esp32 by Espressif Systems).
*/

#if __has_include("config.h")
#include "config.h"
#else
#error "Copy config.example.h to config.h (same folder) and fill in your Wi-Fi and MQTT settings."
#endif

#include <ArduinoJson.h>
#include <DHT.h>
#include <PubSubClient.h>
#include <Ticker.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#if DISPLAY_TYPE == 1
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#elif DISPLAY_TYPE == 2
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Wire.h>
#endif

#define FIRMWARE_VERSION "1.0.0"
#define MQTT_RETRY_MS 5000

#if MQTT_USE_TLS
WiFiClientSecure net;
#else
WiFiClient net;
#endif
PubSubClient mqtt(net);
DHT dht(DHT_PIN, DHT_TYPE);

#if DISPLAY_TYPE == 1
LiquidCrystal_I2C lcd(DISPLAY_ADDRESS, 16, 2);
#elif DISPLAY_TYPE == 2
Adafruit_SSD1306 display(128, 64, &Wire, -1);
#endif
bool displayFound = false;

String topicSensors, topicStatus, topicPriority, topicPumpCommand, topicPumpState;

float soilPct = NAN, tempC = NAN, humidityPct = NAN;  // NAN = failed read
int soilRaw = 0;
int priorityCode = -1;  // -1 = no advice from the backend yet
bool publishNow = true;
unsigned long lastSensorMs = 0, lastMqttAttemptMs = 0, lastDisplayMs = 0, lastDisplayProbeMs = 0;

Ticker pumpTimer;
volatile bool pumpTimerFired = false;
bool pumpRunning = false, pumpHasRun = false;
unsigned long pumpStartedMs = 0, pumpStoppedMs = 0;
char pumpSource[16] = "";

// The MQTT callback only copies a pump command here; loop() runs it. PubSubClient uses one buffer for
// incoming and outgoing messages, so publishing from inside the callback would corrupt the message.
struct {
  bool pending;
  bool on;
  float seconds;
  char source[16];
  char reason[160];
} pumpCommand = {};

// ------------------------------------------------------------------ outputs

void setRelay(bool on) {
  digitalWrite(PUMP_PIN, (on != (PUMP_ACTIVE_LOW != 0)) ? HIGH : LOW);
}

void setLed(int code) {
  static const uint8_t colours[4][3] = {
    {0, 255, 0},    // 0 low: green
    {255, 140, 0},  // 1 medium: yellow (the green die is brighter, so it needs less)
    {255, 40, 0},   // 2 high: orange
    {255, 0, 0},    // 3 critical: red
  };
  uint8_t r = 0, g = 0, b = 40;  // dim blue: waiting for the first advice
  if (code >= 0 && code <= 3) {
    r = colours[code][0];
    g = colours[code][1];
    b = colours[code][2];
  }
#if RGB_COMMON_ANODE
  r = 255 - r;
  g = 255 - g;
  b = 255 - b;
#endif
  analogWrite(LED_R_PIN, r);
  analogWrite(LED_G_PIN, g);
  analogWrite(LED_B_PIN, b);
}

#if DISPLAY_TYPE
bool probeDisplay() {
  Wire.beginTransmission(DISPLAY_ADDRESS);
  if (Wire.endTransmission() != 0) return false;
#if DISPLAY_TYPE == 1
  lcd.init();
  lcd.backlight();
  return true;
#else
  return display.begin(SSD1306_SWITCHCAPVCC, DISPLAY_ADDRESS);
#endif
}

void reportI2cBus() {
  Serial.printf("Display: nothing at I2C address 0x%02X. Devices on SDA %d / SCL %d:", DISPLAY_ADDRESS, SDA, SCL);
  int found = 0;
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf(" 0x%02X", address);
      found++;
    }
  }
  if (found) Serial.println("  -> put that address in DISPLAY_ADDRESS in config.h");
  else Serial.println(" none -> check the display's VCC (5 V / VIN), GND, SDA and SCL wires");
}
#endif

#if DISPLAY_TYPE == 1
void lcdLine(uint8_t row, const char *text) {
  char padded[17];  // pad to the full width instead of lcd.clear(), which flickers
  snprintf(padded, sizeof(padded), "%-16s", text);
  lcd.setCursor(0, row);
  lcd.print(padded);
}
#endif

void updateDisplay() {
  if (!displayFound) return;
#if DISPLAY_TYPE == 1
  // S:41% T:29.1C
  // H:58% MQTT:OK
  char soil[8] = "--", temp[10] = "--", humidity[8] = "--", line[24];
  if (!isnan(soilPct)) snprintf(soil, sizeof(soil), "%.0f%%", soilPct);
  if (!isnan(tempC)) snprintf(temp, sizeof(temp), "%.1fC", tempC);
  if (!isnan(humidityPct)) snprintf(humidity, sizeof(humidity), "%.0f%%", humidityPct);
  snprintf(line, sizeof(line), "S:%s T:%s", soil, temp);
  lcdLine(0, line);
  const char *link = WiFi.status() != WL_CONNECTED ? "WiFi:--" : mqtt.connected() ? "MQTT:OK" : "MQTT:--";
  snprintf(line, sizeof(line), "H:%s %s", humidity, link);
  lcdLine(1, line);
#elif DISPLAY_TYPE == 2
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("GreenPulse");
  display.drawFastHLine(0, 10, 128, SSD1306_WHITE);

  display.setCursor(0, 15);
  display.setTextSize(2);
  if (isnan(soilPct)) display.print("Soil --");
  else display.printf("Soil %.0f%%", soilPct);

  display.setTextSize(1);
  display.setCursor(0, 35);
  if (isnan(tempC)) display.print("Temp --    ");
  else display.printf("Temp %.1fC ", tempC);
  if (isnan(humidityPct)) display.print("Hum --");
  else display.printf("Hum %.0f%%", humidityPct);

  display.setCursor(0, 47);
  display.printf("WiFi %s", WiFi.status() == WL_CONNECTED ? "OK" : "--");
  display.setCursor(0, 57);
  if (mqtt.connected()) display.print("MQTT connected");
  else display.printf("MQTT offline (%d)", mqtt.state());
  display.display();
#endif
}

// ------------------------------------------------------------------ MQTT

void publishJson(const String &topic, JsonDocument &doc, bool retained = false) {
  char buffer[512];
  size_t length = serializeJson(doc, buffer, sizeof(buffer));
  bool sent = mqtt.connected() && mqtt.publish(topic.c_str(), (const uint8_t *)buffer, length, retained);
  Serial.printf("%s %s %s\n", sent ? "->" : "(not sent)", topic.c_str(), buffer);
}

void onMqttMessage(char *topic, byte *payload, unsigned int length) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, (const byte *)payload, length);
  if (error) {
    Serial.printf("Bad JSON on %s: %s\n", topic, error.c_str());
    return;
  }

  if (topicPriority == topic) {
    int code = doc["priority_code"] | -1;
    if (code >= 0 && code <= 3) {
      priorityCode = code;
      setLed(code);
      Serial.printf("Priority: %s\n", doc["priority"] | "?");
    }
  } else if (topicPumpCommand == topic) {
    const char *action = doc["action"] | "";
    if (strcmp(action, "on") != 0 && strcmp(action, "off") != 0) {
      Serial.printf("Unknown pump action '%s'\n", action);
      return;
    }
    pumpCommand.on = strcmp(action, "on") == 0;
    pumpCommand.seconds = doc["duration_s"] | 0.0f;
    strlcpy(pumpCommand.source, doc["source"] | "manual", sizeof(pumpCommand.source));
    strlcpy(pumpCommand.reason, doc["reason"] | "", sizeof(pumpCommand.reason));
    pumpCommand.pending = true;
  }
}

void connectMqtt() {
  Serial.printf("MQTT: connecting to %s:%d as %s ... ", MQTT_HOST, MQTT_PORT, DEVICE_ID);
  const char *user = strlen(MQTT_USERNAME) ? MQTT_USERNAME : nullptr;
  const char *password = strlen(MQTT_PASSWORD) ? MQTT_PASSWORD : nullptr;
  if (!mqtt.connect(DEVICE_ID, user, password, topicStatus.c_str(), 1, true, "{\"online\":false}")) {
    Serial.printf("failed (state %d), retrying in %d s\n", mqtt.state(), MQTT_RETRY_MS / 1000);
    return;
  }
  Serial.println("connected");
  mqtt.subscribe(topicPriority.c_str(), 1);
  mqtt.subscribe(topicPumpCommand.c_str(), 1);

  JsonDocument status;
  status["online"] = true;
  status["ip"] = WiFi.localIP().toString();
  status["rssi"] = WiFi.RSSI();
  status["firmware"] = FIRMWARE_VERSION;
  publishJson(topicStatus, status, true);
  publishNow = true;
}

// ------------------------------------------------------------------ pump

void onPumpTimer() {  // runs in the esp_timer task, independent of loop()
  setRelay(false);
  pumpTimerFired = true;
}

void pumpReject(const char *source, const char *detail) {
  JsonDocument doc;
  doc["state"] = "rejected";
  doc["source"] = source;
  doc["detail"] = detail;
  publishJson(topicPumpState, doc);
}

void pumpStart(float seconds, const char *source, const char *reason) {
  char detail[64];
  if (pumpRunning) return pumpReject(source, "pump is already running");
  if (!(seconds > 0)) return pumpReject(source, "duration_s must be above 0");
  unsigned long restedMs = millis() - pumpStoppedMs;
  if (pumpHasRun && restedMs < PUMP_MIN_REST_S * 1000UL) {
    snprintf(detail, sizeof(detail), "pump is resting, %lu s left", (PUMP_MIN_REST_S * 1000UL - restedMs) / 1000 + 1);
    return pumpReject(source, detail);
  }
  if (!isnan(soilPct) && soilPct >= PUMP_WET_CUTOFF) {
    snprintf(detail, sizeof(detail), "soil is already wet (%.0f%%)", soilPct);
    return pumpReject(source, detail);
  }

  seconds = min(seconds, (float)PUMP_MAX_RUN_S);
  strlcpy(pumpSource, source, sizeof(pumpSource));
  pumpTimerFired = false;
  pumpRunning = true;
  pumpStartedMs = millis();
  setRelay(true);
  pumpTimer.once(seconds, onPumpTimer);

  JsonDocument doc;
  doc["state"] = "on";
  doc["source"] = source;
  doc["duration_s"] = seconds;
  doc["reason"] = reason;
  publishJson(topicPumpState, doc);
}

void pumpFinished(const char *result) {
  pumpRunning = false;
  pumpHasRun = true;
  pumpStoppedMs = millis();
  JsonDocument doc;
  doc["state"] = "off";
  doc["source"] = pumpSource;
  doc["ran_s"] = serialized(String((pumpStoppedMs - pumpStartedMs) / 1000.0f, 1));
  doc["result"] = result;
  publishJson(topicPumpState, doc);
}

void pumpStop(const char *result) {
  pumpTimer.detach();
  setRelay(false);
  if (pumpRunning) pumpFinished(result);
}

void handlePump() {
  if (pumpTimerFired) {
    pumpTimerFired = false;
    if (pumpRunning) pumpFinished("done");
  }
  // Backup in case the timer never fired.
  if (pumpRunning && millis() - pumpStartedMs > (PUMP_MAX_RUN_S + 2) * 1000UL) pumpStop("safety timeout");

  if (pumpCommand.pending) {
    pumpCommand.pending = false;
    if (pumpCommand.on) pumpStart(pumpCommand.seconds, pumpCommand.source, pumpCommand.reason);
    else pumpStop("stopped");
  }
}

// ------------------------------------------------------------------ sensors

void readSensors() {
  long sum = 0;
  for (int i = 0; i < 16; i++) {
    sum += analogRead(SOIL_PIN);
    delay(2);
  }
  soilRaw = sum / 16;
  if (soilRaw < 100 || soilRaw > 4000) {
    soilPct = NAN;  // probe unplugged or shorted
  } else {
    soilPct = constrain((SOIL_DRY_RAW - soilRaw) * 100.0f / (SOIL_DRY_RAW - SOIL_WET_RAW), 0.0f, 100.0f);
  }
  tempC = dht.readTemperature();
  humidityPct = dht.readHumidity();
  Serial.printf("soil raw %d -> %.1f %%, %.1f C, %.1f %% RH\n", soilRaw, soilPct, tempC, humidityPct);
  if (isnan(tempC) || isnan(humidityPct)) {
    Serial.printf("DHT22: no answer on GPIO %d -> check its DATA, VCC and GND wires (bare sensor: 10k from DATA to VCC)\n", DHT_PIN);
  }
}

void addReading(JsonDocument &doc, const char *key, float value) {
  if (isnan(value)) doc[key] = nullptr;
  else doc[key] = serialized(String(value, 1));
}

void publishReading() {
  JsonDocument doc;
  addReading(doc, "soil_moisture", soilPct);
  addReading(doc, "temperature", tempC);
  addReading(doc, "humidity", humidityPct);
  doc["soil_raw"] = soilRaw;
  doc["rssi"] = WiFi.RSSI();
  publishJson(topicSensors, doc);
}

// ------------------------------------------------------------------ main

const char *wifiStatusText(wl_status_t status) {
  switch (status) {
    case WL_CONNECTED: return "connected";
    case WL_NO_SSID_AVAIL: return "network not found: check WIFI_SSID (the ESP32 only sees 2.4 GHz networks)";
    case WL_CONNECT_FAILED: return "connection refused: check WIFI_PASSWORD";
    case WL_CONNECTION_LOST: return "connection lost";
    default: return "connecting";
  }
}

void setup() {
  pinMode(PUMP_PIN, OUTPUT);
  setRelay(false);  // pump off before anything else

  Serial.begin(115200);
  delay(200);
  Serial.println("\nGreenPulse firmware " FIRMWARE_VERSION);

  setLed(-1);
  analogReadResolution(12);
  dht.begin();
  delay(2000);  // the DHT22 returns nothing for ~2 s after power-up

#if DISPLAY_TYPE
  Wire.begin();
  displayFound = probeDisplay();
  if (displayFound) Serial.printf("Display: found at 0x%02X\n", DISPLAY_ADDRESS);
  else reportI2cBus();  // loop() keeps retrying, so a display plugged in later still works
#endif

  String base = String(TOPIC_PREFIX) + "/" + DEVICE_ID + "/";
  topicSensors = base + "sensors";
  topicStatus = base + "status";
  topicPriority = base + "priority";
  topicPumpCommand = base + "pump/command";
  topicPumpState = base + "pump/state";

#if MQTT_USE_TLS
  net.setCACert(AWS_ROOT_CA);
  net.setCertificate(DEVICE_CERT);
  net.setPrivateKey(DEVICE_PRIVATE_KEY);
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Wi-Fi: connecting to %s\n", WIFI_SSID);
}

void loop() {
  static wl_status_t lastWifi = WL_IDLE_STATUS;
  static unsigned long lastWifiLogMs = 0;
  unsigned long now = millis();

  // While it retries, the status flips many times a second, so log changes at most every 5 s.
  wl_status_t wifi = WiFi.status();
  if (wifi != lastWifi && (wifi == WL_CONNECTED || lastWifi == WL_CONNECTED || now - lastWifiLogMs >= 5000)) {
    lastWifi = wifi;
    lastWifiLogMs = now;
    if (wifi == WL_CONNECTED) Serial.printf("Wi-Fi: connected, IP %s\n", WiFi.localIP().toString().c_str());
    else Serial.printf("Wi-Fi: %s\n", wifiStatusText(wifi));
  }

  if (wifi == WL_CONNECTED) {
    if (!mqtt.connected() && (lastMqttAttemptMs == 0 || now - lastMqttAttemptMs >= MQTT_RETRY_MS)) {
      lastMqttAttemptMs = now;
      connectMqtt();
    }
    mqtt.loop();
  }

  handlePump();

  if (publishNow || now - lastSensorMs >= SENSOR_INTERVAL_MS) {
    publishNow = false;
    lastSensorMs = now;
    readSensors();
    publishReading();
  }

#if DISPLAY_TYPE
  if (!displayFound && now - lastDisplayProbeMs >= 5000) {
    lastDisplayProbeMs = now;
    displayFound = probeDisplay();
    if (displayFound) Serial.printf("Display: found at 0x%02X\n", DISPLAY_ADDRESS);
  }
#endif

  if (now - lastDisplayMs >= 1000) {
    lastDisplayMs = now;
    updateDisplay();
  }
}
