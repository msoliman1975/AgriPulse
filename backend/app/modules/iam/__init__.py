"""Identity and access. Public surface:

  - `app.modules.iam.service.UserService`  (Protocol + concrete impl)
  - `app.modules.iam.events.*`             (UserUpsertedV1, ...)
  - `app.modules.iam.router.router`        (FastAPI router)

See ARCHITECTURE.md § 7 and data_model.md § 4.
"""

from app.modules.iam.events import UserUpsertedV1
from app.modules.iam.service import UserService, get_user_service

__all__ = [
    "UserService",
    "UserUpsertedV1",
    "get_user_service",
]
