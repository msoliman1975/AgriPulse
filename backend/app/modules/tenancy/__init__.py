"""Tenant identification and segmentation.

Public surface (importable by other modules and `app/main.py`):

  - `app.modules.tenancy.service.TenantService`  (Protocol + concrete impl)
  - `app.modules.tenancy.events.*`               (TenantCreatedV1, ...)
  - `app.modules.tenancy.router.router`          (FastAPI router)

See ARCHITECTURE.md § 5 (tenancy model) and data_model.md § 3.
"""

from app.modules.tenancy.events import TenantCreatedV1
from app.modules.tenancy.service import TenantService, get_tenant_service

__all__ = [
    "TenantCreatedV1",
    "TenantService",
    "get_tenant_service",
]
