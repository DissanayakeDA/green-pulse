"""The text of every email GreenPulse sends. Each function returns (subject, plain text, HTML).

Advice text comes from the LLM, and readings and reminder titles from outside, so everything is escaped
before it goes into the HTML.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from html import escape

from .schemas import CareResult
from .watering import WateringDecision

Email = tuple[str, str, str]

# The same words and LED colours as the dashboard (dashboard/src/lib/format.ts).
PRIORITY = {
    "low": ("All good", "#16a34a"),
    "medium": ("Act today", "#f2a516"),
    "high": ("Act within 2 hours", "#ec835a"),
    "critical": ("Act now", "#d03b3b"),
}
METRICS = (("soil_moisture", "Soil moisture"), ("temperature", "Temperature"), ("humidity", "Air humidity"))
STATE_WORDS = {
    "too_low": "far too low",
    "low": "a bit low",
    "optimal": "ideal",
    "high": "a bit high",
    "too_high": "far too high",
    "sensor_error": "no reading",
}
GREY = "#5b6b61"


def alert_email(
    result: CareResult,
    decision: WateringDecision | None,
    kind: str,
    to: str,
    tz: tzinfo,
    dashboard_url: str | None = None,
) -> Email:
    """kind: "new" (just reached high/critical), "worse" (e.g. high -> critical) or "still" (a reminder)."""
    advice = result.advice
    label, color = PRIORITY[advice.priority]
    plant = result.environment.plant
    where = f"{plant} ({result.device_id})"
    lead = {
        "new": f"{where} needs attention.",
        "worse": f"It has got worse: {where} is now at “{label}”.",
        "still": f"Reminder: {where} still needs attention.",
    }[kind]
    subject = f"{'Reminder: ' if kind == 'still' else ''}{label}: {advice.headline} - {plant}"
    readings = _readings({key: status.model_dump() for key, status in result.environment.metrics.items()})
    watering = _watering_line(decision)
    checked = f"Checked {_when(result.generated_at, tz)}."

    text = "\n".join(
        [
            lead,
            "",
            f"{label.upper()}: {advice.headline}",
            advice.message,
            "",
            *(f"{i}. {action}" for i, action in enumerate(advice.actions, 1)),
            "",
            *(f"{name}: {value} ({state}; ideal {ideal})" for name, value, ideal, state in readings),
            *([watering] if watering else []),
            checked,
            *_link_text(dashboard_url),
            "",
            _footer(to, dashboard_url),
        ]
    )
    body = (
        f"<p style='margin:0 0 16px'>{escape(lead)}</p>"
        + _banner(label, color, advice.headline)
        + f"<p style='margin:16px 0'>{escape(advice.message)}</p>"
        + "<ol style='margin:0 0 16px;padding-left:20px'>"
        + "".join(f"<li style='margin:4px 0'>{escape(action)}</li>" for action in advice.actions)
        + "</ol>"
        + _readings_table(readings)
        + (f"<p style='margin:12px 0 0'>{escape(watering)}</p>" if watering else "")
        + f"<p style='margin:12px 0 0;color:{GREY}'>{escape(checked)}</p>"
    )
    return subject, text, _page(body, to, dashboard_url)


def offline_email(device_id: str, plant: str, last_seen: datetime, to: str, tz: tzinfo, dashboard_url: str | None = None) -> Email:
    subject = f"Device offline - {device_id} has stopped reporting"
    lines = [
        f"{device_id} ({plant}) hasn't sent a reading since {_when(last_seen, tz)}.",
        "Check that it has power and Wi-Fi. While it's offline, GreenPulse can't watch the plant or water it.",
    ]
    text = "\n".join([*lines, *_link_text(dashboard_url), "", _footer(to, dashboard_url)])
    body = _banner("Device offline", PRIORITY["high"][1], f"{device_id} has stopped reporting") + "".join(
        f"<p style='margin:16px 0 0'>{escape(line)}</p>" for line in lines
    )
    return subject, text, _page(body, to, dashboard_url)


def daily_email(devices: list[dict], day: datetime, to: str, dashboard_url: str | None = None) -> Email:
    """devices: DeviceStore.snapshot() dicts, each with an added "waterings" list (pump runs, last 24 h)."""
    subject = f"GreenPulse daily summary - {day.day} {day:%b}"
    text_parts: list[str] = [f"Your plants on {day.day} {day:%B}:"]
    html_parts: list[str] = [f"<p style='margin:0 0 16px'>Your plants on {day.day} {day:%B}:</p>"]
    if not devices:
        text_parts.append("No device has reported since the server started.")
        html_parts.append("<p>No device has reported since the server started.</p>")
    for device in devices:
        text, html = _device_summary(device)
        text_parts.append(text)
        html_parts.append(html)
    text = "\n\n".join(text_parts) + "\n" + "\n".join(_link_text(dashboard_url)) + "\n\n" + _footer(to, dashboard_url)
    return subject, text, _page("".join(html_parts), to, dashboard_url)


def code_email(code: str, minutes: int) -> Email:
    subject = f"{code} is your GreenPulse code"
    lines = [
        f"Enter {code} on the GreenPulse dashboard's Email alerts page to start getting plant alerts at this address.",
        f"The code expires in {minutes} minutes.",
        "If you didn't ask for this, ignore this email. Nothing else will be sent to you.",
    ]
    body = (
        "<p style='margin:0 0 16px'>Your GreenPulse code is</p>"
        f"<p style='margin:0 0 16px;font-size:32px;font-weight:700;letter-spacing:6px'>{code}</p>"
        + "".join(f"<p style='margin:0 0 12px'>{escape(line)}</p>" for line in lines)
    )
    return subject, "\n\n".join(lines), _page(body)


def sample_email(to: str, gets: list[str], dashboard_url: str | None = None) -> Email:
    subject = "GreenPulse test email"
    lines = [
        "This is a test from GreenPulse. Email reaches this address.",
        "You get: " + ("; ".join(gets) if gets else "nothing at the moment (both kinds are switched off)") + ".",
    ]
    text = "\n\n".join(lines) + "\n\n" + _footer(to, dashboard_url)
    body = "".join(f"<p style='margin:0 0 12px'>{escape(line)}</p>" for line in lines)
    return subject, text, _page(body, to, dashboard_url)


# --------------------------------------------------------------------------- pieces


def _device_summary(device: dict) -> tuple[str, str]:
    name = f"{device['plant']['name']} ({device['device_id']})"
    status = "online" if device["online"] else "offline"
    analysis = device.get("analysis")
    if analysis:
        label, color = PRIORITY[analysis["priority"]]
        verdict = f"{label}: {analysis['headline']}"
    else:
        color, verdict = GREY, "Not analysed yet"
    readings = _readings(device.get("metrics") or {})
    runs = device.get("waterings", [])
    automatic = sum(1 for run in runs if run["source"] == "auto")
    watered = (
        f"Watered {len(runs)} time{'s' if len(runs) != 1 else ''} in the last 24 h "
        f"({automatic} automatic, {len(runs) - automatic} manual)."
        if runs
        else "Not watered in the last 24 h."
    )
    reminders = (analysis or {}).get("notifications", {}).get("reminders", [])
    inbox = "From your inbox: " + "; ".join(f"{r['title']} ({r['kind']})" for r in reminders) + "." if reminders else ""

    text = "\n".join(
        [
            f"{name} - {status}",
            verdict,
            *(f"  {label_}: {value} ({state})" for label_, value, _, state in readings),
            watered,
            *([inbox] if inbox else []),
        ]
    )
    html = (
        f"<div style='margin:0 0 20px;padding:12px 16px;border:1px solid #e3e9e5;border-left:6px solid {color};border-radius:8px'>"
        f"<p style='margin:0;font-weight:600'>{escape(name)} <span style='font-weight:400;color:{GREY}'>· {status}</span></p>"
        f"<p style='margin:4px 0 8px'>{escape(verdict)}</p>"
        + _readings_table(readings)
        + f"<p style='margin:8px 0 0'>{escape(watered)}</p>"
        + (f"<p style='margin:8px 0 0'>{escape(inbox)}</p>" if inbox else "")
        + "</div>"
    )
    return text, html


def _readings(metrics: dict[str, dict]) -> list[tuple[str, str, str, str]]:
    """(label, value, ideal range, state) for each metric present."""
    rows = []
    for key, label in METRICS:
        status = metrics.get(key)
        if not status:
            continue
        unit = status["unit"]
        sep = "" if unit == "%" else " "
        value = "--" if status["value"] is None else f"{status['value']:.0f}{sep}{unit}"
        ideal = f"{status['ideal_min']:g}-{status['ideal_max']:g}{sep}{unit}"
        rows.append((label, value, ideal, STATE_WORDS.get(status["state"], status["state"])))
    return rows


def _readings_table(rows: list[tuple[str, str, str, str]]) -> str:
    if not rows:
        return ""
    cells = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:{GREY}'>{escape(label)}</td>"
        f"<td style='padding:4px 12px 4px 0;font-weight:600'>{escape(value)}</td>"
        f"<td style='padding:4px 0;color:{GREY}'>{escape(state)} · ideal {escape(ideal)}</td></tr>"
        for label, value, ideal, state in rows
    )
    return f"<table style='border-collapse:collapse;font-size:14px'>{cells}</table>"


def _watering_line(decision: WateringDecision | None) -> str:
    if decision is None:
        return ""
    if decision.water:
        return f"Auto-watering: watering now ({decision.duration_s:g} s pulse). {decision.reason}."
    return f"Auto-watering: not watering. {decision.reason}."


def _banner(label: str, color: str, headline: str) -> str:
    return (
        f"<div style='border-left:6px solid {color};background:#f6f8f7;border-radius:8px;padding:12px 16px'>"
        f"<p style='margin:0;font-size:12px;font-weight:600;color:{color};text-transform:uppercase;letter-spacing:.05em'>{escape(label)}</p>"
        f"<p style='margin:4px 0 0;font-size:20px;font-weight:700'>{escape(headline)}</p></div>"
    )


def _page(body: str, to: str | None = None, dashboard_url: str | None = None) -> str:
    link = (
        f"<p style='margin:20px 0 0'><a href='{escape(dashboard_url)}' style='color:#1f8a4c;font-weight:600'>Open the dashboard</a></p>"
        if dashboard_url
        else ""
    )
    footer = f"<p style='margin:24px 0 0;font-size:12px;color:{GREY}'>{escape(_footer(to, dashboard_url))}</p>" if to else ""
    return (
        "<div style='font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#16271d;max-width:560px'>"
        f"<p style='margin:0 0 16px;font-weight:700;color:#1f8a4c'>GreenPulse</p>{body}{link}{footer}</div>"
    )


def _footer(to: str | None, dashboard_url: str | None) -> str:
    where = f" ({dashboard_url}/alerts)" if dashboard_url else ""
    return (
        f"You get this because {to} is on the GreenPulse email list. "
        f"To change or stop these emails, open Email alerts on the dashboard{where}."
    )


def _link_text(dashboard_url: str | None) -> list[str]:
    return [f"Dashboard: {dashboard_url}"] if dashboard_url else []


def _when(moment: datetime, tz: tzinfo) -> str:
    local = moment.astimezone(tz)
    return f"{local.day} {local:%b}, {local:%H:%M}"
