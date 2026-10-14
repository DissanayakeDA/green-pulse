"""Outgoing email over SMTP: the alerts, daily summaries and sign-up codes (alerts.py decides what and when).

Sent from the mailbox the Notification Agent reads, EMAIL_ADDRESS, with the same app password.
Zoho: SMTP_HOST=smtppro.zoho.com (smtp.zoho.com for a personal Zoho address). Gmail: smtp.gmail.com.
Port 465 uses SSL; 587 uses STARTTLS.

Every message carries an X-GreenPulse header. The Notification Agent skips messages that have it, so an
alert that lands in the same inbox ("Water the plant now") is never read back as a reminder.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import Settings

HEADER = "X-GreenPulse"


class MailError(Exception):
    """Sending failed. The message says why, in words the dashboard can show."""


def _connect(host: str, port: int, timeout: float) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    smtp = smtplib.SMTP(host, port, timeout=timeout)
    smtp.starttls(context=context)
    return smtp


class Mailer:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender_name: str = "GreenPulse",
        timeout_s: float = 20,
        connect: Callable[[str, int, float], smtplib.SMTP] = _connect,
    ):
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.sender_name = sender_name
        self.timeout_s = timeout_s
        self._connect = connect

    @classmethod
    def from_settings(cls, settings: Settings) -> Mailer | None:
        """None when sending isn't set up (SMTP_HOST, EMAIL_ADDRESS and EMAIL_APP_PASSWORD are all needed)."""
        if not (settings.smtp_host and settings.email_address and settings.email_app_password):
            return None
        return cls(settings.smtp_host, settings.smtp_port, settings.email_address, settings.email_app_password)

    def build(self, to: str, subject: str, text: str, html: str | None = None, kind: str = "alert") -> EmailMessage:
        message = EmailMessage()
        # Zoho and Gmail only relay mail "from" the account that logged in.
        message["From"] = formataddr((self.sender_name, self.username))
        message["To"] = to
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=self.username.rpartition("@")[2] or None)
        message["Auto-Submitted"] = "auto-generated"  # RFC 3834: no out-of-office replies to an alert
        message[HEADER] = kind
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        return message

    def send(self, to: str, subject: str, text: str, html: str | None = None, kind: str = "alert") -> None:
        message = self.build(to, subject, text, html, kind)
        try:
            with self._connect(self.host, self.port, self.timeout_s) as smtp:
                smtp.login(self.username, self._password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError:
            raise MailError(
                f"{self.host} refused the login for {self.username}. Check EMAIL_APP_PASSWORD and that SMTP is allowed for the account."
            ) from None
        except smtplib.SMTPRecipientsRefused:
            raise MailError(f"{self.host} refused to deliver to {to}.") from None
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"Couldn't send through {self.host}:{self.port} ({exc or type(exc).__name__}).") from None
