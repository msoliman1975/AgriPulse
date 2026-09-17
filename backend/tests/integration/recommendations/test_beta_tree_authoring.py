"""Storing a beta (folding) decision tree: create, append, publish, discard.

The whole point of this piece of work is that a beta tree can be saved at
all, so these tests are about storage rather than about the engine. They go
through ``FoldingTreeAuthorService`` directly, like the sibling authoring
tests, because the service is what the routes call and what the seed script
calls.

Three things are checked that nothing else can check:

  * the definition survives the round trip as an object. It is stored as
    JSONB and read back as the same dictionary, with Arabic text and a
    ``switch.on`` key intact. A YAML round trip loses both.
  * a published beta tree does not appear in the sweep's tree list. That is
    one predicate in one query, and if it ever goes the tree starts writing
    recommendations at growers with no error anywhere.
  * a draft can be discarded. Append is a no-op on an unchanged hash, so
    without a delete one bad draft blocks every later author for ever.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.folding_authoring import (
    BetaNoDraftError,
    BetaTreeCodeExistsError,
    BetaTreeNotFoundError,
    FoldingTreeAuthorService,
)
from app.modules.recommendations.folding_compiler import FoldingCompileError
from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


# The two finding codes these tests register. Named so they cannot collide
# with a real catalogue row: the fixture below inserts them into whatever
# catalogue table exists and removes them again afterwards.
TEST_CODES = ("beta_test_dry", "beta_test_vigour_low")


def _definition(code: str, *, text_en: str = "first", registers: bool = False) -> dict[str, Any]:
    """A small but complete folding tree.

    Every path reaches ``stop``, which is the rule the compiler enforces that
    the old loader does not. The Arabic label and the ``switch`` are here on
    purpose: they are the two things a YAML round trip damages.
    """
    definition: dict[str, Any] = {
        "code": code,
        "name_en": f"Beta tree {code}",
        "name_ar": "شجرة تجريبية",
        "scope": "cell",
        "crop_paths": ["mango"],
        "parameters": {"floor": {"type": "number", "default": 0.3, "min": -1.0, "max": 1.0}},
        "root": "n_start",
        "nodes": {
            "n_start": {
                "label_en": text_en,
                "label_ar": "البداية",
                "set": {"picked": "ndvi"},
                "next": "n_switch",
            },
            "n_switch": {
                "label_en": "How low is the canopy?",
                "switch": {
                    # The key that YAML turns into the boolean True. Stored as
                    # JSON it stays a string, which is the change this whole
                    # piece of work rests on.
                    "on": {"source": "indices", "index": "ndvi", "field": "mean"},
                    "cases": [{"ge": {"source": "params", "name": "floor"}, "go": "n_stop"}],
                    "default": "n_stop",
                },
            },
            "n_stop": {"label_en": "End of the walk", "stop": True},
        },
    }
    if registers:
        definition["registers"] = list(TEST_CODES)
        definition["nodes"]["n_start"]["next"] = "n_register"
        definition["nodes"]["n_register"] = {
            "label_en": "Leaf water is low",
            "register": {"code": TEST_CODES[0], "severity": "warning"},
            "next": "n_switch",
        }
        definition["combinations"] = [
            {
                "codes": [TEST_CODES[0]],
                "action_type": "irrigate",
                "status": "stressed",
                "text_en": "Water shortage.",
                "text_ar": "نقص ماء.",
            }
        ]
    return definition


@pytest.fixture
async def finding_codes(admin_session: AsyncSession):
    """Make ``TEST_CODES`` resolvable, whatever state the catalogue is in.

    `public.decision_tree_findings` arrives in a separate change. Until it
    does there is no table at all, and a tree that registers anything cannot
    compile — which is the correct behaviour and is asserted in its own test
    below. These rows are what lets the rest of the file exercise the
    register path either way.

    `CREATE TABLE IF NOT EXISTS` so the fixture is a no-op once the real
    migration lands; the rows are removed by code at teardown rather than by
    dropping the table, for the same reason.
    """
    await admin_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS public.decision_tree_findings (
                code text PRIMARY KEY,
                clause_en text NOT NULL,
                clause_ar text NOT NULL,
                name_en text NOT NULL,
                name_ar text NOT NULL,
                default_status text NOT NULL,
                description_en text,
                description_ar text,
                is_active boolean NOT NULL DEFAULT TRUE
            )
            """
        )
    )
    for code in TEST_CODES:
        await admin_session.execute(
            text(
                """
                INSERT INTO public.decision_tree_findings
                    (code, clause_en, clause_ar, name_en, name_ar, default_status)
                VALUES (:code, 'a test clause', 'جملة اختبار', 'Test', 'اختبار', 'issue')
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code},
        )
    await admin_session.commit()
    yield TEST_CODES
    await admin_session.execute(
        text("DELETE FROM public.decision_tree_findings WHERE code = ANY(:codes)"),
        {"codes": list(TEST_CODES)},
    )
    await admin_session.commit()


async def _service(admin_session: AsyncSession) -> FoldingTreeAuthorService:
    """The platform scope, which is where beta trees are authored."""
    return FoldingTreeAuthorService(public_session=admin_session, tenant_id=None)


def _code(label: str) -> str:
    return f"beta_{label}_{uuid4().hex[:8]}"


# ---- create ----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_stores_the_definition_as_an_object(admin_session: AsyncSession) -> None:
    service = await _service(admin_session)
    code = _code("create")
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes="v1", actor_user_id=None
    )

    assert tree["code"] == code
    assert tree["stage"] == "beta"
    assert tree["current_version"] is None, "create leaves v1 a draft"
    assert tree["draft_version"] == 1

    # The two things a YAML round trip would have broken.
    stored = tree["definition"]
    assert stored["nodes"]["n_switch"]["switch"]["on"] == {
        "source": "indices",
        "index": "ndvi",
        "field": "mean",
    }, "the switch key came back as a string, not as the boolean True"
    assert stored["name_ar"] == "شجرة تجريبية"

    # And the row really holds JSON, not text.
    row = (
        await admin_session.execute(
            text(
                "SELECT tree_yaml, jsonb_typeof(definition) AS kind "
                "FROM public.decision_tree_versions WHERE tree_id = :tid"
            ),
            {"tid": tree["id"]},
        )
    ).first()
    assert row is not None
    assert row.tree_yaml is None
    assert row.kind == "object"


@pytest.mark.asyncio
async def test_create_refuses_a_code_already_in_use(admin_session: AsyncSession) -> None:
    service = await _service(admin_session)
    code = _code("dup")
    await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    with pytest.raises(BetaTreeCodeExistsError):
        await service.create_tree(
            code=code, definition=_definition(code), notes=None, actor_user_id=None
        )


@pytest.mark.asyncio
async def test_a_definition_that_fails_three_rules_reports_all_three(
    admin_session: AsyncSession,
) -> None:
    """The 422 body lists every problem, not the first one.

    An author fixing one message per round trip is the slow path the
    designer exists to remove, so this is a contract and not a nicety.
    """
    service = await _service(admin_session)
    code = _code("errors")
    broken = _definition(code)
    # 1. a switch with no default.
    del broken["nodes"]["n_switch"]["switch"]["default"]
    # 2. a node nothing can reach.
    broken["nodes"]["n_orphan"] = {"stop": True}
    # 3. a combination rule naming a code the tree never declares.
    broken["combinations"] = [{"codes": ["never_declared"], "text_en": "x", "status": "stressed"}]

    with pytest.raises(FoldingCompileError) as caught:
        await service.create_tree(code=code, definition=broken, notes=None, actor_user_id=None)

    rules = {error.rule for error in caught.value.errors}
    assert "switch-without-default" in rules
    assert "unreachable-node" in rules
    assert "combination-unknown-code" in rules

    # Every error carries Arabic. A blank message on an Arabic screen reads
    # as "no reason given", which is worse than untranslated text.
    for error in caught.value.errors:
        assert error.message_ar, f"{error.rule} has no Arabic message"

    # And nothing was written.
    count = (
        await admin_session.execute(
            text("SELECT count(*) AS n FROM public.decision_trees WHERE code = :c"),
            {"c": code},
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_registers_need_the_finding_catalogue(
    admin_session: AsyncSession, finding_codes: tuple[str, ...]
) -> None:
    """A declared code must resolve, and an unknown one names itself."""
    service = await _service(admin_session)
    code = _code("regs")
    tree = await service.create_tree(
        code=code,
        definition=_definition(code, registers=True),
        notes=None,
        actor_user_id=None,
    )
    assert tree["definition"]["registers"] == list(TEST_CODES)

    unknown_code = _code("unknown_regs")
    definition = _definition(unknown_code, registers=True)
    definition["registers"] = ["no_such_finding_code"]
    definition["nodes"]["n_register"]["register"]["code"] = "no_such_finding_code"
    definition["combinations"] = [
        {"codes": ["no_such_finding_code"], "text_en": "x", "status": "watch"}
    ]
    with pytest.raises(FoldingCompileError) as caught:
        await service.create_tree(
            code=unknown_code, definition=definition, notes=None, actor_user_id=None
        )
    rules = {error.rule for error in caught.value.errors}
    assert "registers-unknown-code" in rules
    assert any("no_such_finding_code" in e.message_en for e in caught.value.errors)


# ---- append ----------------------------------------------------------


@pytest.mark.asyncio
async def test_append_inserts_only_when_the_hash_changed(
    admin_session: AsyncSession,
) -> None:
    service = await _service(admin_session)
    code = _code("append")
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    tree_id: UUID = tree["id"]

    same = await service.append_version(
        tree_id=tree_id, definition=_definition(code), notes="no change", actor_user_id=None
    )
    assert len(same["versions"]) == 1, "an identical body must not add a version"

    changed = await service.append_version(
        tree_id=tree_id,
        definition=_definition(code, text_en="second"),
        notes="changed",
        actor_user_id=None,
    )
    assert len(changed["versions"]) == 2
    assert changed["draft_version"] == 2
    assert changed["definition"]["nodes"]["n_start"]["label_en"] == "second"


@pytest.mark.asyncio
async def test_append_refuses_a_tree_that_is_not_a_beta_tree(
    admin_session: AsyncSession,
) -> None:
    """A live tree's id is not an address here.

    The beta routes and the old editor share one catalogue table, so without
    the stage guard a beta save could overwrite a tree the sweep runs.
    """
    service = await _service(admin_session)
    repo = RecommendationsRepository(tenant_session=admin_session, public_session=admin_session)
    live_id = await repo.insert_tree(
        code=_code("live"),
        tenant_id=None,
        name_en="A live tree",
        name_ar=None,
        description_en=None,
        description_ar=None,
        crop_id=None,
        applicable_regions=[],
        actor_user_id=None,
        stage="live",
    )
    await admin_session.commit()
    with pytest.raises(BetaTreeNotFoundError):
        await service.append_version(
            tree_id=live_id, definition=_definition("x"), notes=None, actor_user_id=None
        )


# ---- publish ---------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_stamps_and_is_idempotent(admin_session: AsyncSession) -> None:
    service = await _service(admin_session)
    code = _code("publish")
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    version_id = tree["versions"][0]["id"]

    first = await service.publish_version(
        tree_id=tree["id"], version_id=version_id, actor_user_id=None
    )
    assert first["version"] == 1
    assert first["published_at"] is not None

    second = await service.publish_version(
        tree_id=tree["id"], version_id=version_id, actor_user_id=None
    )
    assert second["published_at"] == first["published_at"], (
        "a second publish must not move the timestamp — it is the record of "
        "when the tree actually changed"
    )

    after = await service.get_tree(tree["id"])
    assert after["current_version"] == 1
    assert after["draft_version"] is None


@pytest.mark.asyncio
async def test_a_published_beta_tree_never_reaches_the_sweep(
    admin_session: AsyncSession,
) -> None:
    """The one predicate that keeps beta work away from growers.

    `list_active_trees_with_current_version` is the only query the sweep
    resolves its tree set from. A live tree published the same way is in the
    list, so this is not passing because the query returned nothing.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"beta-sweep-{uuid4().hex[:8]}",
        name="beta sweep",
        contact_email="ops@beta.test",
    )
    service = await _service(admin_session)
    repo = RecommendationsRepository(tenant_session=admin_session, public_session=admin_session)

    beta_code = _code("swept")
    beta = await service.create_tree(
        code=beta_code, definition=_definition(beta_code), notes=None, actor_user_id=None
    )
    await service.publish_version(
        tree_id=beta["id"], version_id=beta["versions"][0]["id"], actor_user_id=None
    )

    # A live control, published the same way, so a query that returns nothing
    # cannot make this test pass.
    live_code = _code("control")
    live_id = await repo.insert_tree(
        code=live_code,
        tenant_id=None,
        name_en="Control",
        name_ar=None,
        description_en=None,
        description_ar=None,
        crop_id=None,
        applicable_regions=[],
        actor_user_id=None,
        stage="live",
    )
    live_version_id = await repo.insert_version(
        tree_id=live_id,
        version=1,
        tree_yaml="code: x\nname_en: x\nroot: leaf\nnodes: {}\n",
        tree_compiled={"code": live_code, "name_en": "Control", "nodes": {}},
        compiled_hash="control-hash",
        notes=None,
        published_at=None,
        published_by=None,
    )
    await repo.stamp_published(
        version_id=live_version_id,
        published_at=datetime.now(UTC),
        published_by=None,
    )
    await repo.set_current_version(tree_id=live_id, version_id=live_version_id, actor_user_id=None)
    await admin_session.commit()

    swept = await repo.list_active_trees_with_current_version(visible_to_tenant_id=tenant.tenant_id)
    codes = {row["tree_code"] for row in swept}
    assert live_code in codes, "the control tree must be swept, or this proves nothing"
    assert beta_code not in codes


# ---- discard ---------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_removes_the_draft_and_leaves_the_published_version(
    admin_session: AsyncSession,
) -> None:
    service = await _service(admin_session)
    code = _code("discard")
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await service.publish_version(
        tree_id=tree["id"], version_id=tree["versions"][0]["id"], actor_user_id=None
    )
    with_draft = await service.append_version(
        tree_id=tree["id"],
        definition=_definition(code, text_en="second"),
        notes=None,
        actor_user_id=None,
    )
    assert with_draft["draft_version"] == 2

    await service.discard_draft(tree_id=tree["id"], actor_user_id=None)

    after = await service.get_tree(tree["id"])
    assert after["draft_version"] is None
    assert len(after["versions"]) == 1
    assert after["current_version"] == 1
    assert after["definition"]["nodes"]["n_start"]["label_en"] == "first"


