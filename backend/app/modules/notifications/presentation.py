"""Presentation values the notification templates render.

Everything here exists because the template renderer is a flat
``{{ var }}`` substituter with no conditionals and no filters (see
``templates.py``). A template cannot ask "if severity is critical, paint
the rail red" or "format this timestamp", so the answer has to arrive in
the render context already decided. That is what this module decides.

Three things were wrong before and are fixed here:

* ``severity_label`` was English for both locales, so an Arabic reader
  got ``CRITICAL`` inside an Arabic sentence, on every channel.
* ``action_type`` rendered as its raw enum code (``fertilize``) in a
  field where the reader expects a label.
* ``fired_at`` rendered as a full ISO timestamp with microseconds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.settings import get_settings

DEFAULT_LOCALE = "en"

# ``severity`` is the alerts/recommendations enum: info | warning | critical.
_SEVERITY_LABELS: dict[str, dict[str, str]] = {
    "en": {"info": "Info", "warning": "Warning", "critical": "Critical"},
    "ar": {"info": "معلومة", "warning": "تحذير", "critical": "حرِج"},
}

# (text, background, border) per severity. Text carries the meaning; the
# background and border only support it. Apple Mail and Outlook.com invert
# a light email in dark mode on their own and no markup stops them, so no
# value here is white-on-colour — an inversion still leaves it readable.
_SEVERITY_COLOURS: dict[str, tuple[str, str, str]] = {
    "info": ("#0f6e56", "#e3f0ea", "#bcd8cb"),
    "warning": ("#9c690e", "#f6efdf", "#e0cfa6"),
    "critical": ("#b23a38", "#f6e6e5", "#e3c2c1"),
}
_SEVERITY_FALLBACK = ("#0f2a1f", "#f7f6f1", "#e3e0d6")

# The `recommendations.action_type` CHECK enum, from tenant migration 0015.
_ACTION_TYPE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "irrigate": "Irrigate",
        "fertilize": "Fertilize",
        "spray": "Spray",
        "scout": "Scout",
        "harvest_window": "Harvest window",
        "prune": "Prune",
        "no_action": "No action",
        "other": "Other",
    },
    "ar": {
        "irrigate": "ري",
        "fertilize": "تسميد",
        "spray": "رش",
        "scout": "فحص",
        "harvest_window": "نافذة الحصاد",
        "prune": "تقليم",
        "no_action": "لا إجراء",
        "other": "أخرى",
    },
}

_MONTHS: dict[str, tuple[str, ...]] = {
    "en": (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ),
    "ar": (
        "يناير",
        "فبراير",
        "مارس",
        "أبريل",
        "مايو",
        "يونيو",
        "يوليو",
        "أغسطس",
        "سبتمبر",
        "أكتوبر",
        "نوفمبر",
        "ديسمبر",
    ),
}


def _table(source: dict[str, dict[str, str]], locale: str) -> dict[str, str]:
    return source.get(locale) or source[DEFAULT_LOCALE]


def severity_label(severity: str, locale: str) -> str:
    """Localized severity word. Unknown severities render as themselves."""
    return _table(_SEVERITY_LABELS, locale).get(severity, severity)


def severity_colours(severity: str) -> tuple[str, str, str]:
    """``(text, background, border)`` hex triple for the severity rail."""
    return _SEVERITY_COLOURS.get(severity, _SEVERITY_FALLBACK)


def action_type_label(action_type: str, locale: str) -> str:
    """Localized label for a recommendation's action. Unknown codes render
    as themselves so a new enum value degrades to the code, not to blank."""
    return _table(_ACTION_TYPE_LABELS, locale).get(action_type, action_type)


def format_timestamp(value: datetime | None, locale: str) -> str:
    """``20 Aug 2026, 14:32 UTC`` — or the Arabic equivalent.

    Always rendered in UTC and always labelled UTC. A farm's people can be
    in more than one offset and the platform stores no per-user timezone,
    so an unlabelled local-looking time would be a guess presented as fact.
    """
    if value is None:
        return ""
    moment = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    month = _MONTHS.get(locale, _MONTHS[DEFAULT_LOCALE])[moment.month - 1]
    clock = f"{moment.hour:02d}:{moment.minute:02d}"
    if locale == "ar":
        return f"{moment.day} {month} {moment.year}، {clock} بتوقيت UTC"
    return f"{moment.day} {month} {moment.year}, {clock} UTC"


def absolute_url(path: str) -> str:
    """Prefix an in-app path with the configured web origin.

    The in-app bell hands ``link_url`` straight to react-router's
    ``navigate()``, which reads an absolute URL as a path and produces
    ``/https://...``. So the relative form stays the canonical one and
    only the email channel is given this absolute twin.
    """
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"


def preferences_url() -> str:
    """Where the footer's "change your notifications" link points.

    `/account/notifications`, not `/settings/notifications`. The Settings hub
    is tenant-wide configuration and every tab there is capability-gated, so
    most recipients of this email cannot open it — a Scout or an Agronomist
    would follow the link and be refused. This route is the caller's own row
    and carries no gate.
    """
    return absolute_url("/account/notifications")


# --- optional titled blocks -------------------------------------------------
# The renderer has no conditionals (templates.py), so a section that is
# present only sometimes cannot be expressed in the template: a template
# that hard-codes "WHY THIS TREE RAN" above {{rule_description}} prints
# the heading over nothing whenever the author left the description
# empty, which reads as a bug rather than as an absence. So the heading
# and its content are built together here, and the template places one
# variable that is either the whole section or the empty string.

_BLOCK_INK_SOFT = "#2e4a3d"
_BLOCK_MUTED = "#5e7669"


def titled_block_html(title: str, body_html: str, *, rtl: bool) -> str:
    """A titled section of an email body, or "" when there is no body.

    ``body_html`` must already be markup — either escaped text or a table
    this codebase built. Nothing here escapes it.
    """
    if not body_html:
        return ""
    align = ' align="right"' if rtl else ""
    title_style = f"margin:0 0 7px 0;font-size:12px;color:{_BLOCK_MUTED};font-weight:700;"
    if not rtl:
        title_style = (
            f"margin:0 0 7px 0;font-size:11px;letter-spacing:1.3px;"
            f"text-transform:uppercase;color:{_BLOCK_MUTED};font-weight:700;"
        )
    return (
        f'<tr><td{align} style="padding:26px 36px 0 36px;">'
        f'<p style="{title_style}">{title}</p>'
        f"{body_html}</td></tr>"
    )


def titled_paragraph_html(title: str, body_text: str, *, rtl: bool) -> str:
    """:func:`titled_block_html` whose body is one escaped paragraph."""
    if not body_text:
        return ""
    from html import escape as _escape

    leading = "1.8" if rtl else "1.62"
    para = (
        f'<p style="margin:0;font-size:15px;line-height:{leading};'
        f'color:{_BLOCK_INK_SOFT};">{_escape(body_text)}</p>'
    )
    return titled_block_html(title, para, rtl=rtl)


def titled_block_text(title: str, body: str) -> str:
    """The plain-text twin: a heading and its body, or "" when empty."""
    if not body:
        return ""
    return f"{title}\n{body}\n"


_CALLOUT_BRAND = "#0f6e56"
_CALLOUT_TINT = "#f7f6f1"


def callout_html(title: str, body_text: str | None, *, rtl: bool) -> str:
    """The tinted block that carries the sentence a person has to act on.

    Same markup as the one migration 0070 built, reproduced here so the
    conditional version and the frozen one look identical. Returns "" for
    an empty body: a tree-sourced alert has no prescription, and its
    heading over blank space is what this exists to stop.
    """
    if not body_text:
        return ""
    from html import escape as _escape

    side = "border-right" if rtl else "border-left"
    align = ' align="right"' if rtl else ""
    leading = "1.8" if rtl else "1.62"
    title_style = f"margin:0 0 7px 0;font-size:12px;color:{_CALLOUT_BRAND};font-weight:700;"
    if not rtl:
        title_style = (
            f"margin:0 0 7px 0;font-size:11px;letter-spacing:1.3px;"
            f"text-transform:uppercase;color:{_CALLOUT_BRAND};font-weight:700;"
        )
    return (
        f'<tr><td style="padding:22px 36px 0 36px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        f' style="background-color:{_CALLOUT_TINT};{side}:3px solid {_CALLOUT_BRAND};">'
        f'<tr><td{align} style="padding:16px 18px;">'
        f'<p style="{title_style}">{title}</p>'
        f'<p style="margin:0;font-size:15px;line-height:{leading};color:{_BLOCK_INK_SOFT};">'
        f"{_escape(body_text)}</p>"
        f"</td></tr></table></td></tr>"
    )
