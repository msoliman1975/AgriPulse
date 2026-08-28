"""The API's first unauthenticated routes.

Mounted at /api/v1/public/trial. Every other route in this service sits
behind `requires_capability`; these three cannot, because at this point in
the flow there is no user, no token and no tenant.

That makes three rules non-negotiable here:

  * **No account enumeration.** `POST /signups` answers 202 with the same
    body for a new address, a known address and a customer's address.
  * **Rate limits are the door.** There is no auth to lean on.
  * **Nothing is provisioned.** These routes write a queue row and send
    mail. A tenant appears only when a platform admin approves.

The prefix is registered in `app.shared.auth.middleware._PUBLIC_PREFIXES`,
which is what lets a request past the bearer-token check.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.billing.errors import SignupNotFoundError
from app.modules.billing.service import TrialService
from app.modules.billing.turnstile import verify_token
from app.shared.db.session import get_admin_db_session
from app.shared.ratelimit import check_and_increment

router = APIRouter(prefix="/api/v1/public/trial", tags=["public-trial"])

_log = get_logger(__name__)


class TrialSignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    organisation: str = Field(min_length=2, max_length=160)
    country: str | None = Field(default=None, max_length=2)
    phone: str | None = Field(default=None, max_length=32)
    locale: Literal["en", "ar"] = "en"
    accepts_terms: bool = Field(description="Must be true. The form cannot submit without it.")
    turnstile_token: str | None = Field(
        default=None,
        description="Cloudflare Turnstile response. Required when a secret is configured.",
    )


class TrialSignupAccepted(BaseModel):
    """The one answer this endpoint gives.

    Identical for every input, so nothing here can be used to find out
    whether an address or a company is already a customer.
    """

    status: Literal["accepted"] = "accepted"
    message: str = "Check your email to confirm your address."


class TrialStatusResponse(BaseModel):
    """What the visitor's own status page shows.

    Deliberately thin. It carries no email address, no internal id and no
    reviewer, because the handle it is keyed on travels in a URL.
    """

    state: str
    message: str
    organisation: str
    submitted_at: str | None = None


async def _service(
    session: AsyncSession = Depends(get_admin_db_session),
) -> TrialService:
    return TrialService(public_session=session)


def _client_ip(request: Request) -> str | None:
    """The visitor's address, trusting the proxy header the ingress sets.

    Behind the cluster ingress `request.client.host` is the proxy, so every
    visitor would share one rate-limit bucket.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post(
    "/signups",
    response_model=TrialSignupAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a trial workspace. Unauthenticated.",
)
async def create_signup(
    payload: TrialSignupRequest,
    request: Request,
    service: TrialService = Depends(_service),
) -> TrialSignupAccepted:
    settings = get_settings()

    if not payload.accepts_terms:
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Terms not accepted",
            detail="The terms must be accepted to request a trial.",
            type_="https://agripulse.cloud/problems/trial-terms-required",
        )

    ip = _client_ip(request)
    domain = payload.email.split("@")[-1].lower()

    if ip:
        by_ip = await check_and_increment(
            key=f"trial:signup:ip:{ip}",
            limit=settings.trial_signups_per_ip_per_hour,
            window_seconds=3600,
        )
        if not by_ip.allowed:
            raise _too_many(by_ip.retry_after_seconds)

    by_domain = await check_and_increment(
        key=f"trial:signup:domain:{domain}",
        limit=settings.trial_signups_per_domain_per_day,
        window_seconds=86400,
    )
    if not by_domain.allowed:
        raise _too_many(by_domain.retry_after_seconds)

    if not await verify_token(token=payload.turnstile_token, remote_ip=ip):
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Challenge failed",
            detail="The anti-robot check did not pass. Please try again.",
            type_="https://agripulse.cloud/problems/turnstile-failed",
        )

    # `get_admin_db_session` already opened the transaction and commits
    # when the request ends. Opening a second one here would raise.
    await service.register_signup(
        full_name=payload.full_name,
        email=str(payload.email),
        organisation=payload.organisation,
        country=payload.country,
        phone=payload.phone,
        locale=payload.locale,
        source_ip=ip,
        user_agent=request.headers.get("user-agent"),
    )

    return TrialSignupAccepted()


@router.get(
    "/verify",
    summary="Confirm an email address and place the request in the review queue.",
)
async def verify(
    token: Annotated[str, Query(min_length=16, max_length=256)],
    service: TrialService = Depends(_service),
) -> RedirectResponse:
    """Verifies, then redirects to the marketing site.

    A redirect rather than JSON because a person clicks this link in a mail
    client. The outcome rides in the query string so the site can show the
    right words without a second call.
    """
    settings = get_settings()
    base = settings.trial_marketing_base_url.rstrip("/")

    try:
        signup = await service.verify(token=token)
    except SignupNotFoundError:
        return RedirectResponse(url=f"{base}/trial/status?state=invalid", status_code=303)

    handle = signup.status_handle
    return RedirectResponse(
        url=f"{base}/trial/status?h={handle}&state={signup.status}",
        status_code=303,
    )


@router.get(
    "/status/{handle}",
    response_model=TrialStatusResponse,
    summary="State of one trial request, for the visitor's own status page.",
)
async def signup_status(
    handle: str,
    service: TrialService = Depends(_service),
) -> TrialStatusResponse:
    try:
        signup = await service.get_by_handle(handle)
    except SignupNotFoundError as exc:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Request not found",
            detail="No trial request matches this link.",
            type_="https://agripulse.cloud/problems/trial-signup-not-found",
        ) from exc

    return TrialStatusResponse(
        state=signup.status,
        message=_VISITOR_MESSAGES.get(signup.status, "Your request is with our team."),
        organisation=signup.organisation,
        submitted_at=signup.created_at.isoformat() if signup.created_at else None,
    )


def _too_many(retry_after: int) -> APIError:
    return APIError(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too many requests",
        detail="Too many trial requests from here. Try again later.",
        type_="https://agripulse.cloud/problems/trial-rate-limited",
        extras={"retry_after_seconds": retry_after},
    )


#: What the visitor reads for each state. Kept beside the endpoint so the
#: status page and the emails cannot drift into telling different stories.
_VISITOR_MESSAGES: dict[str, str] = {
    "pending_verification": "Check your email and confirm your address.",
    "awaiting_approval": (
        "Your address is confirmed. We review new workspaces within one working day."
    ),
    "paused": (
        "We are at capacity for new workspaces. Your request is held and we will "
        "write as soon as a place opens."
    ),
    "approved": "Approved. Your workspace is being set up now.",
    "provisioning": "Your workspace is being set up now.",
    "provisioned": "Your workspace is ready. Check your email to set a password.",
    "rejected": "We are not able to open a workspace for this request.",
    "routed_to_existing": (
        "Your organisation already uses AgriPulse. Ask your administrator for an invitation."
    ),
    "failed": "Something went wrong while setting up your workspace. Our team has been alerted.",
    "expired": "This confirmation link expired. Please request a trial again.",
}
