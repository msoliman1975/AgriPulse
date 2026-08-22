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
"""

from __future__ import annotations

import html
import re
from typing import Any

_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def render(template: str | None, ctx: dict[str, Any], *, escape: bool = False) -> str:
    if template is None:
        return ""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = ctx.get(key, "")
        text = str(value) if value is not None else ""
        return html.escape(text, quote=True) if escape else text

    return _PATTERN.sub(_sub, template)
