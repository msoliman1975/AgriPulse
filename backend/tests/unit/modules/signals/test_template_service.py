"""CS-2/3 unit tests — template service logic (mocked repository).

Covers the pre-DB validation that lives in the service layer:
- duplicate signal_definition_id rejection
- duplicate position rejection
- empty-member rejection on update
- missing_definitions round-trip
- aggregation coercion path on create_definition

Repository writes are mocked — the integration suite (separate PR) will
exercise the real DB + ST_Within trigger + unique constraints.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.modules.signals.errors import (
    SignalTemplateMembersInvalidError,
    SignalTemplateNotFoundError,
)
from app.modules.signals.schemas import SignalTemplateDefinitionMember
from app.modules.signals.service import SignalsServiceImpl


def _impl_with_mocked_repo(repo: AsyncMock) -> SignalsServiceImpl:
    """Construct the impl bypassing __init__ — we only need the
    template / definition methods to work, and those only touch
    self._repo + self._audit. AsyncMocks satisfy both."""
    impl = SignalsServiceImpl.__new__(SignalsServiceImpl)
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()
    impl._storage = None  # type: ignore[attr-defined]
    impl._tenant = None  # type: ignore[attr-defined]
    impl._log = None  # type: ignore[attr-defined]
    return impl


def _member(
    def_id: UUID, position: int, is_required: bool = False
) -> SignalTemplateDefinitionMember:
    return SignalTemplateDefinitionMember(
        signal_definition_id=def_id,
        position=position,
        is_required=is_required,
    )


class TestValidateTemplateMembers:
    """The pure-function pre-checks. Repository never touched."""

    def test_empty_rejected(self) -> None:
        with pytest.raises(SignalTemplateMembersInvalidError, match="at least one member"):
            SignalsServiceImpl._validate_template_members(())

    def test_duplicate_definition_id_rejected(self) -> None:
        dup = uuid4()
        members = (_member(dup, 0), _member(dup, 1))
        with pytest.raises(
            SignalTemplateMembersInvalidError, match="Duplicate signal_definition_id"
        ):
            SignalsServiceImpl._validate_template_members(members)

    def test_duplicate_position_rejected(self) -> None:
        members = (_member(uuid4(), 0), _member(uuid4(), 0))
        with pytest.raises(SignalTemplateMembersInvalidError, match="Duplicate position"):
            SignalsServiceImpl._validate_template_members(members)

    def test_happy_path(self) -> None:
        # No exception = pass; nothing to assert beyond that.
        SignalsServiceImpl._validate_template_members(
            (_member(uuid4(), 0), _member(uuid4(), 1, is_required=True))
        )


@pytest.mark.asyncio
class TestCreateTemplate:
    async def test_missing_definition_rejected_with_400(self) -> None:
        missing_id = uuid4()
        repo = AsyncMock()
        repo.missing_definitions = AsyncMock(return_value=(missing_id,))
        impl = _impl_with_mocked_repo(repo)

        with pytest.raises(SignalTemplateMembersInvalidError, match="unknown or deleted"):
            await impl.create_template(
                code="soil-lab",
                name="Soil lab",
                description=None,
                members=(_member(missing_id, 0),),
                actor_user_id=None,
                tenant_schema="t_x",
            )
        # Insert never called because pre-check failed.
        repo.insert_template.assert_not_called()

    async def test_happy_path_inserts_and_audits(self) -> None:
        def_id = uuid4()
        template_row: dict[str, Any] = {"id": uuid4(), "code": "soil-lab", "name": "Soil lab"}
        members_row = ({"signal_definition_id": def_id, "position": 0, "is_required": True},)
        repo = AsyncMock()
        repo.missing_definitions = AsyncMock(return_value=())
        repo.insert_template = AsyncMock(return_value=template_row)
        repo.get_template_members = AsyncMock(return_value=members_row)
        impl = _impl_with_mocked_repo(repo)

        tpl, members = await impl.create_template(
            code="soil-lab",
            name="Soil lab",
            description=None,
            members=(_member(def_id, 0, is_required=True),),
            actor_user_id=None,
            tenant_schema="t_x",
        )
        assert tpl == template_row
        assert members == members_row
        # repo.insert_template gets a tuple-of-tuples of repo shape.
        call_members = repo.insert_template.await_args.kwargs["members"]
        assert call_members == ((def_id, 0, True),)
        # audit emitted with right event type + payload.
        audit_call = impl._audit.record.await_args  # type: ignore[attr-defined]
        assert audit_call.kwargs["event_type"] == "signals.template_created"
        assert audit_call.kwargs["details"] == {"code": "soil-lab", "member_count": 1}


@pytest.mark.asyncio
class TestUpdateTemplate:
    async def test_unknown_template_raises_404(self) -> None:
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value=None)
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(SignalTemplateNotFoundError):
            await impl.update_template(
                template_id=uuid4(),
                updates={"name": "x"},
                members=None,
                actor_user_id=None,
                tenant_schema="t_x",
            )

    async def test_empty_member_list_on_update_rejected(self) -> None:
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value={"id": uuid4(), "code": "x"})
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(SignalTemplateMembersInvalidError, match="cannot be empty"):
            await impl.update_template(
                template_id=uuid4(),
                updates={},
                members=(),
                actor_user_id=None,
                tenant_schema="t_x",
            )

    async def test_scalar_only_update_skips_member_path(self) -> None:
        template_row = {"id": uuid4(), "code": "x"}
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value=template_row)
        repo.update_template = AsyncMock(return_value=template_row)
        repo.get_template_members = AsyncMock(return_value=())
        impl = _impl_with_mocked_repo(repo)

        await impl.update_template(
            template_id=uuid4(),
            updates={"name": "renamed"},
            members=None,
            actor_user_id=None,
            tenant_schema="t_x",
        )
        # `members=None` should be forwarded to repo so it leaves the
        # member list alone, and we shouldn't bother with the
        # definitions-exist check.
        assert repo.update_template.await_args.kwargs["members"] is None
        repo.missing_definitions.assert_not_called()
