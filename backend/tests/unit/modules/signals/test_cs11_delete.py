"""CS-11 unit tests — observation delete (single + templated group).

Repo mocked; the real DELETE SQL + the route's farm-scoped capability
gate are exercised by the integration suite. Here we pin the service
logic: not-found → 404 domain error, success → audit recorded with the
right event + count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.signals.errors import SignalObservationNotFoundError
from app.modules.signals.service import SignalsServiceImpl


def _impl_with_mocked_repo(repo: AsyncMock) -> SignalsServiceImpl:
    impl = SignalsServiceImpl.__new__(SignalsServiceImpl)
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()
    impl._storage = MagicMock()
    impl._tenant = None  # type: ignore[attr-defined]
    impl._log = None  # type: ignore[attr-defined]
    return impl


@pytest.mark.asyncio
async def test_delete_observation_success_audits() -> None:
    obs_id, farm_id, actor = uuid4(), uuid4(), uuid4()
    repo = AsyncMock()
    repo.delete_observation = AsyncMock(return_value=1)
    impl = _impl_with_mocked_repo(repo)

    await impl.delete_observation(
        observation_id=obs_id, farm_id=farm_id, actor_user_id=actor, tenant_schema="t"
    )

    repo.delete_observation.assert_awaited_once_with(observation_id=obs_id)
    args = impl._audit.record.await_args.kwargs
    assert args["event_type"] == "signals.observation_deleted"
    assert args["subject_id"] == obs_id
    assert args["farm_id"] == farm_id
    assert args["details"]["deleted_count"] == 1


@pytest.mark.asyncio
async def test_delete_observation_missing_raises_and_skips_audit() -> None:
    repo = AsyncMock()
    repo.delete_observation = AsyncMock(return_value=0)
    impl = _impl_with_mocked_repo(repo)

    with pytest.raises(SignalObservationNotFoundError):
        await impl.delete_observation(
            observation_id=uuid4(), farm_id=uuid4(), actor_user_id=None, tenant_schema="t"
        )
    impl._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_template_group_returns_count_and_audits() -> None:
    tid, farm_id = uuid4(), uuid4()
    repo = AsyncMock()
    repo.delete_observations_by_template = AsyncMock(return_value=4)
    impl = _impl_with_mocked_repo(repo)

    deleted = await impl.delete_template_observation(
        template_observation_id=tid, farm_id=farm_id, actor_user_id=None, tenant_schema="t"
    )

    assert deleted == 4
    args = impl._audit.record.await_args.kwargs
    assert args["event_type"] == "signals.template_observation_deleted"
    assert args["details"]["deleted_count"] == 4


@pytest.mark.asyncio
async def test_delete_template_group_missing_raises() -> None:
    repo = AsyncMock()
    repo.delete_observations_by_template = AsyncMock(return_value=0)
    impl = _impl_with_mocked_repo(repo)

    with pytest.raises(SignalObservationNotFoundError):
        await impl.delete_template_observation(
            template_observation_id=uuid4(),
            farm_id=uuid4(),
            actor_user_id=None,
            tenant_schema="t",
        )
    impl._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_observation_passthrough() -> None:
    obs_id = uuid4()
    row = {"id": obs_id, "farm_id": uuid4(), "template_observation_id": None}
    repo = AsyncMock()
    repo.get_observation = AsyncMock(return_value=row)
    impl = _impl_with_mocked_repo(repo)

    assert await impl.get_observation(observation_id=obs_id) == row
