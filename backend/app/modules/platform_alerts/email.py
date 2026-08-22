"""Mail the platform operator when the sweep finds something new.

The red bar and `/platform/alerts` both need somebody to be looking at a
browser. The failure this whole module exists to stop was four days of
nobody looking, so the alerts have to be able to reach a person who is not.

One digest per sweep, not one mail per alert
--------------------------------------------
A broken tenant migration opens a finding per farm. Mailing each one turns
a single bug into forty messages that arrive together, which is how an
operator learns to filter the sender. The digest carries the count and the
worst items, and `platform_alert_email_max_items` caps it.

Sent once, unless it gets worse
-------------------------------
The sweep re-detects the same problem every 10 minutes. `notified_at` on
the alert row is what stops the digest repeating; `notified_severity` is
what lets a warning that becomes critical mail a second time. See public
migration 0070.

Failure is not fatal
--------------------
`notify` returns counts and swallows nothing: if SMTP raises, the rows stay
unstamped and the next sweep tries again. The caller runs it after its own
writes have committed, so a mail relay being down cannot cost us the alert
records themselves.
"""

from __future__ import annotations

import asyncio
from html import escape
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.notifications.presentation import absolute_url, severity_colours
from app.modules.notifications.smtp import send_email
from app.modules.platform_alerts.repository import PlatformAlertsRepository

_log = get_logger(__name__)


def _line(row: dict[str, Any]) -> str:
    """One alert as a plain-text line: severity, where, what."""
    where = row.get("tenant_name") or row.get("tenant_slug") or "platform"
    farm = row.get("farm_name")
    if farm:
        where = f"{where} / {farm}"
    severity = str(row.get("severity", "")).upper()
    parts = [f"[{severity}] {where} - {row.get('title', '')}"]
    detail = row.get("detail")
    if detail:
        parts.append(f"    {str(detail)[:400]}")
    return "\n".join(parts)


def build_digest(rows: list[dict[str, Any]], *, dropped: int) -> tuple[str, str]:
    """Return `(subject, body_text)` for a list of new or escalated alerts.

    Pure, so the wording can be tested without an SMTP server.
    """
    criticals = [r for r in rows if r.get("severity") == "critical"]
    warnings = [r for r in rows if r.get("severity") != "critical"]

    if criticals and warnings:
        subject = f"AgriPulse platform: {len(criticals)} critical, {len(warnings)} warning"
    elif criticals:
        subject = f"AgriPulse platform: {len(criticals)} critical"
    else:
        subject = f"AgriPulse platform: {len(warnings)} warning"

    body: list[str] = [
        "New or worsened platform alerts.",
        "",
    ]
    for row in criticals + warnings:
        body.append(_line(row))
        body.append("")

    if dropped:
        body.append(
            f"{dropped} more alert(s) are not listed here. They are marked as "
            "sent, so this mail will not repeat for them."
        )
        body.append("")

    body.append(f"Full list: {absolute_url('/platform/alerts')}")
    body.append("")
    body.append(
        "You receive this because your platform admin record has alert " "emails switched on."
    )
    return subject, "\n".join(body)


def _where(row: dict[str, Any]) -> str:
    where = row.get("tenant_name") or row.get("tenant_slug") or "platform"
    farm = row.get("farm_name")
    return f"{where} / {farm}" if farm else str(where)