@pytest.mark.asyncio
async def test_discard_refuses_when_the_newest_version_is_published(
    admin_session: AsyncSession,
) -> None:
    service = await _service(admin_session)
    code = _code("nodraft")
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await service.publish_version(
        tree_id=tree["id"], version_id=tree["versions"][0]["id"], actor_user_id=None
    )
    with pytest.raises(BetaNoDraftError):
        await service.discard_draft(tree_id=tree["id"], actor_user_id=None)


@pytest.mark.asyncio
async def test_a_discarded_draft_can_be_saved_again(admin_session: AsyncSession) -> None:
    """The reason the route exists, stated as a test.

    Append is a no-op on an unchanged hash, so re-saving a draft's own body
    never removes it. After a discard the same body saves as a fresh draft,
    which is what makes a bad save recoverable.
    """
    service = await _service(admin_session)
    code = _code("resave")
    tree = await service.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    await service.publish_version(
        tree_id=tree["id"], version_id=tree["versions"][0]["id"], actor_user_id=None
    )
    bad = _definition(code, text_en="a save the author did not want")
    await service.append_version(tree_id=tree["id"], definition=bad, notes=None, actor_user_id=None)

    # Saving over it does nothing, which is the trap.
    unchanged = await service.append_version(
        tree_id=tree["id"], definition=bad, notes=None, actor_user_id=None
    )
    assert unchanged["draft_version"] == 2

    await service.discard_draft(tree_id=tree["id"], actor_user_id=None)
    again = await service.append_version(
        tree_id=tree["id"],
        definition=_definition(code, text_en="what the author meant"),
        notes=None,
        actor_user_id=None,
    )
    assert again["draft_version"] == 2
    assert again["definition"]["nodes"]["n_start"]["label_en"] == "what the author meant"


# ---- scope -----------------------------------------------------------


@pytest.mark.asyncio
async def test_one_tenants_beta_tree_is_invisible_to_another(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    one = await tenancy.create_tenant(
        slug=f"beta-a-{uuid4().hex[:8]}", name="a", contact_email="a@beta.test"
    )
    two = await tenancy.create_tenant(
        slug=f"beta-b-{uuid4().hex[:8]}", name="b", contact_email="b@beta.test"
    )
    theirs = FoldingTreeAuthorService(public_session=admin_session, tenant_id=one.tenant_id)
    other = FoldingTreeAuthorService(public_session=admin_session, tenant_id=two.tenant_id)
    code = _code("scoped")
    tree = await theirs.create_tree(
        code=code, definition=_definition(code), notes=None, actor_user_id=None
    )
    with pytest.raises(BetaTreeNotFoundError):
        await other.get_tree(tree["id"])
    assert code not in {row["code"] for row in await other.list_trees()}
