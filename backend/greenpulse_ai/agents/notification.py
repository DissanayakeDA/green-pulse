"""Notification Agent interface + a stand-in that reads a hardcoded inbox.

The real Notification Agent (Gmail / notification API) is owned by Thashmila P H J. Any class with
a `run() -> NotificationReport` method can replace DummyNotificationAgent in
orchestrator.build_service().
"""

from __future__ import annotations

from typing import Protocol

from ..schemas import NotificationReport, Reminder

# First matching kind wins, so the more specific kinds come before "watering".
KEYWORDS: dict[str, tuple[str, ...]] = {
    "travel": ("trip", "travel", "vacation", "holiday", "flight", "booking confirmed"),
    "fertilising": ("fertilis", "fertiliz", "plant food"),
    "repotting": ("repot",),
    "watering": ("water",),
}


class NotificationAgent(Protocol):
    name: str

    def run(self) -> NotificationReport: ...


class DummyNotificationAgent:
    """Filters a hardcoded list of messages (see dummy_data) for plant-care reminders and plans."""

    name = "notification"

    def __init__(self, messages: list[dict]):
        self.messages = messages

    def run(self) -> NotificationReport:
        reminders = []
        for message in self.messages:
            text = f"{message['subject']} {message['body']}".lower()
            kind = next((k for k, words in KEYWORDS.items() if any(w in text for w in words)), None)
            if kind:
                reminders.append(
                    Reminder(
                        kind=kind,
                        title=message["subject"],
                        detail=message["body"],
                        sender=message["from"],
                        received=message.get("received"),
                    )
                )

        if reminders:
            summary = "Relevant messages: " + "; ".join(f"{r.title} ({r.kind})" for r in reminders) + "."
        else:
            summary = f"No plant-care reminders or travel plans among {len(self.messages)} recent messages."
        return NotificationReport(source="dummy", summary=summary, reminders=reminders)
