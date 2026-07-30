"""Three-tier settings resolver — public API.

Service code reads settings via `SettingsResolver`. Admin-side writes
go through `SettingsRepository`. Direct table reads outside this
module are a smell — wrap them in a resolver method instead.
"""

from app.shared.settings.constraints import KeyConstraint, constraint_for, describe
from app.shared.settings.errors import (
    SettingNotFoundError,
    SettingValueError,
    TenantSettingValidationError,
)
from app.shared.settings.repository import SettingsRepository
from app.shared.settings.resolver import (
    ResolvedSetting,
    SettingsResolver,
    invalidate_defaults_cache,
)
from app.shared.settings.validation import validate_value

__all__ = [
    "KeyConstraint",
    "ResolvedSetting",
    "SettingNotFoundError",
    "SettingValueError",
    "SettingsRepository",
    "SettingsResolver",
    "TenantSettingValidationError",
    "constraint_for",
    "describe",
    "invalidate_defaults_cache",
    "validate_value",
]
