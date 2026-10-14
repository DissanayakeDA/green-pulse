import pytest

from greenpulse_ai import Settings, build_service
from greenpulse_ai.bridge import Bridge
from greenpulse_ai.demo import SimulatedEsp32
from greenpulse_ai.device_state import DeviceStore
from greenpulse_ai.plant_profiles import get_profile
from greenpulse_ai.watering import WateringPolicy

DEVICE = "greenpulse-01"


def make_demo(soil=40.0):
    settings = Settings(offline=True)
    device = SimulatedEsp32(DEVICE, soil=soil)
    device._after = lambda seconds, fn: fn()  # finish pump runs at once
    bridge = Bridge(settings, build_service(settings, None), WateringPolicy.from_settings(settings), client=device)
    return bridge, device


def send_reading(bridge, device):
    device._deliver(device.topics.sensors(DEVICE), device.reading())
    bridge.process_pending()


def pump_states(bridge):
    return [(e["state"], e["source"]) for e in reversed(bridge.store.snapshot(DEVICE)["watering"]["events"])]


def test_readings_go_through_the_bridge_like_mqtt_messages():
    bridge, device = make_demo()
    send_reading(bridge, device)
    snapshot = bridge.store.snapshot(DEVICE)
    assert snapshot["reading"]["soil_moisture"] == pytest.approx(40.0, abs=0.1)
    assert snapshot["analysis"]["trigger"] == "first reading"


def test_water_now_runs_the_simulated_pump_within_the_firmware_limits():
    bridge, device = make_demo()
    bridge.water_now(DEVICE)
    assert pump_states(bridge) == [("on", "manual"), ("off", "manual")]
    assert device.soil == pytest.approx(52.5, abs=0.1)

    bridge.water_now(DEVICE)  # straight away again: the pump must rest first
    events = bridge.store.snapshot(DEVICE)["watering"]["events"]
    assert events[0]["state"] == "rejected" and events[0]["detail"].startswith("pump is resting")


def test_wet_soil_is_refused():
    bridge, device = make_demo(soil=80.0)
    bridge.water_now(DEVICE)
    events = bridge.store.snapshot(DEVICE)["watering"]["events"]
    assert events[0]["detail"] == "soil is already wet (80%)"


def test_dashboard_switch_and_auto_watering_on_dry_soil():
    bridge, device = make_demo(soil=20.0)
    bridge.set_auto_watering(DEVICE, True)
    assert bridge.policy.is_enabled(DEVICE)
    assert bridge.store.snapshot(DEVICE)["watering"]["auto_enabled"]

    send_reading(bridge, device)
    assert pump_states(bridge) == [("on", "auto"), ("off", "auto")]
    assert device.soil == pytest.approx(32.5, abs=0.1)


def test_preloaded_past_day_gives_the_first_analysis_a_trend():
    settings = Settings(offline=True)
    service = build_service(settings, None)
    store = DeviceStore(get_profile("pothos"))
    device = SimulatedEsp32(DEVICE, soil=40.0)
    service.preload(device.backfill(store))
    bridge = Bridge(settings, service, WateringPolicy.from_settings(settings), client=device, store=store)

    send_reading(bridge, device)
    environment = service.last_result(DEVICE).environment
    assert environment.moisture_trend_per_hour < 0
    assert environment.hours_until_dry is not None


def test_backfill_gives_the_dashboard_a_past_day():
    store = DeviceStore(get_profile("pothos"))
    SimulatedEsp32(DEVICE, soil=40.0).backfill(store)

    readings = store.readings(DEVICE, 24)
    assert len(readings) >= 287  # one every 5 minutes
    assert readings[-1].soil_moisture == 40.0
    assert all(10 <= r.soil_moisture <= 70 for r in readings)
    assert any(e.state == "on" for e in store.pump_events(DEVICE))  # the soil got dry and was watered
    assert all(p["soil_moisture"] is not None for p in store.history(DEVICE, 24)["points"])
