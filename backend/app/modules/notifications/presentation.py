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
