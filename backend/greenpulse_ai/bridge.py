"""Live MQTT bridge: ESP32 readings in; Plant Doctor advice, LED priority and pump commands out.

    python -m greenpulse_ai.bridge              # broker and LLM settings from .env
    python -m greenpulse_ai.bridge --offline    # rule-based agents only, no LLM calls
    python -m greenpulse_ai.bridge --demo       # simulated ESP32, no broker needed (see demo.py)

Subscribes to  <prefix>/+/sensors      readings from every ESP32
               <prefix>/+/pump/state   the ESP32 reporting pump on / off / rejected (auto and manual runs)
               <prefix>/+/pump/auto    the auto-watering switch on either dashboard (retained)
Publishes      <prefix>/<id>/ai/input, ai/care, priority (see mqtt_payloads) and <prefix>/<id>/pump/command,
               plus <prefix>/<id>/pump/auto when the switch is flipped on the Next.js dashboard

It also serves the dashboard API (api.py) for the Next.js dashboard and its chat, on API_HOST:API_PORT,
and emails alerts and daily summaries to the addresses added on the dashboard (alerts.py, SMTP_HOST).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import queue
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .accounts import Accounts
from .agents.chat import ChatAgent
from .agents.profile import PlantProfileAgent
from .alerts import AlertCenter
from .api import create_app, serve_in_background
from .config import Settings
from .demo import SimulatedEsp32
from .device_state import DeviceStore
from .llm import create_chat_model
from .mailer import Mailer
from .mqtt_payloads import Topics, build_messages, parse_sensor_payload
from .orchestrator import PlantCareService, build_service, describe_context, live_context_agents
from .plant_library import PlantLibrary
from .plant_profiles import PROFILES, get_profile
from .schemas import CareResult, SensorReading
from .watering import WateringPolicy

log = logging.getLogger("greenpulse.bridge")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Bridge:
    def __init__(
        self,
        settings: Settings,
        service: PlantCareService,
        policy: WateringPolicy,
        client: mqtt.Client | None = None,
        clock: Callable[[], datetime] = _utcnow,
        store: DeviceStore | None = None,
        alerts: AlertCenter | None = None,
    ):
        self.settings = settings
        self.service = service
        self.policy = policy
        self.topics = Topics(settings.topic_prefix)
        self.clock = clock
        # What the dashboard API and the Chat Agent read: recent readings, the last result, pump events.
        self.store = store or DeviceStore(get_profile(settings.plant_profile), policy.is_enabled, clock)
        self.alerts = alerts
        self.client = client or create_client(settings)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        # handle_reading blocks for seconds while the LLM runs, so it must not run on the MQTT network thread.
        self._readings: queue.Queue[SensorReading | None] = queue.Queue(maxsize=500)
        self._worker = threading.Thread(target=self._work, name="plant-doctor", daemon=True)
        # Devices whose next reading is analysed straight away (the auto-watering switch was just turned on),
        # instead of waiting up to ANALYSIS_INTERVAL_S for the next scheduled analysis.
        self._analyse_next: set[str] = set()

    # ------------------------------------------------------------------ lifecycle

    def run_forever(self) -> None:
        self._worker.start()
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        self.client.loop_forever(retry_first_connection=True)

    def stop(self) -> None:
        self._readings.put(None)
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("Connected to %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
        client.subscribe(
            [(self.topics.sensors("+"), 0), (self.topics.pump_state("+"), 1), (self.topics.pump_auto("+"), 1)]
        )

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        log.warning("Disconnected from the broker (%s); reconnecting", reason_code)

    def _on_message(self, client, userdata, message: mqtt.MQTTMessage) -> None:
        self.handle_message(message.topic, message.payload)

    # ------------------------------------------------------------------ incoming

    def handle_message(self, topic: str, payload: bytes) -> None:
        device_id, _, kind = topic.removeprefix(f"{self.topics.prefix}/").partition("/")
        try:
            if kind == "sensors":
                reading = parse_sensor_payload(payload, device_id=device_id)
                log.info(
                    "%s  soil %s  %s  %s",
                    reading.device_id,
                    _fmt(reading.soil_moisture, "%"),
                    _fmt(reading.temperature, "°C"),
                    _fmt(reading.humidity, "% RH"),
                )
                self.store.record_reading(reading)
                try:
                    self._readings.put_nowait(reading)
                except queue.Full:
                    log.warning("Analysis queue is full; dropping a reading from %s", device_id)
            elif kind == "pump/state":
                state = json.loads(payload)
                if not isinstance(state, dict):
                    raise ValueError("expected a JSON object")
                log.info("%s  pump %s", device_id, json.dumps(state))
                self.policy.record_pump_state(device_id, state, self.clock())
                self.store.record_pump_state(device_id, state, self.clock())
            elif kind == "pump/auto":
                enabled = _parse_switch(payload)
                self._apply_auto_watering(device_id, enabled)
                log.info("%s  auto-watering %s", device_id, "ON" if enabled else "OFF")
        except ValueError as exc:  # bad JSON or a payload that fails validation
            log.warning("Ignoring bad payload on %s: %s", topic, exc)

    def _apply_auto_watering(self, device_id: str, enabled: bool) -> None:
        if enabled and not self.policy.is_enabled(device_id):
            self._analyse_next.add(device_id)
        self.policy.set_enabled(device_id, enabled)

    # ------------------------------------------------------------------ dashboard controls (api.PumpControls)

    def water_now(self, device_id: str) -> float:
        """The Next.js dashboard's "Water now" button: one manual pulse, the same command Node-RED sends.
        The ESP32 applies its own limits and reports on pump/state, which also starts the auto cooldown."""
        command = {"action": "on", "duration_s": self.policy.pulse_s, "source": "manual", "reason": "Dashboard button"}
        self._publish(self.topics.pump_command(device_id), command, retain=False)
        return self.policy.pulse_s

    def set_auto_watering(self, device_id: str, enabled: bool) -> None:
        """The Next.js dashboard's auto-watering switch. Published retained, like the Node-RED switch, so
        both dashboards show the same state and a restarted bridge picks it up again."""
        self._publish(self.topics.pump_auto(device_id), enabled, retain=True)
        self._apply_auto_watering(device_id, enabled)
        log.info("%s  auto-watering %s (Next.js dashboard)", device_id, "ON" if enabled else "OFF")

    # ------------------------------------------------------------------ analysis

    def _work(self) -> None:
        while (reading := self._readings.get()) is not None:
            try:
                self.process(reading)
            except Exception:
                log.exception("Plant Doctor failed on a reading from %s", reading.device_id)

    def process_pending(self) -> None:
        """Process queued readings on the calling thread (for tests and scripts)."""
        while True:
            try:
                reading = self._readings.get_nowait()
            except queue.Empty:
                return
            if reading is not None:
                self.process(reading)

    def process(self, reading: SensorReading) -> CareResult | None:
        force = reading.device_id in self._analyse_next
        self._analyse_next.discard(reading.device_id)
        result = self.service.handle_reading(reading, force=force)
        if result is None:
            return None

        decision = self.policy.decide(result, self.clock())
        self.store.record_result(result, decision)
        retained = self.topics.retained(result.device_id)
        for topic, payload in build_messages(result, self.topics, decision):
            self._publish(topic, payload, retain=topic in retained)
        if decision.water:
            self._publish(self.topics.pump_command(result.device_id), decision.command(), retain=False)

        pump = f"pump ON {decision.duration_s:g} s" if decision.water else f"pump: {decision.reason}"
        log.info(
            "%s  -> [%s] %s %s | %s | %s via %s",
            result.device_id,
            result.trigger,
            result.priority.upper(),
            result.advice.headline,
            pump,
            result.doctor_source,
            result.model or "rules",
        )
        if self.alerts:
            self.alerts.on_result(result, decision)
        return result

    def _publish(self, topic: str, payload: dict | bool, retain: bool) -> None:
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=retain)


def create_client(settings: Settings) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id, clean_session=True)
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if uses_tls(settings):
        # AWS IoT Core: Amazon root CA + this backend's own device certificate and private key.
        client.tls_set(ca_certs=settings.mqtt_ca_file, certfile=settings.mqtt_cert_file, keyfile=settings.mqtt_key_file)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def uses_tls(settings: Settings) -> bool:
    return bool(settings.mqtt_ca_file or settings.mqtt_cert_file or settings.mqtt_port == 8883)


def _parse_switch(payload: bytes) -> bool:
    """The Node-RED switch sends true/false; {"enabled": true} and "on"/"off" work too."""
    text = payload.decode().strip()
    try:
        value = json.loads(text)
    except ValueError:
        value = text
    if isinstance(value, dict):
        value = value.get("enabled")
    if isinstance(value, str):
        value = value.lower() in {"1", "true", "on", "yes"}
    if not isinstance(value, bool | int):
        raise ValueError(f"expected true/false, got {text!r}")
    return bool(value)


def describe_alerts(alerts: AlertCenter) -> str:
    if not alerts.mailer:
        return "Email alerts: off (set SMTP_HOST in .env to send them)"
    confirmed = sum(1 for r in alerts.overview()["recipients"] if r["verified"])
    return (
        f"Email alerts: from {alerts.mailer.username} via {alerts.mailer.host}:{alerts.mailer.port} to "
        f"{confirmed} confirmed address{'' if confirmed == 1 else 'es'}; daily summary at {alerts.daily_hour:02d}:00"
    )


def describe_accounts(accounts: Accounts) -> str:
    count = accounts.count()
    sign_in = f"Dashboard sign-in: {count} account{'' if count == 1 else 's'}"
    if accounts.registration_open:
        return f"{sign_in}; registration open to anyone with REGISTRATION_CODE"
    return f"{sign_in}; registration closed (set REGISTRATION_CODE in .env to open it)"


def _fmt(value: float | None, unit: str) -> str:
    return "--" if value is None else f"{value:g}{unit}"


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # logging writes to stderr
    parser = argparse.ArgumentParser(
        prog="python -m greenpulse_ai.bridge",
        description="Connect the Multi-Agent Plant Doctor to the MQTT broker and process live ESP32 readings.",
    )
    parser.add_argument("--offline", action="store_true", help="rule-based agents only; no LLM calls")
    parser.add_argument(
        "--plant", choices=PROFILES, help="plant for devices not given one on the dashboard (default: PLANT_PROFILE or pothos)"
    )
    parser.add_argument(
        "--demo",
        nargs="?",
        const=40.0,
        type=float,
        metavar="SOIL",
        help="simulated ESP32 instead of the MQTT broker, starting at SOIL %% moisture (default 40; try 25 for dry soil)",
    )
    parser.add_argument("--no-api", action="store_true", help="don't serve the dashboard API")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "openai", "groq", "greenpulse_ai.orchestrator"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = Settings.from_env()
    if args.offline:
        settings = dataclasses.replace(settings, offline=True)
    if args.plant:
        settings = dataclasses.replace(settings, plant_profile=args.plant)

    llm = create_chat_model(settings)
    weather, notifications = live_context_agents(settings)
    # Each device's plant: chosen on the dashboard, else PLANT_PROFILE. Every agent reads it from here.
    plants = PlantLibrary(settings.plants_file, settings.plant_profile)
    service = build_service(settings, llm, weather, notifications, profile_for=plants.profile_for)
    policy = WateringPolicy.from_settings(settings)
    store = DeviceStore(get_profile(settings.plant_profile), policy.is_enabled, profile_for=plants.profile_for)
    client = None
    if args.demo is not None:
        client = SimulatedEsp32(settings.device_id, settings.topic_prefix, soil=args.demo)
        service.preload(client.backfill(store))
    alerts = AlertCenter(
        Mailer.from_settings(settings),
        store,
        settings.alerts_file,
        settings.timezone,
        settings.daily_summary_hour,
        settings.dashboard_url,
    )
    alerts.start()
    bridge = Bridge(settings, service, policy, client=client, store=store, alerts=alerts)

    if args.demo is not None:
        broker = f"simulated ESP32 {settings.device_id} (demo, no broker)"
    else:
        broker = f"{settings.mqtt_host}:{settings.mqtt_port}{' (TLS)' if uses_tls(settings) else ''}"
    accounts = Accounts(settings.users_file, settings.registration_code)
    if args.no_api:
        api = "dashboard API off"
    else:
        chat = ChatAgent(store, llm, settings.llm_model, settings.location, settings.timezone)
        info = {
            "demo": args.demo is not None,
            "location": settings.location,
            "watering": {
                "pulse_s": settings.water_pulse_s,
                "cooldown_s": settings.water_cooldown_s,
                "max_per_day": settings.water_max_per_day,
            },
        }
        profile_agent = PlantProfileAgent(llm, settings.llm_model, settings.location)
        app = create_app(store, chat, bridge, settings.device_id, info, plants, profile_agent, alerts, accounts)
        serve_in_background(app, settings.api_host, settings.api_port)
        api = f"dashboard API on http://{settings.api_host}:{settings.api_port}"
    print(
        f"GreenPulse bridge | broker {broker} | "
        f"plant: {plants.profile_for(settings.device_id).name} | "
        f"mode: {'LLM ' + settings.llm_model if llm else 'rules only (offline)'} | "
        f"auto-watering: {'on' if settings.auto_watering else 'off'} until the dashboard switch says otherwise\n"
        f"{describe_context(settings)}\n"
        f"{describe_alerts(alerts)}\n"
        f"{describe_accounts(accounts)}\n"
        f"Listening on {bridge.topics.sensors('+')}; {api}. Ctrl+C to stop.\n",
        flush=True,
    )
    try:
        bridge.run_forever()
    except KeyboardInterrupt:
        bridge.stop()


if __name__ == "__main__":
    main()
