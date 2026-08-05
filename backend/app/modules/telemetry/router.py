"""Telemetry ingest route. Mounted under /api/v1 by the app factory.

    POST /api/v1/telemetry/events   -> 202 Accepted, always

Requires a valid bearer token: the path is deliberately NOT in
`AuthMiddleware._PUBLIC_PATHS`, because identity is stamped from the JWT. That
also means pre-auth events (the login funnel) cannot be reported yet — an open
question in the plan, deferred to Phase B.

No capability gate. Every authenticated user emits telemetry about their own
session; `platform.read_usage` (TEL-7) gates *reading* it, which is where the
privilege actually matters.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.telemetry.schemas import IngestBatch, IngestResult
from app.modules.telemetry.service import get_telemetry_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])

# 64 KB. A 50-event batch is ~10 KB; this is headroom, not a target. Checked
# against Content-Length so an oversized body is shed before it is parsed.
MAX_BODY_BYTES = 64 * 1024

_log = get_logger(__name__)


@router.post(
    "/events",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a batch of product-telemetry events",
)
async def ingest_events(
    request: Request,
    batch: IngestBatch,
    context: RequestContext = Depends(get_current_context),
    # `usage_events` lives in `public`, so this uses the admin (public-schema)
    # session rather than the tenant-scoped one. A farm-scoped user has no
    # tenant search_path to write through, and telemetry is cross-tenant by
    # design.
    session: AsyncSession = Depends(get_admin_db_session),
) -> IngestResult:
    """Accept a client batch. Answers 202 whatever happens.

    The status code carries no signal on purpose: a client must never retry, log
    a console error, or surface a failure to the user because telemetry did not
    land. The response body carries the counts for tests and debugging.
    """
    settings = get_settings()
    if not settings.telemetry_ingest_enabled:
        return IngestResult(discarded=True, reason="disabled")

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        _log.info("telemetry_body_too_large", declared_bytes=int(declared))
        return IngestResult(discarded=True, reason="too_large")

    service = get_telemetry_service()
    try:
        return await service.ingest(session=session, context=context, batch=batch)
    except Exception as exc:  # telemetry must not break the app
        # Deliberately swallowed. An ingest failure is logged and forgotten;
        # raising would surface a 500 in the SPA's network tab for a request the
        # user never made, and #332's lesson is that swallowing must at least be
        # observable. Hence the log line and the reason on the response.
        await session.rollback()
        _log.warning(
            "telemetry_ingest_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            session_id=str(batch.session_id),
            events=len(batch.events),
        )
        return IngestResult(discarded=True, reason="error")
