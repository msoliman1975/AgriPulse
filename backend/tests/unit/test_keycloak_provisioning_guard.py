"""IH-3: deployed-env provisioning misconfiguration guard."""

from __future__ import annotations

from app.core.settings import Settings
from app.shared.keycloak import provisioning_config_problems


def test_dev_env_with_noop_is_fine() -> None:
    s = Settings(app_env="dev", keycloak_provisioning_enabled=False)
    assert provisioning_config_problems(s) == []


def test_test_env_with_noop_is_fine() -> None:
    s = Settings(app_env="test", keycloak_provisioning_enabled=False)
    assert provisioning_config_problems(s) == []


def test_production_without_provisioning_flags_problem() -> None:
    s = Settings(app_env="production", keycloak_provisioning_enabled=False)
    assert provisioning_config_problems(s) == ["provisioning_disabled"]


def test_staging_without_provisioning_flags_problem() -> None:
    s = Settings(app_env="staging", keycloak_provisioning_enabled=False)
    assert provisioning_config_problems(s) == ["provisioning_disabled"]


def test_production_enabled_but_secret_missing_flags_problem() -> None:
    s = Settings(
        app_env="production",
        keycloak_provisioning_enabled=True,
        keycloak_admin_client_secret="",
    )
    assert provisioning_config_problems(s) == ["admin_client_secret_missing"]


def test_production_fully_configured_is_clean() -> None:
    s = Settings(
        app_env="production",
        keycloak_provisioning_enabled=True,
        keycloak_admin_client_secret="a-secret",
    )
    assert provisioning_config_problems(s) == []
