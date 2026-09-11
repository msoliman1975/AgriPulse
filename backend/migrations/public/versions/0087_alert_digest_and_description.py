"""Consolidated alert digest, and the description every message was missing.

Two changes, both about what a person reads.

**One message instead of N.** A decision-tree sweep opens one alert per
block. The fan-out sent one message per alert, so a 23-block farm
produced 23 emails whose subjects differed only in the block number —
``Warning · My new tree — 011, Mango Republic``, then 012, then 013.
This seeds ``alert_digest``: one message per farm + tree + leaf +
severity, naming the blocks it covers. The alerts themselves are
untouched and stay one per block, because the Action Center needs a row
per block to close.

**What it is, and why you are seeing it.** Until now an alert email
carried the leaf's one sentence and nothing else. Two things existed and
were shown nowhere:

* ``decision_trees.description_en`` — the tree author's paragraph on what
  the tree looks for. Written in the authoring screen, read by no one.
* the values the walk actually resolved (``signal_snapshot``). Without
  them "Warning" is an assertion. With them it is checkable — and in the
  case that prompted this, the honest reading was "NDVI mean: no data",
  which is the whole reason the tree fired.

So version 3 of the two single-finding email templates adds a "Why this
tree ran" and a "What we measured" section, and the digest carries the
same two under the same names. Version 2 stays on disk: the loader reads
``ORDER BY version DESC LIMIT 1``, so a rollback is a delete of these
rows and nothing re-renders.

Both sections arrive as **pre-built markup** (``why_block_html``,
``evidence_block_html``) rather than as bare values. The renderer is a
flat substituter with no conditionals, so a template that hard-coded the
heading above ``{{rule_description}}`` would print "WHY THIS TREE RAN"
over an empty space for every tree whose author left the field blank.
The builder in ``notifications/presentation.py`` returns the heading and
its body together, or the empty string.

Revision ID: 0087
Revises: 0086
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087"
down_revision: str | Sequence[str] | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


# =========================================================================
# Version 3 of the single-finding emails — same card, two sections added.
# =========================================================================

# One variable, not one per section. The builder in
# ``notifications/presentation.py`` concatenates only the sections that
# have a body, so an absent section leaves neither a heading nor a blank
# line behind. A template placing each section separately could not do
# that — the renderer has no conditionals — and would print two empty
# lines for a tree whose author wrote no description and whose walk
# resolved nothing.
_ADDED_HTML = "{{extra_blocks_html}}"
_ADDED_TEXT = "{{extra_blocks_text}}"

# The callout is separate because it stays last: it is the line a person
# acts on. It is conditional for the same reason as the rest. Tree-sourced
# alerts carry no prescription — the leaf writes a diagnosis and nothing
# else — so the hard-coded "WHAT TO DO" in version 2 has been printing
# above blank space on every alert this platform has sent.
_ACTION_HTML = "{{action_block_html}}"
_ACTION_TEXT = "{{action_block_text}}"

ALERT_EN_HTML = _shell(
    rtl=False,
    eyebrow="Alert",
    headline="{{rule_name}}",
    location="Block <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row("Detected", "{{fired_at_display}}", rtl=False),
            _row("Severity", "{{severity_label}}", rtl=False, value_color="{{severity_color}}"),
            _row("Decision tree", "{{rule_name}}", rtl=False),
            _row("Block", "{{block_code}}", rtl=False),
            _row("Farm", "{{farm_name}}", rtl=False, last=True),
        ]
    ),
    blocks=(_plain_block("What we see", "{{diagnosis}}", rtl=False) + _ADDED_HTML + _ACTION_HTML),
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

ALERT_EN_SUBJECT = "{{severity_label}} \u00b7 {{rule_name}} \u2014 {{block_code}}, {{farm_name}}"

ALERT_EN_TEXT = (
    "{{severity_label}} alert on block {{block_code}}, {{farm_name}}.\n\n"
    "Detected:      {{fired_at_display}}\n"
    "Severity:      {{severity_label}}\n"
    "Decision tree: {{rule_name}}\n"
    "Block:         {{block_code}}\n"
    "Farm:          {{farm_name}}\n\n"
    "WHAT WE SEE\n{{diagnosis}}\n\n"
    + _ADDED_TEXT
    + _ACTION_TEXT
    + "Open this alert:\n{{link_url_abs}}\n\n"
    "--\n"
    "You are getting this because you have access to {{farm_name}} in\n"
    "AgriPulse and email is on in your notification channels.\n"
    "Change your notifications: {{preferences_url}}\n"
    "AgriPulse - admin@agripulse.tech. Replies are not read.\n"
)

ALERT_AR_HTML = _shell(
    rtl=True,
    eyebrow="\u062a\u0646\u0628\u064a\u0647",
    headline="{{rule_name}}",
    location="\u0627\u0644\u062d\u0642\u0644 <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row(
                "\u0648\u0642\u062a \u0627\u0644\u0631\u0635\u062f",
                "{{fired_at_display}}",
                rtl=True,
            ),
            _row(
                "\u0627\u0644\u062e\u0637\u0648\u0631\u0629",
                "{{severity_label}}",
                rtl=True,
                value_color="{{severity_color}}",
            ),
            _row(
                "\u0634\u062c\u0631\u0629 \u0627\u0644\u0642\u0631\u0627\u0631",
                "{{rule_name}}",
                rtl=True,
            ),
            _row("\u0627\u0644\u062d\u0642\u0644", "{{block_code}}", rtl=True),
            _row(
                "\u0627\u0644\u0645\u0632\u0631\u0639\u0629", "{{farm_name}}", rtl=True, last=True
            ),
        ]
    ),
    blocks=(
        _plain_block("\u0645\u0627 \u0646\u0631\u0627\u0647", "{{diagnosis}}", rtl=True)
        + _ADDED_HTML
        + _ACTION_HTML
    ),
    button_label="\u0627\u0641\u062a\u062d \u0627\u0644\u062a\u0646\u0628\u064a\u0647",
    paste_label="\u0623\u0648 \u0627\u0644\u0635\u0642 \u0647\u0630\u0627 \u0627\u0644\u0631\u0627\u0628\u0637 \u0641\u064a \u0627\u0644\u0645\u062a\u0635\u0641\u062d:",
    footer_why=(
        "\u0648\u0635\u0644\u062a\u0643 \u0647\u0630\u0647 \u0627\u0644\u0631\u0633\u0627\u0644\u0629 \u0644\u0623\u0646 \u0644\u062f\u064a\u0643 \u0635\u0644\u0627\u062d\u064a\u0629 \u0639\u0644\u0649 "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> \u0641\u064a AgriPulse\u060c '
        "\u0648\u0627\u0644\u0628\u0631\u064a\u062f \u0645\u0641\u0639\u0651\u0644 \u0636\u0645\u0646 \u0642\u0646\u0648\u0627\u062a \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0644\u062f\u064a\u0643."
    ),
    footer_link="\u063a\u064a\u0651\u0631 \u0625\u0634\u0639\u0627\u0631\u0627\u062a\u0643",
    footer_sig="\u0631\u0633\u0627\u0644\u0629 \u0622\u0644\u064a\u0629. \u0644\u0627 \u062a\u062a\u0645 \u0642\u0631\u0627\u0621\u0629 \u0627\u0644\u0631\u062f\u0648\u062f.",
).replace("{{diagnosis_or_text}}", "{{diagnosis}}")

ALERT_AR_SUBJECT = (
    "{{severity_label}} \u00b7 {{rule_name}} \u2014 {{block_code}}\u060c {{farm_name}}"
)

ALERT_AR_TEXT = (
    "\u062a\u0646\u0628\u064a\u0647 {{severity_label}} \u0639\u0644\u0649 \u0627\u0644\u062d\u0642\u0644 {{block_code}}\u060c {{farm_name}}.\n\n"
    "\u0648\u0642\u062a \u0627\u0644\u0631\u0635\u062f: {{fired_at_display}}\n"
    "\u0627\u0644\u062e\u0637\u0648\u0631\u0629: {{severity_label}}\n"
    "\u0634\u062c\u0631\u0629 \u0627\u0644\u0642\u0631\u0627\u0631: {{rule_name}}\n"
    "\u0627\u0644\u062d\u0642\u0644: {{block_code}}\n"
    "\u0627\u0644\u0645\u0632\u0631\u0639\u0629: {{farm_name}}\n\n"
    "\u0645\u0627 \u0646\u0631\u0627\u0647\n{{diagnosis}}\n\n"
    + _ADDED_TEXT
    + _ACTION_TEXT
    + "\u0627\u0641\u062a\u062d \u0627\u0644\u062a\u0646\u0628\u064a\u0647:\n{{link_url_abs}}\n\n"
    "--\n"
    "\u0648\u0635\u0644\u062a\u0643 \u0647\u0630\u0647 \u0627\u0644\u0631\u0633\u0627\u0644\u0629 \u0644\u0623\u0646 \u0644\u062f\u064a\u0643 \u0635\u0644\u0627\u062d\u064a\u0629 \u0639\u0644\u0649 {{farm_name}} \u0641\u064a AgriPulse.\n"
    "\u063a\u064a\u0651\u0631 \u0625\u0634\u0639\u0627\u0631\u0627\u062a\u0643: {{preferences_url}}\n"
)

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
    blocks=_ADDED_HTML + _callout("Recommended", "{{text}}", rtl=False),
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

REC_EN_SUBJECT = "{{severity_label}} \u00b7 {{tree_name}} \u2014 {{block_code}}, {{farm_name}}"

REC_EN_TEXT = (
    "{{severity_label}} recommendation on block {{block_code}}, {{farm_name}}.\n\n"
    "Raised:        {{fired_at_display}}\n"
    "Severity:      {{severity_label}}\n"
    "Decision tree: {{tree_name}}\n"
    "Action:        {{action_type_label}}\n"
    "Block:         {{block_code}}\n"
    "Farm:          {{farm_name}}\n\n" + _ADDED_TEXT + "RECOMMENDED\n{{text}}\n\n"
    "Open this recommendation:\n{{link_url_abs}}\n\n"
    "--\n"
    "You are getting this because you have access to {{farm_name}} in\n"
    "AgriPulse and email is on in your notification channels.\n"
    "Change your notifications: {{preferences_url}}\n"
    "AgriPulse - admin@agripulse.tech. Replies are not read.\n"
)

REC_AR_HTML = _shell(
    rtl=True,
    eyebrow="\u062a\u0648\u0635\u064a\u0629",
    headline="{{tree_name}}",
    location="\u0627\u0644\u062d\u0642\u0644 <strong>{{block_code}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row(
                "\u062a\u0627\u0631\u064a\u062e \u0627\u0644\u0625\u0635\u062f\u0627\u0631",
                "{{fired_at_display}}",
                rtl=True,
            ),
            _row(
                "\u0627\u0644\u062e\u0637\u0648\u0631\u0629",
                "{{severity_label}}",
                rtl=True,
                value_color="{{severity_color}}",
            ),
            _row(
                "\u0634\u062c\u0631\u0629 \u0627\u0644\u0642\u0631\u0627\u0631",
                "{{tree_name}}",
                rtl=True,
            ),
            _row("\u0627\u0644\u0625\u062c\u0631\u0627\u0621", "{{action_type_label}}", rtl=True),
            _row("\u0627\u0644\u062d\u0642\u0644", "{{block_code}}", rtl=True),
            _row(
                "\u0627\u0644\u0645\u0632\u0631\u0639\u0629", "{{farm_name}}", rtl=True, last=True
            ),
        ]
    ),
    blocks=_ADDED_HTML
    + _callout("\u0627\u0644\u062a\u0648\u0635\u064a\u0629", "{{text}}", rtl=True),
    button_label="\u0627\u0641\u062a\u062d \u0627\u0644\u062a\u0648\u0635\u064a\u0629",
    paste_label="\u0623\u0648 \u0627\u0644\u0635\u0642 \u0647\u0630\u0627 \u0627\u0644\u0631\u0627\u0628\u0637 \u0641\u064a \u0627\u0644\u0645\u062a\u0635\u0641\u062d:",
    footer_why=(
        "\u0648\u0635\u0644\u062a\u0643 \u0647\u0630\u0647 \u0627\u0644\u0631\u0633\u0627\u0644\u0629 \u0644\u0623\u0646 \u0644\u062f\u064a\u0643 \u0635\u0644\u0627\u062d\u064a\u0629 \u0639\u0644\u0649 "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> \u0641\u064a AgriPulse\u060c '
        "\u0648\u0627\u0644\u0628\u0631\u064a\u062f \u0645\u0641\u0639\u0651\u0644 \u0636\u0645\u0646 \u0642\u0646\u0648\u0627\u062a \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0644\u062f\u064a\u0643."
    ),
    footer_link="\u063a\u064a\u0651\u0631 \u0625\u0634\u0639\u0627\u0631\u0627\u062a\u0643",
    footer_sig="\u0631\u0633\u0627\u0644\u0629 \u0622\u0644\u064a\u0629. \u0644\u0627 \u062a\u062a\u0645 \u0642\u0631\u0627\u0621\u0629 \u0627\u0644\u0631\u062f\u0648\u062f.",
).replace("{{diagnosis_or_text}}", "{{text}}")

REC_AR_SUBJECT = "{{severity_label}} \u00b7 {{tree_name}} \u2014 {{block_code}}\u060c {{farm_name}}"

REC_AR_TEXT = (
    "\u062a\u0648\u0635\u064a\u0629 {{severity_label}} \u0639\u0644\u0649 \u0627\u0644\u062d\u0642\u0644 {{block_code}}\u060c {{farm_name}}.\n\n"
    "\u062a\u0627\u0631\u064a\u062e \u0627\u0644\u0625\u0635\u062f\u0627\u0631: {{fired_at_display}}\n"
    "\u0627\u0644\u062e\u0637\u0648\u0631\u0629: {{severity_label}}\n"
    "\u0634\u062c\u0631\u0629 \u0627\u0644\u0642\u0631\u0627\u0631: {{tree_name}}\n"
    "\u0627\u0644\u0625\u062c\u0631\u0627\u0621: {{action_type_label}}\n"
    "\u0627\u0644\u062d\u0642\u0644: {{block_code}}\n"
    "\u0627\u0644\u0645\u0632\u0631\u0639\u0629: {{farm_name}}\n\n"
    + _ADDED_TEXT
    + "\u0627\u0644\u062a\u0648\u0635\u064a\u0629\n{{text}}\n\n"
    "\u0627\u0641\u062a\u062d \u0627\u0644\u062a\u0648\u0635\u064a\u0629:\n{{link_url_abs}}\n\n"
    "--\n"
    "\u0648\u0635\u0644\u062a\u0643 \u0647\u0630\u0647 \u0627\u0644\u0631\u0633\u0627\u0644\u0629 \u0644\u0623\u0646 \u0644\u062f\u064a\u0643 \u0635\u0644\u0627\u062d\u064a\u0629 \u0639\u0644\u0649 {{farm_name}} \u0641\u064a AgriPulse.\n"
    "\u063a\u064a\u0651\u0631 \u0625\u0634\u0639\u0627\u0631\u0627\u062a\u0643: {{preferences_url}}\n"
)


# =========================================================================
# The digest itself.
#
# Same card, three differences that matter:
#   * the location line counts blocks instead of naming one;
#   * a "Blocks" fact row carries the full list, so the reader never has
#     to open the app to learn which ones;
#   * the button opens the farm's alert queue rather than one alert,
#     because one alert is not what this message is about.
# =========================================================================

DIGEST_EN_HTML = _shell(
    rtl=False,
    eyebrow="Alert digest",
    headline="{{rule_name}}",
    location="<strong>{{block_count_label}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row("Detected", "{{fired_at_display}}", rtl=False),
            _row("Severity", "{{severity_label}}", rtl=False, value_color="{{severity_color}}"),
            _row("Decision tree", "{{rule_name}}", rtl=False),
            _row("Blocks", "{{block_list_full}}", rtl=False),
            _row("Farm", "{{farm_name}}", rtl=False, last=True),
        ]
    ),
    blocks=(
        _plain_block(
            "What we see",
            "The same finding on {{block_count_label}}: {{verdict}}",
            rtl=False,
        )
        + _ADDED_HTML
        + _callout(
            "What to do",
            "Open the alert queue for {{farm_name}} to review and close these together.",
            rtl=False,
        )
    ),
    button_label="Open the alert queue",
    paste_label="Or paste this into your browser:",
    footer_why=(
        "You are getting one message instead of {{block_count}} because these blocks "
        "raised the same finding in the same run. You get it at all because you have "
        'access to <strong style="color:#2e4a3d;">{{farm_name}}</strong> in AgriPulse '
        "and email is on in your notification channels."
    ),
    footer_link="Change which notifications you get",
    footer_sig="Sent by an automated system. Replies are not read.",
).replace("{{diagnosis_or_text}}", "{{verdict}}")

DIGEST_EN_SUBJECT = (
    "{{severity_label}} \u00b7 {{rule_name}} \u2014 {{block_count_label}}, {{farm_name}}"
)

DIGEST_EN_TEXT = (
    "{{severity_label}}: the same finding on {{block_count_label}} of {{farm_name}}.\n\n"
    "Detected:      {{fired_at_display}}\n"
    "Severity:      {{severity_label}}\n"
    "Decision tree: {{rule_name}}\n"
    "Blocks:        {{block_list_full}}\n"
    "Farm:          {{farm_name}}\n\n"
    "WHAT WE SEE\n{{verdict}}\n\n" + _ADDED_TEXT + "WHAT TO DO\n"
    "Open the alert queue for {{farm_name}} to review and close these together.\n"
    "{{link_url_abs}}\n\n"
    "--\n"
    "You are getting one message instead of {{block_count}} because these blocks\n"
    "raised the same finding in the same run. You get it at all because you have\n"
    "access to {{farm_name}} in AgriPulse and email is on in your notification\n"
    "channels.\n"
    "Change your notifications: {{preferences_url}}\n"
    "AgriPulse - admin@agripulse.tech. Replies are not read.\n"
)

DIGEST_AR_HTML = _shell(
    rtl=True,
    eyebrow="\u062a\u0646\u0628\u064a\u0647\u0627\u062a \u0645\u062c\u0645\u0651\u0639\u0629",
    headline="{{rule_name}}",
    location="<strong>{{block_count_label}}</strong> &middot; {{farm_name}}",
    facts="".join(
        [
            _row(
                "\u0648\u0642\u062a \u0627\u0644\u0631\u0635\u062f",
                "{{fired_at_display}}",
                rtl=True,
            ),
            _row(
                "\u0627\u0644\u062e\u0637\u0648\u0631\u0629",
                "{{severity_label}}",
                rtl=True,
                value_color="{{severity_color}}",
            ),
            _row(
                "\u0634\u062c\u0631\u0629 \u0627\u0644\u0642\u0631\u0627\u0631",
                "{{rule_name}}",
                rtl=True,
            ),
            _row("\u0627\u0644\u0642\u0637\u0639", "{{block_list_full}}", rtl=True),
            _row(
                "\u0627\u0644\u0645\u0632\u0631\u0639\u0629", "{{farm_name}}", rtl=True, last=True
            ),
        ]
    ),
    blocks=(
        _plain_block(
            "\u0645\u0627 \u0646\u0631\u0627\u0647",
            "\u0646\u0641\u0633 \u0627\u0644\u0646\u062a\u064a\u062c\u0629 \u0639\u0644\u0649 {{block_count_label}}: {{verdict}}",
            rtl=True,
        )
        + _ADDED_HTML
        + _callout(
            "\u0627\u0644\u0625\u062c\u0631\u0627\u0621 \u0627\u0644\u0645\u0637\u0644\u0648\u0628",
            "\u0627\u0641\u062a\u062d \u0642\u0627\u0626\u0645\u0629 \u062a\u0646\u0628\u064a\u0647\u0627\u062a {{farm_name}} \u0644\u0645\u0631\u0627\u062c\u0639\u062a\u0647\u0627 \u0648\u0625\u063a\u0644\u0627\u0642\u0647\u0627 \u0645\u0639\u064b\u0627.",
            rtl=True,
        )
    ),
    button_label="\u0627\u0641\u062a\u062d \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u062a\u0646\u0628\u064a\u0647\u0627\u062a",
    paste_label="\u0623\u0648 \u0627\u0644\u0635\u0642 \u0647\u0630\u0627 \u0627\u0644\u0631\u0627\u0628\u0637 \u0641\u064a \u0627\u0644\u0645\u062a\u0635\u0641\u062d:",
    footer_why=(
        "\u0648\u0635\u0644\u062a\u0643 \u0631\u0633\u0627\u0644\u0629 \u0648\u0627\u062d\u062f\u0629 \u0628\u062f\u0644 {{block_count}} \u0644\u0623\u0646 \u0647\u0630\u0647 \u0627\u0644\u0642\u0637\u0639 \u0623\u0638\u0647\u0631\u062a \u0646\u0641\u0633 \u0627\u0644\u0646\u062a\u064a\u062c\u0629 \u0641\u064a \u0646\u0641\u0633 \u0627\u0644\u062a\u0634\u063a\u064a\u0644\u0629\u060c "
        "\u0648\u0644\u0623\u0646 \u0644\u062f\u064a\u0643 \u0635\u0644\u0627\u062d\u064a\u0629 \u0639\u0644\u0649 "
        '<strong style="color:#2e4a3d;">{{farm_name}}</strong> \u0641\u064a AgriPulse\u060c '
        "\u0648\u0627\u0644\u0628\u0631\u064a\u062f \u0645\u0641\u0639\u0651\u0644 \u0636\u0645\u0646 \u0642\u0646\u0648\u0627\u062a \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0644\u062f\u064a\u0643."
    ),
    footer_link="\u063a\u064a\u0651\u0631 \u0625\u0634\u0639\u0627\u0631\u0627\u062a\u0643",
    footer_sig="\u0631\u0633\u0627\u0644\u0629 \u0622\u0644\u064a\u0629. \u0644\u0627 \u062a\u062a\u0645 \u0642\u0631\u0627\u0621\u0629 \u0627\u0644\u0631\u062f\u0648\u062f.",
).replace("{{diagnosis_or_text}}", "{{verdict}}")

DIGEST_AR_SUBJECT = (
    "{{severity_label}} \u00b7 {{rule_name}} \u2014 {{block_count_label}}\u060c {{farm_name}}"
)

DIGEST_AR_TEXT = (
    "{{severity_label}}: \u0646\u0641\u0633 \u0627\u0644\u0646\u062a\u064a\u062c\u0629 \u0639\u0644\u0649 {{block_count_label}} \u0645\u0646 {{farm_name}}.\n\n"
    "\u0648\u0642\u062a \u0627\u0644\u0631\u0635\u062f: {{fired_at_display}}\n"
    "\u0627\u0644\u062e\u0637\u0648\u0631\u0629: {{severity_label}}\n"
    "\u0634\u062c\u0631\u0629 \u0627\u0644\u0642\u0631\u0627\u0631: {{rule_name}}\n"
    "\u0627\u0644\u0642\u0637\u0639: {{block_list_full}}\n"
    "\u0627\u0644\u0645\u0632\u0631\u0639\u0629: {{farm_name}}\n\n"
    "\u0645\u0627 \u0646\u0631\u0627\u0647\n{{verdict}}\n\n"
    + _ADDED_TEXT
    + "\u0627\u0644\u0625\u062c\u0631\u0627\u0621 \u0627\u0644\u0645\u0637\u0644\u0648\u0628\n"
    "\u0627\u0641\u062a\u062d \u0642\u0627\u0626\u0645\u0629 \u062a\u0646\u0628\u064a\u0647\u0627\u062a {{farm_name}} \u0644\u0645\u0631\u0627\u062c\u0639\u062a\u0647\u0627 \u0648\u0625\u063a\u0644\u0627\u0642\u0647\u0627 \u0645\u0639\u064b\u0627.\n"
    "{{link_url_abs}}\n\n"
    "--\n"
    "\u0648\u0635\u0644\u062a\u0643 \u0631\u0633\u0627\u0644\u0629 \u0648\u0627\u062d\u062f\u0629 \u0628\u062f\u0644 {{block_count}} \u0644\u0623\u0646 \u0647\u0630\u0647 \u0627\u0644\u0642\u0637\u0639 \u0623\u0638\u0647\u0631\u062a \u0646\u0641\u0633 \u0627\u0644\u0646\u062a\u064a\u062c\u0629.\n"
    "\u063a\u064a\u0651\u0631 \u0625\u0634\u0639\u0627\u0631\u0627\u062a\u0643: {{preferences_url}}\n"
)


# (template_code, locale, channel, version, subject, body, body_html)
_ROWS: tuple[tuple[str, str, str, int, str, str, str | None], ...] = (
    # -- version 3 of the single-finding emails ---------------------------
    ("alert_opened", "en", "email", 3, ALERT_EN_SUBJECT, ALERT_EN_TEXT, ALERT_EN_HTML),
    ("alert_opened", "ar", "email", 3, ALERT_AR_SUBJECT, ALERT_AR_TEXT, ALERT_AR_HTML),
    ("recommendation_opened", "en", "email", 3, REC_EN_SUBJECT, REC_EN_TEXT, REC_EN_HTML),
    ("recommendation_opened", "ar", "email", 3, REC_AR_SUBJECT, REC_AR_TEXT, REC_AR_HTML),
    # -- the digest, all three per-user channels --------------------------
    ("alert_digest", "en", "email", 1, DIGEST_EN_SUBJECT, DIGEST_EN_TEXT, DIGEST_EN_HTML),
    ("alert_digest", "ar", "email", 1, DIGEST_AR_SUBJECT, DIGEST_AR_TEXT, DIGEST_AR_HTML),
    # The bell shows a title and one line. The line says how many blocks
    # and what the finding was — the two things that decide whether the
    # reader clicks now or later.
    (
        "alert_digest",
        "en",
        "in_app",
        1,
        "{{severity_label}} \u00b7 {{rule_name}} \u2014 {{block_count_label}}",
        "{{farm_name}}: {{verdict}} \u2014 {{block_list}}",
        None,
    ),
    (
        "alert_digest",
        "ar",
        "in_app",
        1,
        "{{severity_label}} \u00b7 {{rule_name}} \u2014 {{block_count_label}}",
        "{{farm_name}}: {{verdict}} \u2014 {{block_list}}",
        None,
    ),
    # Push is read in one glance, possibly in sunlight, by somebody
    # deciding whether to walk to a field. So the title leads with where
    # and how many, and the body is the finding, not a restated title.
    (
        "alert_digest",
        "en",
        "push",
        1,
        "{{farm_name}} \u2014 {{block_count_label}}",
        "{{severity_label}}: {{verdict}}",
        None,
    ),
    (
        "alert_digest",
        "ar",
        "push",
        1,
        "{{farm_name}} \u2014 {{block_count_label}}",
        "{{severity_label}}: {{verdict}}",
        None,
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for code, locale, channel, version, subject, body, body_html in _ROWS:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.notification_templates
                       (template_code, locale, channel, version,
                        subject, body, body_html)
                SELECT :code, :locale, :channel, :version, :subject, :body, :body_html
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.notification_templates
                     WHERE template_code = :code AND locale = :locale
                       AND channel = :channel AND version = :version
                 )
                """
            ),
            {
                "code": code,
                "locale": locale,
                "channel": channel,
                "version": version,
                "subject": subject,
                "body": body,
                "body_html": body_html,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Version 3 goes; version 2 is still on disk and the loader's
    # ORDER BY version DESC picks it up again with no other change.
    bind.execute(
        sa.text(
            "DELETE FROM public.notification_templates "
            "WHERE channel = 'email' AND version = 3 "
            "AND template_code IN ('alert_opened', 'recommendation_opened')"
        )
    )
    # The digest has no earlier version to fall back to. Without a row the
    # fan-out records status='failed', error='template not found' rather
    # than sending anything, which is the intended state after a rollback:
    # the code that would have consolidated is rolled back with it.
    bind.execute(
        sa.text("DELETE FROM public.notification_templates WHERE template_code = 'alert_digest'")
    )
