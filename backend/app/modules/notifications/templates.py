"""Tiny ``{{ var }}`` template renderer.

We deliberately avoid Jinja2 here — the templates are short, the
substitution surface is closed (every var is a value we control), and
keeping the renderer in-process means no extra runtime dependency.

Whitespace inside the braces is tolerated: ``{{var}}``, ``{{ var }}``,
``{{  var  }}`` all work. Unknown vars resolve to the empty string so
a stale template never raises in production.

``escape=True`` HTML-escapes every substituted value. The flag is per
call rather than global because the channels disagree: the email
channel's ``body_html`` is HTML and a farm name containing ``&`` has to
become ``&amp;``, while the webhook channel's body is a JSON document
where ``&amp;`` would corrupt the payload. Escaping is applied to the
*values*, never to the template, so the template's own markup survives.

One kind of value is markup on purpose: a list whose length the flat
renderer cannot loop over has to arrive already built (the measured-value
table in an alert email). Wrapping such a value in :class:`SafeMarkup`
exempts it from escaping. Wrap nothing that came from a user or from a
database text column without escaping its parts first — the builder does
that, and that is the whole reason the exemption is a distinct type
rather than a second boolean.
"""

from __future__ import annotations

import html
import re
from typing import Any

_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class SafeMarkup(str):
    """A string that is already HTML and must not be escaped again.

    Only for markup this codebase built, with every interpolated part
    escaped at build time.
    """

    __slots__ = ()


def render(template: str | None, ctx: dict[str, Any], *, escape: bool = False) -> str:
    if template is None:
        return ""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = ctx.get(key, "")
        if value is None:
            return ""
        if isinstance(value, SafeMarkup):
            return str(value)
        text = str(value)
        return html.escape(text, quote=True) if escape else text

    return _PATTERN.sub(_sub, template)
