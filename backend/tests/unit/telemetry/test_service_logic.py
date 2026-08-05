"""Row-building, clock clamping and rate limiting — no DB needed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.modules.telemetry.schemas import IngestBatch, IngestEvent
from app.modules.telemetry.service import (
    TelemetryServiceImpl,
    _actor_role,
    _clamp_time,
    _RateLimiter,
)
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)

_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _ctx(**kw: object) -> RequestContext:
    base: dict[str, object] = {"user_id": uuid4(), "keycloak_subject": "sub"}
    base.update(kw)
    return RequestContext(**base)  # type: ignore[arg-type]


def _row(event: IngestEvent, context: RequestContext) -> dict[str, object] | None:
    svc = TelemetryServiceImpl()
    batch = IngestBatch(session_id=uuid4(), events=[event])
    return svc._build_row(event, batch=batch, context=context, now=_NOW, taxonomy=svc.taxonomy)


# --- clock clamping --------------------------------------------------------


def test_clamp_accepts_a_plausible_timestamp() -> None:
    when = _NOW - timedelta(minutes=2)
    assert _clamp_time(when, _NOW) == when


def test_clamp_rejects_a_future_timestamp() -> None:
    """Future rows land in chunks retention and compression never reach."""
    assert _clamp_time(_NOW + timedelta(days=400), _NOW) == _NOW


def test_clamp_rejects_a_far_past_timestamp() -> None:
    assert _clamp_time(_NOW - timedelta(days=400), _NOW) == _NOW


def test_clamp_assumes_utc_for_naive_input() -> None:
    naive = (_NOW - timedelta(minutes=1)).replace(tzinfo=None)
    assert _clamp_time(naive, _NOW).tzinfo is not None


def test_clamp_defaults_to_now_when_absent() -> None:
    assert _clamp_time(None, _NOW) == _NOW


def test_clamped_fallback_is_stable_within_a_minute() -> None:
    """Why the fallback is floored: `(time, id)` is the idempotency key.

    A raw `now()` fallback would give two deliveries of the same event different
    timestamps, so dedupe would hold for well-behaved clocks and fail silently
    for skewed ones. Flooring makes the fallback identical for a whole minute,
    which covers the realistic resend window.
    """
    skewed = _NOW + timedelta(days=900)
    first = _clamp_time(skewed, _NOW.replace(second=3, microsecond=100))
    second = _clamp_time(skewed, _NOW.replace(second=41, microsecond=900_000))
    assert first == second == _NOW.replace(second=0, microsecond=0)


# --- identity stamping -----------------------------------------------------


def test_identity_comes_from_context_not_payload() -> None:
    """The whole security property of ingest, in one test.

    The payload below tries to claim someone else's identity. `IngestEvent`
    ignores unknown fields, so those keys never even reach the row builder.
    """
    user_id, tenant_id = uuid4(), uuid4()
    context = _ctx(user_id=user_id, tenant_id=tenant_id, tenant_role=TenantRole.TENANT_ADMIN)
    forged = IngestEvent.model_validate(
        {
            "event_name": "page_view",
            "user_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "actor_role": "PlatformAdmin",
            "is_platform_staff": True,
            "locale": "fr",
        }
    )
    row = _row(forged, context)
    assert row is not None
    assert row["user_id"] == user_id
    assert row["tenant_id"] == tenant_id
    assert row["actor_role"] == "TenantAdmin"
    assert row["is_platform_staff"] is False
    assert row["locale"] == "en"


def test_platform_staff_is_flagged() -> None:
    """Without this flag our own clicking dominates every chart."""
    context = _ctx(tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    row = _row(IngestEvent(event_name="page_view"), context)
    assert row is not None
    assert row["is_platform_staff"] is True
    assert row["tenant_id"] is None
    assert row["actor_role"] == "PlatformAdmin"


def test_actor_role_prefers_platform_then_tenant() -> None:
    assert (
        _actor_role(
            _ctx(platform_role=PlatformRole.PLATFORM_SUPPORT, tenant_role=TenantRole.TENANT_OWNER)
        )
        == "PlatformSupport"
    )
    assert _actor_role(_ctx(tenant_role=TenantRole.BILLING_ADMIN)) == "BillingAdmin"


def test_actor_role_uses_a_single_farm_scope() -> None:
    scope = FarmScope(farm_id=uuid4(), role=FarmRole.AGRONOMIST)
    assert _actor_role(_ctx(farm_scopes=(scope,))) == "Agronomist"


def test_actor_role_is_none_when_farm_scopes_disagree() -> None:
    """Picking one of several farm roles would be arbitrary, so pick none."""
    scopes = (
        FarmScope(farm_id=uuid4(), role=FarmRole.AGRONOMIST),
        FarmScope(farm_id=uuid4(), role=FarmRole.VIEWER),
    )
    assert _actor_role(_ctx(farm_scopes=scopes)) is None


# --- vocabulary enforcement ------------------------------------------------


def test_unknown_event_name_is_rejected() -> None:
    assert _row(IngestEvent(event_name="hack_the_planet"), _ctx()) is None


def test_unknown_feature_is_rejected() -> None:
    assert _row(IngestEvent(event_name="feature_used", feature="nope"), _ctx()) is None


def test_unknown_flow_is_rejected() -> None:
    assert _row(IngestEvent(event_name="flow_start", flow="nope"), _ctx()) is None


def test_step_without_its_flow_is_rejected() -> None:
    """A step is meaningless without the flow it belongs to."""
    assert _row(IngestEvent(event_name="flow_step", step="details"), _ctx()) is None


def test_step_from_the_wrong_flow_is_rejected() -> None:
    event = IngestEvent(event_name="flow_step", flow="backfill_run", step="subscriptions")
    assert _row(event, _ctx()) is None


def test_valid_flow_step_is_accepted() -> None:
    event = IngestEvent(event_name="flow_step", flow="farm_onboarding", step="subscriptions")
    assert _row(event, _ctx()) is not None


def test_props_are_allow_listed_in_the_row() -> None:
    event = IngestEvent(
        event_name="feature_used",
        feature="reports",
        props={"action": "export", "farm_name": "Bashayer", "notes": "secret"},
    )
    row = _row(event, _ctx())
    assert row is not None
    assert row["props"] == '{"action":"export"}'
    assert row["_props_dropped"] == 2


def test_absurd_props_count_rejects_the_event() -> None:
    event = IngestEvent(event_name="page_view", props={f"k{i}": i for i in range(50)})
    assert _row(event, _ctx()) is None


def test_client_id_is_preserved_for_idempotency() -> None:
    given = uuid4()
    row = _row(IngestEvent(event_name="page_view", id=given), _ctx())
    assert row is not None
    assert row["id"] == given


def test_missing_id_is_minted() -> None:
    row = _row(IngestEvent(event_name="page_view"), _ctx())
    assert row is not None
    assert isinstance(row["id"], UUID)


# --- rate limiting ---------------------------------------------------------


def test_rate_limiter_sheds_past_the_window() -> None:
    limiter = _RateLimiter.create()
    session = uuid4()
    assert all(limiter.allow(session) for _ in range(60))
    assert not limiter.allow(session), "61st batch in the window should be shed"


def test_rate_limiter_is_per_session() -> None:
    limiter = _RateLimiter.create()
    noisy, quiet = uuid4(), uuid4()
    for _ in range(60):
        limiter.allow(noisy)
    assert not limiter.allow(noisy)
    assert limiter.allow(quiet), "one loud session must not mute everyone else"


def test_rate_limiter_bookkeeping_is_bounded() -> None:
    """A long-lived process must not leak a deque per session id ever seen."""
    limiter = _RateLimiter.create()
    for _ in range(12_000):
        limiter.allow(uuid4())
    assert len(limiter._hits) <= 10_000
