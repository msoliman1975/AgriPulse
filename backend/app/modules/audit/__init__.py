"""Audit log. Public surface:

  - `app.modules.audit.service.AuditService`  (Protocol + concrete impl)
  - `app.modules.audit.events.*`              (placeholder)

See data_model.md § 13.
"""

from app.modules.audit.service import AuditService, get_audit_service

__all__ = [
    "AuditService",
    "get_audit_service",
]
