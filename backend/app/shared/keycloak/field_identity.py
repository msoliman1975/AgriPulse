"""Identity primitives for field workers who have a phone but no email.

The identity core requires an email: ``public.users.email`` is ``CITEXT NOT
NULL`` with a UNIQUE constraint, and ``KeycloakAdminClient`` uses the email as
the Keycloak username. Egyptian field labour generally has neither an email
address nor a reason to want one, so without this a scout simply cannot be
provisioned — the mobile app would ship with a login screen nobody can pass.

The chosen shape (D7) keeps the phone as the real identity and mints a
non-deliverable address to satisfy the constraint::

    phone  = +201001234567                            <- what they type to sign in
    email  = +201001234567@scouts.agripulse.cloud     <- synthetic, never delivered

Nothing here talks to Keycloak; it is pure text handling so it can be tested
without a realm, and so the rules live in one place rather than being
re-derived at each call site.
"""

from __future__ import annotations

import re
import secrets

# A domain we control, with **no MX record**, so a stray send cannot leave the
# building. Deliberately not `.local`: Keycloak 26 strips `.local` addresses on
# user-profile write, which would silently blank the field we just set.
SYNTHETIC_EMAIL_DOMAIN = "scouts.agripulse.cloud"

# Egypt. Kept explicit rather than guessed from a locale: a wrong country code
# produces a plausible-looking number that belongs to somebody else.
_DEFAULT_COUNTRY_CODE = "20"

_NON_DIGITS = re.compile(r"[^\d+]")


class InvalidPhoneNumberError(ValueError):
    """The string given cannot be read as a phone number."""


# +20, then a 10-digit national number beginning 1X.
_EG_COUNTRY_CODE = "20"
_EG_MSISDN_LENGTH = 12


def normalise_phone(raw: str, *, country_code: str = _DEFAULT_COUNTRY_CODE) -> str:
    """Return an E.164 phone number, or raise.

    Supervisors type what they know — ``01001234567``, ``0100 123 4567``,
    ``+20 100 123 4567`` — and every one of those is the same person. They must
    normalise to one string, because the phone *is* the username: two spellings
    would mean two accounts, two PINs, and a scout who cannot explain why their
    login stopped working.
    """
    if not raw or not raw.strip():
        raise InvalidPhoneNumberError("phone number is empty")

    cleaned = _NON_DIGITS.sub("", raw.strip())
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    elif cleaned.startswith("00"):
        # International prefix as dialled from a landline.
        digits = cleaned[2:]
    elif cleaned.startswith("0"):
        # National trunk prefix: drop the leading 0 and prepend the country.
        digits = f"{country_code}{cleaned[1:]}"
    else:
        digits = cleaned if cleaned.startswith(country_code) else f"{country_code}{cleaned}"

    if not digits.isdigit():
        raise InvalidPhoneNumberError(f"not a phone number: {raw!r}")
    # E.164 allows at most 15 digits; anything under 8 is a typo, not a number.
    if not 8 <= len(digits) <= 15:
        raise InvalidPhoneNumberError(
            f"phone number must be 8-15 digits after normalisation, got {len(digits)}: {raw!r}"
        )
    # Country-specific length, because the generic 8-15 window is wide enough
    # to swallow a one-digit typo — and here that does not fail, it mints a
    # working account under a number nobody owns. The scout then cannot sign
    # in with their real number and the error says "wrong phone or PIN".
    if digits.startswith(_EG_COUNTRY_CODE) and len(digits) != _EG_MSISDN_LENGTH:
        raise InvalidPhoneNumberError(
            f"an Egyptian mobile is {_EG_MSISDN_LENGTH} digits in E.164 "
            f"(+20 1X XXXX XXXX); got {len(digits)}: {raw!r}"
        )
    return f"+{digits}"


def synthetic_email(phone_e164: str) -> str:
    """Mint the placeholder address that satisfies ``users.email``.

    Derived from the phone rather than random so it is stable: re-running an
    enrolment for the same person produces the same address instead of a second
    account. The ``+`` is dropped because it is a valid but awkward local-part
    character that some tooling treats as a subaddress separator.
    """
    return f"{phone_e164.lstrip('+')}@{SYNTHETIC_EMAIL_DOMAIN}"


def is_synthetic_email(email: str | None) -> bool:
    """True when this address was minted here.

    Used to keep placeholder addresses out of anything that reads like a way to
    contact somebody — the Team screen, exports, reports.
    """
    if not email:
        return False
    return email.strip().lower().endswith(f"@{SYNTHETIC_EMAIL_DOMAIN}")


def generate_pin(length: int = 6) -> str:
    """A numeric PIN a scout can be told out loud and can type with gloves on.

    Numeric on purpose: the sign-in screen shows a number pad, and a mixed-case
    password read across a field is transcribed wrong more often than not.
    Generated with ``secrets`` rather than ``random`` — it is a credential, and
    the weakness of six digits is already the ceiling here, so the generator
    must not lower it further.
    """
    if length < 4:
        raise ValueError("a PIN shorter than 4 digits is not a credential")
    return "".join(secrets.choice("0123456789") for _ in range(length))
