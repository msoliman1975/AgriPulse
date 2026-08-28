"""The trial emails.

Five of the nine messages in the design belong to this slice — the four
trial-clock messages (D-7, D-1, trial ended, and the archive warning) arrive
with the trial clock.

Copy rules that apply to all of them: say what happened and what to do next,
name no date we cannot keep, and never apologise for a decision. The
templates carry no branding markup yet; they are text, and text arrives.

Sends go through the notifications SMTP client. Delivery failure is logged
and swallowed at the call site — a signup must not be lost because a mail
server was briefly down, and the row's state is the record either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.notifications.smtp import SmtpSendError, send_email

_log = get_logger(__name__)


@dataclass(frozen=True)
class TrialEmail:
    subject: str
    body: str


def verify_address(*, full_name: str, verify_url: str) -> TrialEmail:
    return TrialEmail(
        subject="Confirm your email to request an AgriPulse trial",
        body=(
            f"Hello {full_name},\n\n"
            "Confirm this address to send your trial request to our team:\n\n"
            f"{verify_url}\n\n"
            "The link works for the next two days. If you did not ask for a "
            "trial, ignore this message and nothing happens.\n\n"
            "AgriPulse\n"
        ),
    )


def under_review(*, full_name: str, status_url: str) -> TrialEmail:
    return TrialEmail(
        subject="Your AgriPulse trial request is with our team",
        body=(
            f"Hello {full_name},\n\n"
            "Your address is confirmed. We review new workspaces within one "
            "working day and will write as soon as yours is ready.\n\n"
            f"You can check the status here at any time:\n{status_url}\n\n"
            "AgriPulse\n"
        ),
    )


def still_reviewing(*, full_name: str, status_url: str) -> TrialEmail:
    return TrialEmail(
        subject="Still working on your AgriPulse trial",
        body=(
            f"Hello {full_name},\n\n"
            "Your trial request is still with us and has not been forgotten. "
            "We will write the moment it is ready.\n\n"
            f"Status:\n{status_url}\n\n"
            "AgriPulse\n"
        ),
    )


def approved(*, full_name: str, set_password_url: str, trial_days: int) -> TrialEmail:
    return TrialEmail(
        subject="Your AgriPulse workspace is ready",
        body=(
            f"Hello {full_name},\n\n"
            "Your workspace is ready. Set a password and sign in:\n\n"
            f"{set_password_url}\n\n"
            f"The trial runs for {trial_days} days. You will find a sample "
            "farm already in place, so you can look around before drawing "
            "your own.\n\n"
            "AgriPulse\n"
        ),
    )


def paused(*, full_name: str, status_url: str) -> TrialEmail:
    return TrialEmail(
        subject="Your AgriPulse trial request is held",
        body=(
            f"Hello {full_name},\n\n"
            "We are at capacity for new trial workspaces at the moment, so "
            "your request is held rather than closed. We will write as soon "
            "as a place opens.\n\n"
            f"Status:\n{status_url}\n\n"
            "AgriPulse\n"
        ),
    )


def rejected(*, full_name: str, reason: str, contact_url: str) -> TrialEmail:
    return TrialEmail(
        subject="About your AgriPulse trial request",
        body=(
            f"Hello {full_name},\n\n"
            "We are not able to open a trial workspace for this request.\n\n"
            f"{reason}\n\n"
            f"If you think this is wrong, write to us here:\n{contact_url}\n\n"
            "AgriPulse\n"
        ),
    )


def routed_to_existing(*, full_name: str, organisation_hint: str) -> TrialEmail:
    return TrialEmail(
        subject="Your organisation already uses AgriPulse",
        body=(
            f"Hello {full_name},\n\n"
            f"{organisation_hint} already has an AgriPulse workspace. Ask "
            "your administrator to send you an invitation — that puts you in "
            "the same workspace as your colleagues, with the farms already "
            "set up.\n\n"
            "AgriPulse\n"
        ),
    )


def send(*, to_address: str, email: TrialEmail) -> bool:
    """Best-effort send. Returns False on failure instead of raising.

    The caller has already written the state change. Losing the mail is
    recoverable — a platform admin can resend — but losing the row is not.
    """
    try:
        send_email(to_address=to_address, subject=email.subject, body_text=email.body)
    except SmtpSendError as exc:
        _log.warning("trial_email_failed", to=to_address, subject=email.subject, error=str(exc))
        return False
    return True


def status_url(handle: str) -> str:
    base = get_settings().trial_marketing_base_url.rstrip("/")
    return f"{base}/trial/status?h={handle}"


def verify_url(token: str) -> str:
    """The link points at the API, not the site.

    The endpoint does the work and then redirects to the site, so a visitor
    who opens the link on a phone with no JavaScript still gets verified.
    """
    base = get_settings().trial_api_base_url.rstrip("/")
    return f"{base}/api/v1/public/trial/verify?token={token}"


def contact_url() -> str:
    base = get_settings().trial_marketing_base_url.rstrip("/")
    return f"{base}/contact"
