"""How the FCM bearer is sourced.

This is the branch that cannot be caught anywhere but production: the code
path only runs when `fcm_enabled` is true, which no test environment sets, so
a wrong precedence or a missing setting shows up as every push silently
recording `skipped` — or, worse, as a 500 in a subscriber.
"""

from __future__ import annotations

import json

import pytest

from app.modules.notifications.push import (
    PushSendError,
    _bearer,
    reset_fcm_credentials,
)


class _Settings:
    def __init__(self, **kw: object) -> None:
        self.fcm_access_token = ""
        self.fcm_service_account_file = ""
        self.fcm_service_account_json = ""
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture(autouse=True)
def _clean() -> None:
    # The credential is cached in a module global; a leaked one from another
    # test would make the precedence assertions below meaningless.
    reset_fcm_credentials()


def test_static_token_wins_over_everything() -> None:
    """The documented escape hatch for a one-off manual test."""
    settings = _Settings(
        fcm_access_token="ya29.hand-minted",
        fcm_service_account_json='{"type":"service_account"}',
    )
    assert _bearer(settings) == "ya29.hand-minted"


def test_no_credential_at_all_names_all_three_options() -> None:
    """The operator reading this error is deciding which one to set."""
    with pytest.raises(PushSendError) as exc:
        _bearer(_Settings())
    message = str(exc.value)
    assert "FCM_SERVICE_ACCOUNT_JSON" in message
    assert "FCM_SERVICE_ACCOUNT_FILE" in message
    assert "FCM_ACCESS_TOKEN" in message


def test_malformed_inline_json_says_so_rather_than_erroring_deep() -> None:
    """A truncated secret is a realistic way for this to be wrong, and
    `json.JSONDecodeError` surfacing from inside google-auth would send
    somebody looking in the wrong library."""
    with pytest.raises(PushSendError) as exc:
        _bearer(_Settings(fcm_service_account_json="{not json"))
    assert "not valid JSON" in str(exc.value)


def test_inline_json_is_parsed_and_preferred_over_a_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hetzner injects secrets as env vars and mounts no secret volumes, so
    inline has to work — and has to win when a stale file path is also set."""
    captured: dict[str, object] = {}

    class _FakeCreds:
        valid = True
        expired = False
        token = "ya29.from-inline"

    class _FakeServiceAccount:
        class Credentials:
            @staticmethod
            def from_service_account_info(info: dict[str, object], **kw: object) -> _FakeCreds:
                captured["info"] = info
                captured["scopes"] = kw.get("scopes")
                return _FakeCreds()

            @staticmethod
            def from_service_account_file(path: str, **kw: object) -> _FakeCreds:
                raise AssertionError(f"file path {path!r} must not be read when JSON is set")

    monkeypatch.setitem(
        __import__("sys").modules,
        "google.oauth2",
        type("m", (), {"service_account": _FakeServiceAccount}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.oauth2.service_account",
        _FakeServiceAccount,
    )

    payload = {"type": "service_account", "project_id": "agripulse-scout"}
    settings = _Settings(
        fcm_service_account_json=json.dumps(payload),
        fcm_service_account_file="C:/keys/stale.json",
    )
    assert _bearer(settings) == "ya29.from-inline"
    assert captured["info"] == payload
    assert captured["scopes"] == ["https://www.googleapis.com/auth/firebase.messaging"]
