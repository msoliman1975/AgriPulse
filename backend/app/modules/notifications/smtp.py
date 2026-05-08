"""Synchronous SMTP send used by the notifications email channel.

The notifications subscriber runs in a sync handler (see
``subscribers.py``), so a synchronous client (``smtplib``) is the
right fit — async would require spinning up an event loop locally for
no benefit. Sends are best-effort with a hard timeout; failures bubble
to the caller, which records them on the ``notification_dispatches``
row.

For dev (MailHog) we don't authenticate or use TLS. Production envs
override ``smtp_username`` / ``smtp_password`` / ``smtp_starttls`` via
ExternalSecrets; the ``settings.*`` reads pick them up automatically.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.settings import get_settings


class SmtpSendError(RuntimeError):
    """Raised when SMTP delivery fails. The caller stores the message
    on the dispatch row so an operator can read it later.
    """


def send_email(
    *,
    to_address: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> None:
    """Send a single email through the configured SMTP server.

    Raises ``SmtpSendError`` on connection / send failure. Returns
    silently on success.
    """
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(
            host=settings.smtp_host,
            port=settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as client:
            if settings.smtp_starttls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise SmtpSendError(str(exc)) from exc
