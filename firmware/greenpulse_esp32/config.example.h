// GreenPulse ESP32 settings.
// Copy this file to config.h in the same folder and fill in your values. config.h is git-ignored,
// so your Wi-Fi password and AWS certificates never reach the repository.
#pragma once

// ------------------------------------------------------------------ Wi-Fi (2.4 GHz only)
#define WIFI_SSID     "your-wifi-name"
#define WIFI_PASSWORD "your-wifi-password"

// ------------------------------------------------------------------ MQTT
#define DEVICE_ID    "greenpulse-01"  // MQTT client ID and topic name; on AWS IoT Core, the Thing name
#define TOPIC_PREFIX "greenpulse"

// 0 = local Mosquitto on your laptop (development)
// 1 = AWS IoT Core over TLS (final setup)
#define MQTT_USE_TLS 0

#if !MQTT_USE_TLS
// The laptop's Wi-Fi IP address (run `ipconfig` on Windows), not "localhost": that would be the ESP32 itself.
#define MQTT_HOST     "192.168.1.10"
#define MQTT_PORT     1883
#define MQTT_USERNAME ""
#define MQTT_PASSWORD ""
#else
// AWS IoT Core > Settings > Device data endpoint
#define MQTT_HOST     "xxxxxxxxxxxxxx-ats.iot.ap-south-1.amazonaws.com"
#define MQTT_PORT     8883
#define MQTT_USERNAME ""
#define MQTT_PASSWORD ""

// Paste the full PEM text, including the BEGIN/END lines.
static const char AWS_ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
AmazonRootCA1.pem goes here
-----END CERTIFICATE-----
)PEM";

static const char DEVICE_CERT[] = R"PEM(
-----BEGIN CERTIFICATE-----
xxxxxxxxxx-certificate.pem.crt goes here
-----END CERTIFICATE-----
)PEM";

static const char DEVICE_PRIVATE_KEY[] = R"PEM(
-----BEGIN RSA PRIVATE KEY-----
xxxxxxxxxx-private.pem.key goes here
-----END RSA PRIVATE KEY-----
)PEM";
#endif

// ------------------------------------------------------------------ Pins (ESP32 DevKit V1)
// Analog inputs must be ADC1 pins (GPIO 32-39): ADC2 pins stop working while Wi-Fi is on.
#define SOIL_PIN  34
#define DHT_PIN   4
#define DHT_TYPE  DHT22  // or DHT11

#define LED_R_PIN 18
#define LED_G_PIN 19
#define LED_B_PIN 5
#define RGB_COMMON_ANODE 0  // 1 if the LED's longest leg goes to 3.3 V instead of GND

#define PUMP_PIN 23
#define PUMP_ACTIVE_LOW 1  // 1 for most relay modules (IN pin LOW = relay on); 0 for a MOSFET driver

// Display on I2C (SDA 21, SCL 22): 1 = 16x2 LCD with I2C backpack, 2 = SSD1306 128x64 OLED, 0 = none
#define DISPLAY_TYPE 1
#define DISPLAY_ADDRESS 0x27  // LCD backpacks: 0x27 or 0x3F. OLED: 0x3C

// ------------------------------------------------------------------ Soil sensor calibration
// Open the Serial Monitor (115200 baud) and note the "soil raw" value with the probe in dry air,
// then standing in a glass of water (up to the line on the probe). Put those numbers here.
#define SOIL_DRY_RAW 3000
#define SOIL_WET_RAW 1300

// ------------------------------------------------------------------ Timing and pump safety
#define SENSOR_INTERVAL_MS 10000  // how often to publish a reading

// The ESP32 enforces these whatever the backend or dashboard asks for.
#define PUMP_MAX_RUN_S  15  // longest single run
#define PUMP_MIN_REST_S 60  // shortest pause between runs
#define PUMP_WET_CUTOFF 75  // refuse to pump when the soil already reads at least this %
