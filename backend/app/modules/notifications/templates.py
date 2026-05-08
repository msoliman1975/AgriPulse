"""Tiny ``{{ var }}`` template renderer.

We deliberately avoid Jinja2 here — the templates are short, the
substitution surface is closed (every var is a value we control), and
keeping the renderer in-process means no extra runtime dependency.

Whitespace inside the braces is tolerated: ``{{var}}``, ``{{ var }}``,
``{{  var  }}`` all work. Unknown vars resolve to the empty string so
a stale template never raises in production.
"""

from __future__ import annotations

import re
from typing import Any

_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def render(template: str | None, ctx: dict[str, Any]) -> str:
    if template is None:
        return ""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = ctx.get(key, "")
        return str(value) if value is not None else ""

    return _PATTERN.sub(_sub, template)
