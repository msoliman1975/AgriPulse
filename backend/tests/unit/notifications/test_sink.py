"""The notification sink.

This is the component whose failure mode is sending real email to real
customers, so the tests are weighted towards what must *not* happen: no
suppression without an explicit prefix, no suppression of a tenant that merely
resembles a simulation one, and no leakage of the flag past the handler that
set it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.modules.notifications.sink import (
    OutboundSuppressedError,
    activate_for_tenant,
    is_suppressed,
    outbound_for_tenant,
    resets_outbound,
    resolve_for_tenant,
)


class _FakeSession:
    """Answers the one slug lookup `resolve_for_tenant` makes."""

    def __init__(self, slug: str | None) -> None:
        self._slug = slug

    def execute(self, *_args: Any, **_kwargs: Any) -> _FakeSession:
        return self

    def scalar_one_or_none(self) -> str | None:
        return self._slug


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Any:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_prefix(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("NOTIFICATION_SINK_TENANT_PREFIX", value)
    get_settings.cache_clear()


def test_no_prefix_configured_suppresses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default in every environment that hosts no simulation runs."""
    _set_prefix(monkeypatch, "")
    assert resolve_for_tenant(_FakeSession("sim-abc123"), uuid4()) is False


def test_matching_slug_is_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prefix(monkeypatch, "sim-")
    assert resolve_for_tenant(_FakeSession("sim-abc123"), uuid4()) is True


def test_real_tenant_is_not_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The assertion that protects every paying customer on the box."""
    _set_prefix(monkeypatch, "sim-")
    for slug in ("bashayer", "simba-farms", "a-sim-tenant", "SIM-UPPER"):
        assert resolve_for_tenant(_FakeSession(slug), uuid4()) is False, slug


def test_missing_tenant_is_not_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prefix(monkeypatch, "sim-")
    assert resolve_for_tenant(_FakeSession(None), uuid4()) is False


def test_context_is_false_by_default() -> None:
    """Fails open: code that never established the context delivers."""
    assert is_suppressed() is False


def test_context_manager_restores_previous_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prefix(monkeypatch, "sim-")
    with outbound_for_tenant(_FakeSession("sim-1"), uuid4()) as suppressed:
        assert suppressed is True
        assert is_suppressed() is True
    assert is_suppressed() is False


def test_decorator_resets_even_when_the_handler_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leak that would silence a real customer.

    Handlers are sync and full of early returns, and they run one after another
    on the same thread. If a simulation tenant's handler left the flag set, the
    next tenant's notifications would be dropped silently.
    """
    _set_prefix(monkeypatch, "sim-")

    @resets_outbound
    def handler() -> None:
        activate_for_tenant(_FakeSession("sim-1"), uuid4())
        assert is_suppressed() is True
        raise RuntimeError("handler blew up mid fan-out")

    with pytest.raises(RuntimeError):
        handler()
    assert is_suppressed() is False


def test_decorator_resets_after_a_normal_return(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prefix(monkeypatch, "sim-")

    @resets_outbound
    def handler() -> None:
        activate_for_tenant(_FakeSession("sim-1"), uuid4())

    handler()
    assert is_suppressed() is False


def test_transports_refuse_to_send_while_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The backstop, for a call site added later that forgets to check.

    It raises rather than returning quietly: ``send_email`` returns ``None`` on
    success, so a silent return would leave the dispatch row reading ``sent``
    for a mail that was never sent -- corrupting the table the harness reads as
    its oracle.
    """
    _set_prefix(monkeypatch, "sim-")
    from app.modules.notifications.push import send_push
    from app.modules.notifications.smtp import send_email
    from app.modules.notifications.webhook import send_webhook

    @resets_outbound
    def handler() -> None:
        activate_for_tenant(_FakeSession("sim-1"), uuid4())
        with pytest.raises(OutboundSuppressedError):
            send_email(to_address="real@customer.test", subject="s", body_text="b")
        with pytest.raises(OutboundSuppressedError):
            send_push(token="tok", title="t", body="b", data={})
        with pytest.raises(OutboundSuppressedError):
            send_webhook(
                url="https://customer.test/hook",
                secret="s",
                event_name="alert.opened",
                delivery_id=uuid4(),
                body={},
            )

    handler()
