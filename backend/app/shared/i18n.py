"""The languages this product speaks.

One definition, because there were already three: `tenancy.schemas.default_locale`,
`auth.context.preferred_language`, and the `user_preferences.language` column's
`'en'` default. Three copies of a list that must agree is how a language gets
added in one place and silently rejected in another.

Adding a language is deliberately two steps, and both are required before the
value is worth accepting:

1. add the code here, and
2. add a catalogue for it in `mobile/src/i18n/locales/` and register it there.

The API validating a code the app cannot render is not a failure the user sees
as "unsupported language" — the app falls back to English and the setting looks
broken. Keep this list to what has actually been translated.
"""

from __future__ import annotations

from typing import Literal, get_args

SupportedLanguage = Literal["en", "ar"]

SUPPORTED_LANGUAGES: tuple[str, ...] = get_args(SupportedLanguage)

# What a person gets when nothing has been chosen for them. English rather than
# Arabic: this is the platform-wide default, and the office-facing web app is
# the majority of sessions. The mobile enrolment path overrides it to Arabic,
# which is the language of the person actually holding the phone.
DEFAULT_LANGUAGE: SupportedLanguage = "en"
