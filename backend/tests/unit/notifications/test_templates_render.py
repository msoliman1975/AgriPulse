"""The ``{{ var }}`` renderer, and the escaping switch added for HTML email.

The switch exists because two channels disagree about what a value means.
``body_html`` is markup, so a farm name containing ``&`` has to arrive as
``&amp;`` or the layout breaks and a decision tree authored with a tag
would inject into the message. The webhook body is a JSON document, where
``&amp;`` would corrupt the payload. So the tests below pin both
directions, not just the new one.
"""

from __future__ import annotations

import json

from app.modules.notifications.templates import render


def test_substitutes_and_tolerates_whitespace() -> None:
    ctx = {"who": "Green Farm"}
    assert render("{{who}}|{{ who }}|{{  who  }}", ctx) == "Green Farm|Green Farm|Green Farm"


def test_unknown_var_renders_empty_rather_than_raising() -> None:
    # A stale template must never take the fan-out down.
    assert render("a{{nope}}b", {}) == "ab"


def test_none_value_renders_empty() -> None:
    assert render("[{{x}}]", {"x": None}) == "[]"


def test_none_template_renders_empty() -> None:
    assert render(None, {"x": "y"}) == ""


def test_escape_off_by_default() -> None:
    # The plain-text body and the webhook payload both rely on this.
    assert render("{{v}}", {"v": "a & b"}) == "a & b"


def test_escape_encodes_markup_characters() -> None:
    out = render("<p>{{v}}</p>", {"v": '<script>alert("x")</script> & co'}, escape=True)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&amp; co" in out
    # The template's own markup survives — only values are escaped.
    assert out.startswith("<p>")
    assert out.endswith("</p>")


def test_escape_covers_quotes_so_an_attribute_cannot_be_broken_out_of() -> None:
    out = render('<a title="{{v}}">x</a>', {"v": '" onmouseover="evil()'}, escape=True)
    assert 'onmouseover="evil()' not in out
    assert "&quot;" in out


def test_webhook_json_body_stays_valid_without_escaping() -> None:
    # The shape migration 0014 seeds for the webhook channel.
    template = '{"event":"alert.opened","farm":"{{farm_name}}","snap":{{snap}}}'
    out = render(template, {"farm_name": "Bashayer & Sons", "snap": json.dumps({"ndvi": 0.31})})
    assert json.loads(out)["farm"] == "Bashayer & Sons"
    assert json.loads(out)["snap"] == {"ndvi": 0.31}
