"""Phone-as-username primitives for field workers (S-1).

These are the rules that decide whether two supervisors entering the same
person produce one account or two, so they are worth pinning down precisely.
"""

from __future__ import annotations

import pytest

from app.shared.keycloak.field_identity import (
    SYNTHETIC_EMAIL_DOMAIN,
    InvalidPhoneNumberError,
    generate_pin,
    is_synthetic_email,
    normalise_phone,
    synthetic_email,
)


@pytest.mark.parametrize(
    "raw",
    [
        "01001234567",  # what a supervisor actually types
        "0100 123 4567",  # …with the spacing they read off a card
        "+201001234567",
        "+20 100 123 4567",
        "00201001234567",  # dialled internationally from a landline
        "201001234567",  # country code, no plus
    ],
)
def test_every_spelling_of_one_number_normalises_to_one_string(raw: str) -> None:
    """The phone is the username, so two spellings would mean two accounts,
    two PINs, and a scout who cannot explain why their login stopped working."""
    assert normalise_phone(raw) == "+201001234567"


@pytest.mark.parametrize("raw", ["", "   ", "abc", "12345", "+" + "9" * 20])
def test_unusable_input_is_rejected_rather_than_guessed(raw: str) -> None:
    with pytest.raises((InvalidPhoneNumberError, ValueError)):
        normalise_phone(raw)


def test_a_non_egyptian_number_keeps_its_own_country_code() -> None:
    # Already international: the default country code must not be prepended on
    # top, which would produce a plausible number belonging to somebody else.
    assert normalise_phone("+9715012345678") == "+9715012345678"


def test_synthetic_email_is_stable_and_recognisable() -> None:
    phone = normalise_phone("01001234567")
    email = synthetic_email(phone)

    assert email == f"201001234567@{SYNTHETIC_EMAIL_DOMAIN}"
    # Stable: re-running an enrolment must not mint a second address, which
    # would collide with `uq_users_email` or create a duplicate person.
    assert synthetic_email(phone) == email
    assert is_synthetic_email(email)
    assert not is_synthetic_email("agronomist@bashayer.example")
    assert not is_synthetic_email(None)


def test_synthetic_domain_is_not_dot_local() -> None:
    """Keycloak 26 strips `.local` addresses on user-profile write, which would
    silently blank the field we just set."""
    assert not SYNTHETIC_EMAIL_DOMAIN.endswith(".local")


def test_pin_is_numeric_and_not_predictable() -> None:
    pins = {generate_pin() for _ in range(200)}
    assert all(p.isdigit() and len(p) == 6 for p in pins)
    # Not a strength proof — just a guard against a constant or a seeded
    # generator sneaking in, which has happened to credential code before.
    assert len(pins) > 150


def test_pin_length_floor_is_enforced() -> None:
    with pytest.raises(ValueError, match="not a credential"):
        generate_pin(length=3)


def test_a_one_digit_typo_in_an_egyptian_mobile_is_rejected() -> None:
    """The generic 8-15 window swallowed this, and the consequence was not a
    failure — it was a working account under a number nobody owns. The scout
    then could not sign in with their real number, and the app reported
    "wrong phone or PIN". Seen in production."""
    with pytest.raises(InvalidPhoneNumberError) as exc:
        normalise_phone("0100001111")
    assert "12 digits" in str(exc.value)

    # The correct number still normalises from every spelling.
    for spelling in ("01000011111", "+201000011111", "00201000011111", "0100 001 1111"):
        assert normalise_phone(spelling) == "+201000011111"


def test_other_country_codes_keep_the_generic_window() -> None:
    """The tightening is Egypt-specific on purpose; it must not start
    rejecting numbers from anywhere else."""
    assert normalise_phone("+17017305526") == "+17017305526"
    assert normalise_phone("+441234567890") == "+441234567890"