def build_digest_html(rows: list[dict[str, Any]], *, dropped: int) -> str:
    """HTML twin of `build_digest`'s body.

    Same constraints as the notification templates added alongside this:
    600 px, tables, inline styles, no images, no `<style>` block, because
    Outlook on Windows renders with Word. The only colour that changes
    between rows is the severity rail, which is the one thing readable at
    thumbnail size. Colours come from `notifications.presentation` so the
    operator's mail and a grower's mail agree on what critical looks like.
    """
    ordered = [r for r in rows if r.get("severity") == "critical"] + [
        r for r in rows if r.get("severity") != "critical"
    ]

    items: list[str] = []
    for row in ordered:
        text_colour, background, border = severity_colours(str(row.get("severity", "")))
        detail = str(row.get("detail") or "")[:400]
        items.append(
            f'<tr><td style="padding:0 0 12px 0;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="background:{background};border:1px solid {border};">'
            f"<tr>"
            f'<td width="5" style="background:{text_colour};font-size:0;line-height:0;">&nbsp;</td>'
            f'<td style="padding:10px 12px;font-family:Arial,Helvetica,sans-serif;">'
            f'<div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;'
            f'color:{text_colour};">{escape(str(row.get("severity", "")))}</div>'
            f'<div style="font-size:15px;font-weight:bold;color:#111827;padding-top:2px;">'
            f'{escape(str(row.get("title", "")))}</div>'
            f'<div style="font-size:12px;color:#6b7280;padding-top:2px;">'
            f"{escape(_where(row))}</div>"
            + (
                f'<div style="font-size:12px;color:#374151;padding-top:6px;">'
                f"{escape(detail)}</div>"
                if detail
                else ""
            )
            + "</td></tr></table></td></tr>"
        )

    dropped_html = (
        f'<p style="font-size:12px;color:#6b7280;margin:0 0 16px 0;">{dropped} more alert(s) '
        f"are not listed here. They are marked as sent, so this mail will not repeat "
        f"for them.</p>"
        if dropped
        else ""
    )
    link = absolute_url("/platform/alerts")

    return f"""<div style="display:none;max-height:0;overflow:hidden;">{len(ordered)} new or worsened platform alert(s).</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#f3f4f6;padding:24px 0;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           style="width:600px;max-width:600px;background:#ffffff;">
      <tr><td style="padding:20px 24px 8px 24px;font-family:Arial,Helvetica,sans-serif;">
        <div style="font-size:13px;letter-spacing:.18em;color:#6b7280;">AGRIPULSE</div>
        <h1 style="font-size:19px;color:#111827;margin:8px 0 0 0;">Platform alerts</h1>
        <p style="font-size:13px;color:#6b7280;margin:4px 0 0 0;">
          New or worsened since the last digest.</p>
      </td></tr>
      <tr><td style="padding:16px 24px 0 24px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          {"".join(items)}
        </table>
        {dropped_html}
      </td></tr>
      <tr><td style="padding:0 24px 8px 24px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
          <tr><td bgcolor="#166534" style="padding:10px 18px;">
            <a href="{link}" style="font-family:Arial,Helvetica,sans-serif;font-size:14px;
               color:#ffffff;text-decoration:none;font-weight:bold;">Open the alerts page</a>
          </td></tr>
        </table>
      </td></tr>
      <tr><td style="padding:8px 24px 20px 24px;font-family:Arial,Helvetica,sans-serif;">
        <p style="font-size:11px;color:#9ca3af;margin:0;">{link}</p>
        <p style="font-size:11px;color:#9ca3af;margin:8px 0 0 0;">
          You receive this because your platform admin record has alert emails
          switched on.</p>
      </td></tr>
    </table>
  </td></tr>
</table>"""


async def notify(repo: PlatformAlertsRepository) -> dict[str, int]:
    """Mail the digest for anything new, then stamp what was sent.

    The repository's session must already be inside a transaction the
    caller commits; this function does not commit.
    """
    settings = get_settings()
    if not settings.platform_alert_email_enabled:
        return {"recipients": 0, "alerts": 0, "sent": 0}

    recipients = await repo.list_email_recipients()
    if not recipients:
        # Nobody has ticked the box. Do not stamp the rows: the day somebody
        # does, they should receive what is currently broken rather than
        # only what breaks next.
        return {"recipients": 0, "alerts": 0, "sent": 0}

    cap = settings.platform_alert_email_max_items
    # Read one past the cap so the digest can say how many it left out
    # without a second count query.
    candidates = await repo.list_unnotified(limit=cap + 1)
    if not candidates:
        return {"recipients": len(recipients), "alerts": 0, "sent": 0}

    listed = candidates[:cap]
    dropped = len(candidates) - len(listed)
    subject, body = build_digest(listed, dropped=dropped)
    body_html = build_digest_html(listed, dropped=dropped)

    sent = 0
    for person in recipients:
        address = person["email"]
        try:
            # smtplib is synchronous and this runs on the API's event loop
            # when an operator forces a sweep from the page. A relay that
            # takes its full timeout would otherwise stall every other
            # request in that worker.
            await asyncio.to_thread(
                send_email,
                to_address=address,
                subject=subject,
                body_text=body,
                body_html=body_html,
            )
            sent += 1
        except Exception:
            # One bad address must not stop the others, and must not stop
            # the stamping below: a digest that reached three of four
            # operators has been delivered.
            _log.warning("platform_alert_email_failed", to=address, exc_info=True)

    if sent:
        await repo.mark_notified(alert_ids=[row["id"] for row in candidates])

    result = {"recipients": len(recipients), "alerts": len(candidates), "sent": sent}
    _log.info("platform_alert_email_digest", **result)
    return result
