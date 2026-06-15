"""U-2 guard: worker role vocabulary stays aligned with IAM FarmRole.

The unification's whole point is that a worker record and a login member
speak ONE role language. This test fails loudly if someone drifts the two
enums apart (e.g. renames a FarmRole member, or adds a worker role that
collides with a FarmRole spelling but means something else).
"""

from __future__ import annotations

from typing import get_args

from app.modules.resources.schemas import WorkerRole
from app.shared.auth.context import FarmRole

# The four worker roles that MUST equal a FarmRole member exactly.
_SHARED = {"FarmManager", "Agronomist", "FieldOperator", "Scout"}
# Worker-only extra: generic labour, no login / no permission equivalent.
_WORKER_ONLY = {"FieldWorker"}


def _worker_role_values() -> set[str]:
    return set(get_args(WorkerRole))


def test_shared_worker_roles_are_real_farm_roles() -> None:
    farm_role_values = {r.value for r in FarmRole}
    assert farm_role_values >= _SHARED, _SHARED - farm_role_values


def test_worker_vocabulary_is_shared_plus_extra() -> None:
    assert _worker_role_values() == _SHARED | _WORKER_ONLY


def test_field_worker_is_not_a_permission_role() -> None:
    # FieldWorker grants nothing — it must NOT leak into the IAM enum.
    assert "FieldWorker" not in {r.value for r in FarmRole}


def test_viewer_is_not_a_worker_role() -> None:
    # A read-only Viewer (FarmRole) does not perform plan activities, so it
    # is intentionally excluded from the worker vocabulary.
    assert FarmRole.VIEWER.value not in _worker_role_values()
