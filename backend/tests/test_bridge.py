import json

from greenpulse_ai import Settings, build_service
from greenpulse_ai.agents import ImapNotificationAgent, OpenMeteoWeatherAgent
from greenpulse_ai.bridge import Bridge, _parse_switch, uses_tls
from greenpulse_ai.watering import WateringPolicy

from conftest import T0, FakeImap, make_email, open_meteo_response


class FakeClient:
    """Records what the bridge publishes instead of talking to a broker."""

    def __init__(self):
        self.published: list[tuple[str, dict, bool]] = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload), retain))

    def topics(self):
        return [topic for topic, _, _ in self.published]


def make_bridge(auto_watering=False):
    settings = Settings(offline=True, auto_watering=auto_watering)
    client = FakeClient()
    bridge = Bridge(settings, build_service(settings, None), WateringPolicy.from_settings(settings), client, clock=lambda: T0)
    return bridge, client


def sensors(moisture, temperature=26.0, humidity=60.0):
    return json.dumps({"soil_moisture": moisture, "temperature": temperature, "humidity": humidity}).encode()


def test_reading_in_advice_out():
    bridge, client = make_bridge()
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(50))
    bridge.process_pending()

    assert client.topics() == [
        "greenpulse/greenpulse-01/ai/input",
        "greenpulse/greenpulse-01/ai/care",
        "greenpulse/greenpulse-01/priority",
    ]
    retained = {topic for topic, _, retain in client.published if retain}
    assert retained == {"greenpulse/greenpulse-01/ai/care", "greenpulse/greenpulse-01/priority"}
    care = client.published[1][1]
    assert care["priority"] == "low"
    assert care["watering"] == {
        "auto_enabled": False,
        "decision": "skip",
        "duration_s": 0.0,
        "reason": "Auto-watering is off",
    }


def test_dry_soil_with_auto_watering_sends_a_pump_command():
    bridge, client = make_bridge(auto_watering=True)
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))
    bridge.process_pending()

    topic, command, retain = client.published[-1]
    assert topic == "greenpulse/greenpulse-01/pump/command"
    assert command["action"] == "on" and command["source"] == "auto" and command["duration_s"] == 5.0
    assert not retain  # a retained command would re-run on every ESP32 reconnect


def test_dashboard_switch_enables_auto_watering():
    bridge, client = make_bridge()
    bridge.handle_message("greenpulse/greenpulse-01/pump/auto", b"true")
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))
    bridge.process_pending()
    assert client.topics()[-1] == "greenpulse/greenpulse-01/pump/command"


def test_turning_the_switch_on_re_analyses_the_next_reading():
    bridge, client = make_bridge()
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))  # throttled: nothing new
    bridge.process_pending()
    assert len(client.published) == 3

    bridge.handle_message("greenpulse/greenpulse-01/pump/auto", b"true")
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))  # back to normal throttling
    bridge.process_pending()
    assert client.topics()[3:] == [
        "greenpulse/greenpulse-01/ai/input",
        "greenpulse/greenpulse-01/ai/care",
        "greenpulse/greenpulse-01/priority",
        "greenpulse/greenpulse-01/pump/command",
    ]
    assert client.published[4][1]["trigger"] == "forced"


def test_manual_watering_reported_by_the_esp32_blocks_auto_watering():
    bridge, client = make_bridge(auto_watering=True)
    bridge.handle_message("greenpulse/greenpulse-01/pump/state", b'{"state": "on", "source": "manual", "duration_s": 5}')
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(18))
    bridge.process_pending()
    assert "greenpulse/greenpulse-01/pump/command" not in client.topics()
    assert "soak" in client.published[1][1]["watering"]["reason"]


def test_bad_payloads_are_ignored():
    bridge, client = make_bridge()
    bridge.handle_message("greenpulse/greenpulse-01/sensors", b"not json")
    bridge.handle_message("greenpulse/greenpulse-01/sensors", b'{"soil_moisture": "wet"}')
    bridge.handle_message("greenpulse/greenpulse-01/pump/state", b'"on"')
    bridge.handle_message("greenpulse/greenpulse-01/pump/auto", b"maybe")
    bridge.process_pending()
    assert client.published == []


def test_throttled_readings_publish_nothing():
    bridge, client = make_bridge()
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(50))
    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(49.9))
    bridge.process_pending()
    assert len(client.published) == 3  # only the first reading was analysed


def test_device_id_comes_from_the_topic():
    bridge, client = make_bridge()
    bridge.handle_message("greenpulse/balcony-02/sensors", sensors(50))
    bridge.process_pending()
    assert client.topics()[0] == "greenpulse/balcony-02/ai/input"


def test_live_weather_and_email_reach_the_plant_doctor():
    """End to end with the real Weather and Notification agents (fake HTTP and IMAP underneath):
    ESP32 reading in -> Open-Meteo forecast + mailbox reminder -> Plant Doctor -> MQTT out."""
    settings = Settings(offline=True)
    weather = OpenMeteoWeatherAgent(
        "Colombo, LK", 6.9271, 79.8612, fetch=lambda url, params, timeout: open_meteo_response(code=0, hourly_temps=(34.0,), rain=(5,))
    )
    imap = FakeImap([make_email("Booking confirmed: Kandy trip", "Your trip starts this Friday (3 nights).")])
    notifications = ImapNotificationAgent("imap.gmail.com", "plant.owner@gmail.com", "app-password", connect=imap)
    client = FakeClient()
    service = build_service(settings, None, weather, notifications)
    bridge = Bridge(settings, service, WateringPolicy.from_settings(settings), client, clock=lambda: T0)

    bridge.handle_message("greenpulse/greenpulse-01/sensors", sensors(50))
    bridge.process_pending()

    ai_input, care = client.published[0][1], client.published[1][1]
    assert ai_input["weather"]["source"] == "open-meteo" and ai_input["weather"]["heat_alert"]
    assert ai_input["notifications"]["source"] == "email"
    assert [r["kind"] for r in ai_input["notifications"]["reminders"]] == ["travel"]
    assert care["headline"] == "Water well before your trip"


def test_switch_payloads():
    assert _parse_switch(b"true") is True
    assert _parse_switch(b"false") is False
    assert _parse_switch(b'{"enabled": true}') is True
    assert _parse_switch(b"OFF") is False


def test_tls_is_used_for_aws_iot_core():
    assert not uses_tls(Settings())
    assert uses_tls(Settings(mqtt_port=8883))
    assert uses_tls(Settings(mqtt_ca_file="AmazonRootCA1.pem"))
