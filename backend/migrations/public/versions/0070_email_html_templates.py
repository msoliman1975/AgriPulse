"""HTML email bodies for alert_opened and recommendation_opened (en + ar).

Until now every email row carried ``body_html = NULL``, so the platform
sent plain text only. This inserts **version 2** rows for the four email
templates. Version 1 stays on disk: the loader reads
``ORDER BY version DESC LIMIT 1``, so an alert that already fired keeps
the wording it fired with, and a rollback is a delete of these rows.

Shape of the design, and why:

* 600 px, tables, inline styles, no ``<style>`` block. Outlook on Windows
  renders with Word — that is the floor.
* No images. Most clients block remote images by default, and a brand
  that disappears when images are off is not a brand. The wordmark is
  letter-spaced text.
* A 5 px severity rail is the only colour that changes between messages.
  It is the one thing readable at thumbnail size.
* A preheader ``<div>`` — hidden in the body, shown by the client next to
  the subject in the inbox list. Without it the client shows whatever the
  first markup happens to be.
* Facts before prose. Most readers only want to know which block, and how
  bad, before deciding whether to keep reading.
* One button (a ``bgcolor`` table cell, which every client renders) with
  the same URL repeated in plain text underneath for the clients that
  strip it.

New variables this markup needs, all added in
``notifications/presentation.py`` and wired through the two
``_build_render_ctx*`` functions — no schema change:
``severity_color``, ``severity_bg``, ``severity_border``,
``fired_at_display``, ``action_type_label``, ``preferences_url``, and
``link_url_abs`` (``link_url`` stays relative for the in-app bell, which
hands it to react-router).

Revision ID: 0070
Revises: 0069
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | Sequence[str] | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- palette (the login theme's own values, not new ones) -------------------
INK = "#0f2a1f"
INK_SOFT = "#2e4a3d"
MUTED = "#5e7669"
FAINT = "#8a9489"
LINE = "#e3e0d6"
LINE_SOFT = "#f0eee7"
TINT = "#f7f6f1"
BRAND = "#0f6e56"

LATIN_FONT = "-apple-system,'Segoe UI',Roboto,Arial,sans-serif"
# Tahoma first: it is the Arabic face actually installed on Windows and
# inside Outlook. Web fonts are not used — half the clients drop them.
ARABIC_FONT = "Tahoma,'Segoe UI',Arial,sans-serif"


def _row(label: str, value: str, *, rtl: bool, value_color: str = INK, last: bool = False) -> str:
    """One line of the fact table."""
    align = ' align="right"' if rtl else ""
    edge = LINE if last else LINE_SOFT
    label_style = f"padding:10px 0;border-bottom:1px solid {edge};font-size:12px;color:{MUTED};"
    if not rtl:
        label_style += "letter-spacing:.7px;text-transform:uppercase;"
    return (
        f"<tr>"
        f'<td width="132"{align} style="{label_style}">{label}</td>'
        f'<td{align} style="padding:10px 0;border-bottom:1px solid {edge};'
        f'font-size:14px;color:{value_color};">{value}</td>'
        f"</tr>"
    )


def _callout(title: str, body: str, *, rtl: bool) -> str:
    """The tinted block that carries the sentence a person has to act on."""
    side = "border-right" if rtl else "border-left"
    align = ' align="right"' if rtl else ""
    leading = "1.8" if rtl else "1.62"
    title_style = f"margin:0 0 7px 0;font-size:12px;color:{BRAND};font-weight:700;"
    if not rtl:
        title_style = (
            f"margin:0 0 7px 0;font-size:11px;letter-spacing:1.3px;"
            f"text-transform:uppercase;color:{BRAND};font-weight:700;"
        )
    return (
        f'<tr><td style="padding:22px 36px 0 36px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        f' style="background-color:{TINT};{side}:3px solid {BRAND};">'
        f'<tr><td{align} style="padding:16px 18px;">'
        f'<p style="{title_style}">{title}</p>'
        f'<p style="margin:0;font-size:15px;line-height:{leading};color:{INK_SOFT};">{body}</p>'
        f"</td></tr></table></td></tr>"
    )


def _plain_block(title: str, body: str, *, rtl: bool) -> str:
    """An untinted titled paragraph — used for "what we see"."""
    align = ' align="right"' if rtl else ""
    leading = "1.8" if rtl else "1.62"
    title_style = f"margin:0 0 7px 0;font-size:12px;color:{MUTED};font-weight:700;"
    if not rtl:
        title_style = (
            f"margin:0 0 7px 0;font-size:11px;letter-spacing:1.3px;"
            f"text-transform:uppercase;color:{MUTED};font-weight:700;"
        )
    return (
        f'<tr><td{align} style="padding:26px 36px 0 36px;">'
        f'<p style="{title_style}">{title}</p>'
        f'<p style="margin:0;font-size:15px;line-height:{leading};color:{INK_SOFT};">{body}</p>'
        f"</td></tr>"
    )


def _shell(
    *,
    rtl: bool,
    eyebrow: str,
    headline: str,
    location: str,
    facts: str,
    blocks: str,
    button_label: str,
    paste_label: str,
    footer_why: str,
    footer_link: str,
    footer_sig: str,
) -> str:
    font = ARABIC_FONT if rtl else LATIN_FONT
    align = ' align="right"' if rtl else ""
    dir_attr = ' dir="rtl"' if rtl else ""
    dir_style = "direction:rtl;text-align:right;" if rtl else ""
    align_tbl = ' align="right"' if rtl else ""
    head_leading = "1.45" if rtl else "1.28"
    foot_leading = "1.8" if rtl else "1.6"
    # The wordmark keeps the Latin stack in both directions. It is a mark,
    # not a word to be read in the surrounding language.
    eyebrow_style = f"font-size:12px;color:{MUTED};"
    if not rtl:
        eyebrow_style = (
            f"font-size:11px;letter-spacing:1.4px;color:{MUTED};text-transform:uppercase;"
        )

    return "".join(
        [
            # A real document, not a fragment. `add_alternative` sends this
            # string as the whole HTML part; clients tolerate a bare fragment
            # but the wrapper is what lets us paint the ground behind the
            # 600 px card and stop iOS inflating small text.
            f'<!DOCTYPE html><html{dir_attr}><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "</head>"
            f'<body style="margin:0;padding:0;background-color:#eceae2;'
            f'-webkit-text-size-adjust:100%;{dir_style}">',
            # Preheader. Hidden in the body, shown in the inbox list.
            '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
            'font-size:1px;line-height:1px;color:#eceae2;">{{diagnosis_or_text}}</div>',
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            ' style="background-color:#eceae2;"><tr>'
            '<td align="center" style="padding:24px 12px;">',
            f'<table{dir_attr} role="presentation" width="600" cellpadding="0" cellspacing="0"'
            f' border="0" style="width:600px;max-width:600px;background-color:#ffffff;'
            f'font-family:{font};color:{INK};{dir_style}">',
            # severity rail
            '<tr><td style="height:5px;background-color:{{severity_color}};'
            'line-height:5px;font-size:0;">&nbsp;</td></tr>',
            # wordmark + eyebrow
            '<tr><td style="padding:26px 36px 0 36px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            "<tr>"
            f'<td{align} style="font-size:14px;font-weight:700;letter-spacing:2.4px;'
            f'color:{BRAND};font-family:{LATIN_FONT};">AGRIPULSE</td>'
            f'<td align="{"left" if rtl else "right"}" style="{eyebrow_style}">{eyebrow}</td>'
            "</tr></table></td></tr>",
            # severity pill
            f'<tr><td{align} style="padding:22px 36px 0 36px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"{align_tbl}>'
            '<tr><td style="background-color:{{severity_bg}};'
            "border:1px solid {{severity_border}};border-radius:2px;padding:4px 10px;"
            "font-size:12px;font-weight:700;color:{{severity_color}};"
            + ("" if rtl else "letter-spacing:1.2px;text-transform:uppercase;")
            + '">{{severity_label}}</td></tr></table></td></tr>',
            # headline + location
            f'<tr><td{align} style="padding:14px 36px 0 36px;">'
            f'<h1 style="margin:0;font-size:22px;line-height:{head_leading};font-weight:600;'
            f'color:{INK};">{headline}</h1>'
            f'<p style="margin:8px 0 0 0;font-size:15px;color:{INK_SOFT};">{location}</p>'
            "</td></tr>",
            # facts
            '<tr><td style="padding:24px 36px 0 36px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="border-top:1px solid {LINE};">{facts}</table></td></tr>',
            blocks,
            # button + paste fallback
            f'<tr><td{align} style="padding:28px 36px 0 36px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"{align_tbl}>'
            f'<tr><td bgcolor="{BRAND}" style="border-radius:3px;">'
            '<a href="{{link_url_abs}}" style="display:inline-block;padding:13px 26px;'
            f"font-family:{font};font-size:15px;font-weight:600;color:#ffffff;"
            f'text-decoration:none;">{button_label}</a>'
            "</td></tr></table>"
            f'<p style="margin:12px 0 0 0;font-size:12px;line-height:1.6;color:{MUTED};">'
            f"{paste_label}<br>"
            f'<span dir="ltr" style="color:{BRAND};word-break:break-all;">{{{{link_url_abs}}}}'
            "</span></p></td></tr>",
            # footer
            '<tr><td style="padding:30px 36px 30px 36px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td{align} style="border-top:1px solid {LINE};padding-top:16px;">'
            f'<p style="margin:0 0 6px 0;font-size:12px;line-height:{foot_leading};'
            f'color:{MUTED};">{footer_why}</p>'
            f'<p style="margin:0 0 12px 0;font-size:12px;line-height:{foot_leading};">'
            f'<a href="{{{{preferences_url}}}}" style="color:{BRAND};">{footer_link}</a></p>'
            f'<p style="margin:0;font-size:11px;line-height:{foot_leading};color:{FAINT};">'
            f"AgriPulse &middot; admin@agripulse.tech<br>{footer_sig}</p>"
            "</td></tr></table></td></tr>",
            "</table>",
            "</td></tr></table></body></html>",
        ]
    )


# --- alert, English ---------------------------------------------------------
ALERT_EN_HTML = _shell(
    rtl=False,
    eyebrow="Alert",
    headline="{{rule_name}}",
    location="Block <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row("Detected", "{{fired_at_display}}", rtl=False),
            _row("Severity", "{{severity_label}}", rtl=False, value_color="{{severity_color}}"),
            _row("Rule", "{{rule_name}}", rtl=False),
            _row("Block", "{{block_code}}", rtl=False),
            _row("Farm", "{{farm_name}}", rtl=False, last=True),
        ]
    ),
    blocks=(
        _plain_block("What we see", "{{diagnosis}}", rtl=False)
        + _callout("What to do", "{{prescription}}", rtl=False)
    ),
    button_label="Open this alert",
    paste_label="Or paste this into your browser:",
    footer_why=(
        "You are getting this because you have access to "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> in AgriPulse '
        "and email is on in your notification channels."
    ),
    footer_link="Change which notifications you get",
    footer_sig="Sent by an automated system. Replies are not read.",
).replace("{{diagnosis_or_text}}", "{{diagnosis}}")

ALERT_EN_SUBJECT = "{{severity_label}} · {{rule_name}} — {{block_code}}, {{farm_name}}"

ALERT_EN_TEXT = (
    "{{severity_label}} alert on block {{block_code}}, {{farm_name}}.\n\n"
    "Detected: {{fired_at_display}}\n"
    "Severity: {{severity_label}}\n"
    "Rule:     {{rule_name}}\n"
    "Block:    {{block_code}}\n"
    "Farm:     {{farm_name}}\n\n"
    "WHAT WE SEE\n{{diagnosis}}\n\n"
    "WHAT TO DO\n{{prescription}}\n\n"
    "Open this alert:\n{{link_url_abs}}\n\n"
    "--\n"
    "You are getting this because you have access to {{farm_name}} in\n"
    "AgriPulse and email is on in your notification channels.\n"
    "Change your notifications: {{preferences_url}}\n"
    "AgriPulse - admin@agripulse.tech. Replies are not read.\n"
)

# --- alert, Arabic ----------------------------------------------------------
ALERT_AR_HTML = _shell(
    rtl=True,
    eyebrow="تنبيه",
    headline="{{rule_name}}",
    location="الحقل <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row("وقت الرصد", "{{fired_at_display}}", rtl=True),
            _row("الخطورة", "{{severity_label}}", rtl=True, value_color="{{severity_color}}"),
            _row("القاعدة", "{{rule_name}}", rtl=True),
            _row("الحقل", "{{block_code}}", rtl=True),
            _row("المزرعة", "{{farm_name}}", rtl=True, last=True),
        ]
    ),
    blocks=(
        _plain_block("ما الذي رصدناه", "{{diagnosis}}", rtl=True)
        + _callout("الإجراء المقترح", "{{prescription}}", rtl=True)
    ),
    button_label="افتح التنبيه",
    paste_label="أو انسخ هذا الرابط في المتصفح:",
    footer_why=(
        "وصلتك هذه الرسالة لأن لديك صلاحية على "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> في AgriPulse، '
        "والبريد مفعّل ضمن قنوات الإشعار لديك."
    ),
    footer_link="غيّر إشعاراتك",
    footer_sig="رسالة آلية. لا تتم قراءة الردود.",
).replace("{{diagnosis_or_text}}", "{{diagnosis}}")

ALERT_AR_SUBJECT = "{{severity_label}} · {{rule_name}} — {{block_code}}، {{farm_name}}"

ALERT_AR_TEXT = (
    "تنبيه {{severity_label}} على الحقل {{block_code}}، {{farm_name}}.\n\n"
    "وقت الرصد: {{fired_at_display}}\n"
    "الخطورة: {{severity_label}}\n"
    "القاعدة: {{rule_name}}\n"
    "الحقل: {{block_code}}\n"
    "المزرعة: {{farm_name}}\n\n"
    "ما الذي رصدناه\n{{diagnosis}}\n\n"
    "الإجراء المقترح\n{{prescription}}\n\n"
    "افتح التنبيه:\n{{link_url_abs}}\n\n"
    "--\n"
    "وصلتك هذه الرسالة لأن لديك صلاحية على {{farm_name}} في AgriPulse.\n"
    "غيّر إشعاراتك: {{preferences_url}}\n"
)

# --- recommendation, English ------------------------------------------------
REC_EN_HTML = _shell(
    rtl=False,
    eyebrow="Recommendation",
    headline="{{tree_name}}",
    location="Block <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row("Raised", "{{fired_at_display}}", rtl=False),
            _row("Severity", "{{severity_label}}", rtl=False, value_color="{{severity_color}}"),
            _row("Decision tree", "{{tree_name}}", rtl=False),
            _row("Action", "{{action_type_label}}", rtl=False),
            _row("Block", "{{block_code}}", rtl=False),
            _row("Farm", "{{farm_name}}", rtl=False, last=True),
        ]
    ),
    blocks=_callout("Recommended", "{{text}}", rtl=False),
    button_label="Open this recommendation",
    paste_label="Or paste this into your browser:",
    footer_why=(
        "You are getting this because you have access to "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> in AgriPulse '
        "and email is on in your notification channels."
    ),
    footer_link="Change which notifications you get",
    footer_sig="Sent by an automated system. Replies are not read.",
).replace("{{diagnosis_or_text}}", "{{text}}")

REC_EN_SUBJECT = "{{severity_label}} · {{tree_name}} — {{block_code}}, {{farm_name}}"

REC_EN_TEXT = (
    "{{severity_label}} recommendation on block {{block_code}}, {{farm_name}}.\n\n"
    "Raised:        {{fired_at_display}}\n"
    "Severity:      {{severity_label}}\n"
    "Decision tree: {{tree_name}}\n"
    "Action:        {{action_type_label}}\n"
    "Block:         {{block_code}}\n"
    "Farm:          {{farm_name}}\n\n"
    "RECOMMENDED\n{{text}}\n\n"
    "Open this recommendation:\n{{link_url_abs}}\n\n"
    "--\n"
    "You are getting this because you have access to {{farm_name}} in\n"
    "AgriPulse and email is on in your notification channels.\n"
    "Change your notifications: {{preferences_url}}\n"
    "AgriPulse - admin@agripulse.tech. Replies are not read.\n"
)

# --- recommendation, Arabic -------------------------------------------------
REC_AR_HTML = _shell(
    rtl=True,
    eyebrow="توصية",
    headline="{{tree_name}}",
    location="الحقل <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row("تاريخ الإصدار", "{{fired_at_display}}", rtl=True),
            _row("الخطورة", "{{severity_label}}", rtl=True, value_color="{{severity_color}}"),
            _row("شجرة القرار", "{{tree_name}}", rtl=True),
            _row("الإجراء", "{{action_type_label}}", rtl=True),
            _row("الحقل", "{{block_code}}", rtl=True),
            _row("المزرعة", "{{farm_name}}", rtl=True, last=True),
        ]
    ),
    blocks=_callout("التوصية", "{{text}}", rtl=True),
    button_label="افتح التوصية",
    paste_label="أو انسخ هذا الرابط في المتصفح:",
    footer_why=(
        "وصلتك هذه الرسالة لأن لديك صلاحية على "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> في AgriPulse، '
        "والبريد مفعّل ضمن قنوات الإشعار لديك."
    ),
    footer_link="غيّر إشعاراتك",
    footer_sig="رسالة آلية. لا تتم قراءة الردود.",
).replace("{{diagnosis_or_text}}", "{{text}}")

REC_AR_SUBJECT = "{{severity_label}} · {{tree_name}} — {{block_code}}، {{farm_name}}"

REC_AR_TEXT = (
    "توصية {{severity_label}} على الحقل {{block_code}}، {{farm_name}}.\n\n"
    "تاريخ الإصدار: {{fired_at_display}}\n"
    "الخطورة: {{severity_label}}\n"
    "شجرة القرار: {{tree_name}}\n"
    "الإجراء: {{action_type_label}}\n"
    "الحقل: {{block_code}}\n"
    "المزرعة: {{farm_name}}\n\n"
    "التوصية\n{{text}}\n\n"
    "افتح التوصية:\n{{link_url_abs}}\n\n"
    "--\n"
    "وصلتك هذه الرسالة لأن لديك صلاحية على {{farm_name}} في AgriPulse.\n"
    "غيّر إشعاراتك: {{preferences_url}}\n"
)


_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    # (template_code, locale, subject, body, body_html)
    ("alert_opened", "en", ALERT_EN_SUBJECT, ALERT_EN_TEXT, ALERT_EN_HTML),
    ("alert_opened", "ar", ALERT_AR_SUBJECT, ALERT_AR_TEXT, ALERT_AR_HTML),
    ("recommendation_opened", "en", REC_EN_SUBJECT, REC_EN_TEXT, REC_EN_HTML),
    ("recommendation_opened", "ar", REC_AR_SUBJECT, REC_AR_TEXT, REC_AR_HTML),
)

_VERSION = 2


def upgrade() -> None:
    bind = op.get_bind()
    for code, locale, subject, body, body_html in _ROWS:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.notification_templates
                       (template_code, locale, channel, version,
                        subject, body, body_html)
                SELECT :code, :locale, 'email', :version, :subject, :body, :body_html
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.notification_templates
                     WHERE template_code = :code AND locale = :locale
                       AND channel = 'email' AND version = :version
                 )
                """
            ),
            {
                "code": code,
                "locale": locale,
                "version": _VERSION,
                "subject": subject,
                "body": body,
                "body_html": body_html,
            },
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM public.notification_templates "
            "WHERE channel = 'email' AND version = :version "
            "AND template_code IN ('alert_opened', 'recommendation_opened')"
        ),
        {"version": _VERSION},
    )
