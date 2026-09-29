"""Run the Multi-Agent Plant Doctor on hardcoded dummy data (no ESP32 or MQTT broker needed).

    python -m greenpulse_ai                          # default scenario
    python -m greenpulse_ai --scenario overwatered   # one scenario
    python -m greenpulse_ai --all                    # every scenario, as a table
    python -m greenpulse_ai --simulate               # fake ESP32 streaming readings through the service
    python -m greenpulse_ai --offline                # rules only, never call the LLM
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import textwrap
import time

from .agents import DummyNotificationAgent, DummyWeatherAgent
from .config import Settings
from .dummy_data import DEFAULT_SCENARIO, SCENARIOS, Scenario, simulate_readings
from .llm import create_chat_model
from .mqtt_payloads import LED_COLOURS, Topics, build_messages
from .orchestrator import build_pipeline, build_service
from .plant_profiles import PROFILES, get_profile
from .schemas import CareResult

LABEL_WIDTH = 15


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.list:
        for scenario in SCENARIOS.values():
            print(f"{scenario.key:<16}{scenario.title}")
        return

    settings = Settings.from_env()
    if args.offline:
        settings = dataclasses.replace(settings, offline=True)
    if args.plant:
        settings = dataclasses.replace(settings, plant_profile=args.plant)

    llm = create_chat_model(settings)
    mode = f"LLM ({settings.llm_model})" if llm else "rules only (offline; set OPENAI_API_KEY in .env to use the LLM)"
    print(f"GreenPulse Agentic AI Core | plant: {get_profile(settings.plant_profile).name} | mode: {mode}\n")

    if args.simulate:
        _simulate(settings, llm, args.ticks, args.delay, args.analysis_interval)
    elif args.all:
        _run_all(settings, llm)
    else:
        result = _run_scenario(SCENARIOS[args.scenario], settings, llm)
        _print_result(SCENARIOS[args.scenario], result, Topics(settings.topic_prefix), args.json)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m greenpulse_ai",
        description="Run the GreenPulse Multi-Agent Plant Doctor on dummy sensor, weather and inbox data.",
    )
    what = parser.add_mutually_exclusive_group()
    what.add_argument("--scenario", choices=SCENARIOS, default=DEFAULT_SCENARIO, help="scenario to run")
    what.add_argument("--all", action="store_true", help="run every scenario and print a summary table")
    what.add_argument("--simulate", action="store_true", help="stream simulated ESP32 readings through the service")
    what.add_argument("--list", action="store_true", help="list the scenarios")
    parser.add_argument("--plant", choices=PROFILES, help="plant profile (default: PLANT_PROFILE or pothos)")
    parser.add_argument("--offline", action="store_true", help="rule-based agents only; no LLM calls")
    parser.add_argument("--json", action="store_true", help="print the full MQTT payloads")
    parser.add_argument("--ticks", type=int, default=48, help="simulate: readings to generate (10 simulated min each)")
    parser.add_argument("--delay", type=float, default=0.2, help="simulate: real seconds between readings")
    parser.add_argument(
        "--analysis-interval", type=int, default=3600, help="simulate: re-analyse at least every N simulated seconds"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def _run_scenario(scenario: Scenario, settings: Settings, llm) -> CareResult:
    pipeline = build_pipeline(
        settings,
        llm,
        weather_agent=DummyWeatherAgent(scenario.weather, settings.location),
        notification_agent=DummyNotificationAgent(scenario.messages),
    )
    readings = scenario.readings(settings.device_id)
    return pipeline.run(readings[-1], readings, trigger=f"scenario:{scenario.key}")


def _run_all(settings: Settings, llm) -> None:
    print(f"{'scenario':<16}{'baseline':<10}{'final':<10}{'doctor':<16}headline")
    print("-" * 90)
    for scenario in SCENARIOS.values():
        result = _run_scenario(scenario, settings, llm)
        print(
            f"{scenario.key:<16}{result.environment.baseline_priority:<10}{result.priority:<10}"
            f"{result.doctor_source:<16}{result.advice.headline}"
        )


def _simulate(settings: Settings, llm, ticks: int, delay: float, analysis_interval: int) -> None:
    settings = dataclasses.replace(settings, analysis_interval_s=analysis_interval)
    service = build_service(settings, llm)
    print(
        f"Fake ESP32 publishing one reading per 10 simulated minutes; the service re-analyses on the first reading, "
        f"every {analysis_interval // 60} simulated min, on a >= {settings.moisture_change_trigger:g}-point moisture "
        f"change, or when the sensor priority changes.\n"
    )
    analyses = 0
    for i, reading in enumerate(simulate_readings(settings.device_id, count=ticks)):
        result = service.handle_reading(reading)
        line = (
            f"t+{i * 10 // 60:02d}:{i * 10 % 60:02d}  soil {reading.soil_moisture:5.1f}%  "
            f"{reading.temperature:4.1f}°C  {reading.humidity:4.1f}% RH"
        )
        if result:
            analyses += 1
            line += f"  -> [{result.trigger}] {result.priority.upper():<8} {result.advice.headline}"
        print(line, flush=True)
        time.sleep(delay)
    print(f"\n{ticks} readings, {analyses} Plant Doctor analyses")


def _print_result(scenario: Scenario, result: CareResult, topics: Topics, show_json: bool) -> None:
    env, advice = result.environment, result.advice

    print(f"Scenario: {scenario.key} - {scenario.title}")
    print("=" * 78)
    metrics = " | ".join(
        f"{key.replace('_', ' ')} {'--' if m.value is None else f'{m.value:g}{m.unit}'} [{m.state}]"
        for key, m in env.metrics.items()
    )
    _section("SENSORS", metrics)
    if env.moisture_trend_per_hour is not None:
        trend = f"moisture trend {env.moisture_trend_per_hour:+.2f} %/h"
        if env.hours_until_dry is not None:
            trend += f", dry in ~{env.hours_until_dry:g} h"
        _section("", trend)

    _section("ENVIRONMENT", f"[{env.source}] condition {env.condition}, sensor baseline priority {env.baseline_priority}")
    _section("", env.summary)
    for concern in env.concerns:
        _section("", f"- {concern}")
    _section("WEATHER", f"[{result.weather.source}] {result.weather.summary}")
    _section("NOTIFICATIONS", f"[{result.notifications.source}] {result.notifications.summary}")

    _section("PLANT DOCTOR", f"[{result.doctor_source}] priority {advice.priority.upper()} (LED {LED_COLOURS[advice.priority]})")
    _section("", f">> {advice.headline}")
    _section("", advice.message)
    for n, action in enumerate(advice.actions, 1):
        _section("", f"{n}. {action}")
    _section("", f"Why: {advice.reasoning}")
    if result.guardrail_note:
        _section("", f"Guardrail: {result.guardrail_note}")

    print()
    for n, (topic, payload) in enumerate(build_messages(result, topics)):
        body = json.dumps(payload, ensure_ascii=False)
        label = "" if n else "MQTT OUT"
        if len(body) <= 90:
            _section(label, f"{topic}  {body}")
        elif show_json:
            _section(label, topic)
            print(textwrap.indent(json.dumps(payload, indent=2, ensure_ascii=False), " " * LABEL_WIDTH))
        else:
            _section(label, f"{topic}  ({len(body.encode())} bytes)")
    print(f"\nFinished in {result.duration_ms} ms. Use --json to see full payloads, --all for every scenario.")


def _section(label: str, text: str) -> None:
    lines = textwrap.wrap(text, width=100 - LABEL_WIDTH) or [""]
    print(f"{label:<{LABEL_WIDTH}}{lines[0]}")
    for line in lines[1:]:
        print(f"{'':<{LABEL_WIDTH}}{line}")


if __name__ == "__main__":
    main()
