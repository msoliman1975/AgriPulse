"""Three-tier settings resolver — public API.

Service code reads settings via `SettingsResolver`. Admin-side writes
go through `SettingsRepository`. Direct table reads outside this
module are a smell — wrap them in a resolver method instead.
"""

from app.shared.settings.errors import (
    SettingNotFoundError,
    TenantSettingValidationError,
)
from app.shared.settings.repository import SettingsRepository
from app.shared.settings.resolver import (
    ResolvedSetting,
    SettingsResolver,
    invalidate_defaults_cache,
)

__all__ = [
    "ResolvedSetting",
    "SettingNotFoundError",
    "SettingsRepository",
    "SettingsResolver",
    "TenantSettingValidationError",
    "invalidate_defaults_cache",
]
