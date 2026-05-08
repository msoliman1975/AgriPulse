"""Cross-module event subscribers for the notifications module.

When an alert fires (``AlertOpenedV1``), we fan out to every channel
the tenant + user have opted into. PR-B wires only the in-app channel
end-to-end; email/webhook write a ``notification_dispatches`` row with
status ``skipped`` until PR-D / PR-E land.

Why sync SQLAlchemy here: same reason as ``imagery/subscribers.py`` —
the EventBus dispatches sync handlers inline in the publisher's call
stack, which is already inside a running asyncio loop. A small
synchronous engine + session lets the handler run without owning the
loop.

Recipients are resolved by joining the tenant's ``farm_scopes`` table
to ``public.users`` (cross-schema). A single alert produces N inbox
items (one per scoped user) plus M ``notification_dispatches`` rows
(one per channel and user).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.alerts.events import AlertOpenedV1
from app.modules.notifications.events import InboxItemCreatedV1
from app.modules.notifications.smtp import SmtpSendError, send_email
from app.modules.notifications.templates import render
from app.modules.notifications.webhook import WebhookSendError, send_webhook
from app.modules.recommendations.events import RecommendationOpenedV1
from app.shared.db.session import sanitize_tenant_schema
from app.shared.eventbus import EventBus, get_default_bus
from app.shared.realtime import publish_to_user

_log = get_logger(__name__)
_DEFAULT_LOCALE = "en"
# Channels iterated *per user*. The webhook channel is tenant-scoped
# (one URL per tenant) so it runs once per alert, outside this loop.
_PER_USER_CHANNELS = ("in_app", "email")
_KNOWN_CHANNELS = ("in_app", "email", "webhook")

_sync_engine = None
_sync_factory: sessionmaker[Session] | None = None


def _session_factory() -> sessionmaker[Session]:
    """Lazy singleton sessionmaker.

    Uses ``NullPool`` so every handler call gets a fresh connection.
    The handler runs at most a few times per second; we trade pool
    reuse for the guarantee that a previous handler's transaction
    state never leaks into the next one. Pooling caused intermittent
    "current transaction is aborted" failures in tests when one test
    ended cleanly but its connection still carried a stale tx flag.
    """
    global _sync_engine, _sync_factory
    if _sync_factory is None:
        settings = get_settings()
        _sync_engine = create_engine(
            str(settings.database_sync_url),
            poolclass=NullPool,
            future=True,
        )
        _sync_factory = sessionmaker(bind=_sync_engine, autoflush=False, future=True)
    return _sync_factory


def _resolve_tenant_id(session: Session, schema_name: str) -> UUID | None:
    row = session.execute(
        text("SELECT id FROM public.tenants WHERE schema_name = :s"),
        {"s": schema_name},
    ).first()
    return row.id if row is not None else None


def _load_block_and_farm(
    session: Session, *, block_id: UUID, farm_id: UUID
) -> dict[str, Any] | None:
    """Pull block.code + farm.code + farm.name. Both rows are committed
    before the publishing transaction (blocks and farms are not touched
    by the alerts engine), so the sync handler's separate connection
    can read them.
    """
    row = (
        session.execute(
            text(
                "SELECT b.code AS block_code, f.code AS farm_code, f.name AS farm_name "
                "FROM blocks b JOIN farms f ON f.id = b.farm_id "
                "WHERE b.id = :bid AND f.id = :fid AND b.deleted_at IS NULL"
            ),
            {"bid": block_id, "fid": farm_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def _load_default_rule(session: Session, rule_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT name_en, name_ar FROM public.default_rules "
                "WHERE code = :c AND deleted_at IS NULL"
            ),
            {"c": rule_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def _load_recipients(session: Session, *, farm_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]:
    """Users with a non-soft-deleted farm_scope on this farm.

    Joins through `tenant_memberships` (the FK target of farm_scopes)
    and then `users` / `user_preferences` for notification preferences
    and locale. Restricts to memberships in the target tenant — a user
    may have memberships across multiple tenants.
    """
    rows = (
        session.execute(
            text(
                """
                SELECT u.id AS user_id,
                       u.email,
                       COALESCE(up.language, 'en') AS locale,
                       COALESCE(
                           up.notification_channels,
                           ARRAY['in_app','email']::text[]
                       ) AS notification_channels
                FROM public.farm_scopes fs
                JOIN public.tenant_memberships tm ON tm.id = fs.membership_id
                JOIN public.users u ON u.id = tm.user_id
                LEFT JOIN public.user_preferences up ON up.user_id = u.id
                WHERE fs.farm_id = :fid
                  AND fs.revoked_at IS NULL
                  AND tm.tenant_id = :tid
                  AND tm.status = 'active'
                """
            ),
            {"fid": farm_id, "tid": tenant_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _load_webhook_target(session: Session, tenant_id: UUID) -> tuple[str | None, str | None]:
    """Return the tenant's ``(webhook_endpoint_url, kms_key)`` pair.

    A NULL endpoint means webhooks are not configured; the caller
    treats that as a ``skipped`` dispatch. The kms_key is consumed by
    the webhook channel to derive the signing secret.
    """
    row = session.execute(
        text(
            "SELECT webhook_endpoint_url, webhook_signing_secret_kms_key "
            "FROM public.tenant_settings WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    ).first()
    if row is None:
        return None, None
    return row.webhook_endpoint_url, row.webhook_signing_secret_kms_key


def _load_tenant_channels(session: Session, tenant_id: UUID) -> list[str]:
    row = session.execute(
        text(
            "SELECT alert_notification_channels FROM public.tenant_settings "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    ).first()
    if row is None or row.alert_notification_channels is None:
        return ["in_app", "email"]
    return list(row.alert_notification_channels)


def _load_template(
    session: Session, *, template_code: str, locale: str, channel: str
) -> dict[str, Any] | None:
    for try_locale in (locale, _DEFAULT_LOCALE):
        row = (
            session.execute(
                text(
                    "SELECT subject, body, body_html, version "
                    "FROM public.notification_templates "
                    "WHERE template_code = :c AND locale = :l AND channel = :ch "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"c": template_code, "l": try_locale, "ch": channel},
            )
            .mappings()
            .first()
        )
        if row is not None:
            return dict(row)
    return None


def _build_render_ctx(
    *,
    alert: dict[str, Any],
    rule: dict[str, Any] | None,
    locale: str,
    tenant_id: UUID,
) -> dict[str, Any]:
    """Variables exposed to the template renderer.

    Uses _ar fields when the user's locale is ``ar``; otherwise _en.
    Webhook channel reads ``signal_snapshot_json`` and the structured
    fields directly.
    """
    is_ar = locale == "ar"
    severity_label = (
        {
            "info": "Info",
            "warning": "Warning",
            "critical": "Critical",
        }
        .get(alert["severity"], alert["severity"])
        .upper()
    )
    diagnosis = alert.get("diagnosis_ar") if is_ar else alert.get("diagnosis_en")
    prescription = alert.get("prescription_ar") if is_ar else alert.get("prescription_en")
    rule_name = (
        (rule.get("name_ar") if is_ar else rule.get("name_en"))
        if rule is not None
        else alert["rule_code"]
    ) or alert["rule_code"]
    return {
        "tenant_id": str(tenant_id),
        "alert_id": str(alert["alert_id"]),
        "block_id": str(alert["block_id"]),
        "block_code": alert.get("block_code"),
        "farm_id": str(alert["farm_id"]),
        "farm_name": alert.get("farm_name"),
        "rule_code": alert["rule_code"],
        "rule_name": rule_name,
        "severity": alert["severity"],
        "severity_label": severity_label,
        "diagnosis": diagnosis or "",
        "prescription": prescription or "",
        "fired_at": alert["created_at"].isoformat() if alert.get("created_at") else "",
        "signal_snapshot_json": json.dumps(alert.get("signal_snapshot") or {}),
        "link_url": f"/alerts/{alert['farm_id']}?alert={alert['alert_id']}",
    }


def _insert_dispatch(
    session: Session,
    *,
    alert_id: UUID | None = None,
    recommendation_id: UUID | None = None,
    template_code: str,
    locale: str,
    channel: str,
    recipient_user_id: UUID | None,
    recipient_address: str | None,
    status: str,
    rendered_subject: str | None,
    rendered_body: str | None,
    error: str | None,
) -> bool:
    # Wrap the INSERT in a SAVEPOINT so a partial-UNIQUE collision only
    # rolls back the inner transaction. Without this, a constraint
    # violation aborts the outer transaction and every subsequent query
    # fails with "current transaction is aborted". This matters when
    # the handler runs twice for the same source row (e.g. duplicate
    # subscriber registration in tests, or re-evaluation of a still-
    # active rule/tree before the prior row is resolved).
    if (alert_id is None) == (recommendation_id is None):
        raise ValueError("exactly one of alert_id / recommendation_id must be set")
    sp = session.begin_nested()
    try:
        session.execute(
            text(
                """
                INSERT INTO notification_dispatches (
                    alert_id, recommendation_id, template_code, locale, channel,
                    recipient_user_id, recipient_address,
                    status, rendered_subject, rendered_body, error,
                    sent_at
                ) VALUES (
                    :alert_id, :rec_id, :code, :loc, :chan,
                    :uid, :addr,
                    :status, :rs, :rb, :err,
                    CASE WHEN :status = 'sent' THEN now() ELSE NULL END
                )
                """
            ),
            {
                "alert_id": alert_id,
                "rec_id": recommendation_id,
                "code": template_code,
                "loc": locale,
                "chan": channel,
                "uid": recipient_user_id,
                "addr": recipient_address,
                "status": status,
                "rs": rendered_subject,
                "rb": rendered_body,
                "err": error,
            },
        )
        sp.commit()
    except IntegrityError as exc:
        sp.rollback()
        msg = str(exc)
        if (
            "uq_notification_dispatches_alert_chan_user_active" in msg
            or "uq_notification_dispatches_rec_chan_user_active" in msg
        ):
            return False
        raise
    return True


def _insert_inbox_item(
    session: Session,
    *,
    user_id: UUID,
    alert_id: UUID | None = None,
    recommendation_id: UUID | None = None,
    severity: str | None,
    title: str,
    body: str,
    link_url: str | None,
) -> UUID:
    if (alert_id is None) == (recommendation_id is None):
        raise ValueError("exactly one of alert_id / recommendation_id must be set")
    item_id = uuid4()
    session.execute(
        text(
            """
            INSERT INTO in_app_inbox (
                id, user_id, alert_id, recommendation_id, severity, title, body, link_url,
                created_at, updated_at
            ) VALUES (:id, :uid, :alert_id, :rec_id, :sev, :title, :body, :link, now(), now())
            """
        ),
        {
            "id": item_id,
            "uid": user_id,
            "alert_id": alert_id,
            "rec_id": recommendation_id,
            "sev": severity,
            "title": title,
            "body": body,
            "link": link_url,
        },
    )
    return item_id


def _dispatch_webhook_once(
    session: Session,
    *,
    event: AlertOpenedV1,
    tenant_channels: list[str],
    tenant_id: UUID,
    alert: dict[str, Any],
    rule: dict[str, Any] | None,
) -> None:
    """Single per-alert webhook dispatch.

    Records ``skipped`` when the tenant has disabled the channel, has
    no URL, or has no signing secret available; ``failed`` when the
    template is missing or the HTTP send fails; ``sent`` on 2xx.
    """
    if "webhook" not in tenant_channels:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=None,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="channel disabled by tenant",
        )
        return

    webhook_url, kms_key = _load_webhook_target(session, tenant_id)
    webhook_secret = _resolve_webhook_secret(kms_key)
    template = _load_template(
        session, template_code="alert_opened", locale=_DEFAULT_LOCALE, channel="webhook"
    )
    if template is None:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=webhook_url,
            status="failed",
            rendered_subject=None,
            rendered_body=None,
            error="template not found",
        )
        return

    ctx = _build_render_ctx(alert=alert, rule=rule, locale=_DEFAULT_LOCALE, tenant_id=tenant_id)
    _send_webhook_channel(
        session,
        event=event,
        locale=_DEFAULT_LOCALE,
        body_template=template,
        ctx=ctx,
        url=webhook_url,
        secret=webhook_secret,
    )


def _send_webhook_channel(
    session: Session,
    *,
    event: AlertOpenedV1,
    locale: str,
    body_template: dict[str, Any],
    ctx: dict[str, Any],
    url: str | None,
    secret: str | None,
) -> None:
    """POST the alert payload to the tenant's webhook URL.

    Skips if the tenant has no URL configured or if the dev secret is
    blank. Records ``failed`` rows on transport / non-2xx errors so an
    operator reading the dispatch log can see why.
    """
    from uuid import uuid4

    if not url:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=None,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="tenant has no webhook_endpoint_url",
        )
        return

    if not secret:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=url,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="no signing secret configured (KMS not wired and webhook_dev_secret empty)",
        )
        return

    # The webhook body is the structured event itself, not the rendered
    # template. We render the template's body to keep parity with the
    # other channels' audit trail (so an operator sees the same
    # rendered text everywhere) but the wire bytes are the JSON below.
    rendered = render(body_template["body"], ctx)
    delivery_id = uuid4()
    payload = {
        "event": "alert.opened",
        "delivery_id": str(delivery_id),
        "tenant_id": ctx.get("tenant_id"),
        "alert_id": str(event.alert_id),
        "block_id": str(event.block_id),
        "farm_id": ctx.get("farm_id"),
        "rule_code": event.rule_code,
        "severity": event.severity,
        "fired_at": event.created_at.isoformat(),
        "signal_snapshot": event.signal_snapshot or {},
    }

    try:
        result = send_webhook(
            url=url,
            secret=secret,
            event_name="alert.opened",
            delivery_id=delivery_id,
            body=payload,
        )
    except WebhookSendError as exc:
        _log.warning(
            "webhook_send_failed",
            alert_id=str(event.alert_id),
            url=url,
            error=str(exc),
        )
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=url,
            status="failed",
            rendered_subject=None,
            rendered_body=rendered,
            error=str(exc)[:1000],
        )
        return

    _insert_dispatch(
        session,
        alert_id=event.alert_id,
        template_code="alert_opened",
        locale=locale,
        channel="webhook",
        recipient_user_id=None,
        recipient_address=url,
        status="sent",
        rendered_subject=f"HTTP {result.status_code}",
        rendered_body=rendered,
        error=None,
    )


def _resolve_webhook_secret(kms_key: str | None) -> str | None:
    """Resolve the per-tenant HMAC secret.

    Production: ``kms_key`` names a KMS key; a future enhancement will
    plumb a KMS client here. Dev / CI: fall back to
    ``settings.webhook_dev_secret`` so local stacks can sign payloads
    without a KMS dependency. An empty dev secret returns ``None`` so
    the caller skips the dispatch with a clear error.
    """
    settings = get_settings()
    secret = settings.webhook_dev_secret
    if not secret:
        return None
    # Bind kms_key into the derived secret so two tenants with the
    # same dev fallback still get distinct signatures. Production
    # replaces this with a real KMS-derived key.
    if kms_key:
        return f"{secret}::{kms_key}"
    return secret


def _dispatch_channel_for_user(
    session: Session,
    *,
    event: AlertOpenedV1,
    user: dict[str, Any],
    channel: str,
    locale: str,
    effective_channels: list[str],
    tenant_id: UUID,
    alert: dict[str, Any],
    rule: dict[str, Any] | None,
) -> InboxItemCreatedV1 | None:
    """Run the per-(user, channel) leg of the fan-out.

    Returns the inbox event when a row was inserted (in_app channel
    only) so the caller can publish it to SSE after commit.
    """
    if channel not in effective_channels:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel=channel,
            recipient_user_id=user["user_id"],
            recipient_address=user.get("email") if channel == "email" else None,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="channel disabled by tenant or user",
        )
        return None

    template = _load_template(session, template_code="alert_opened", locale=locale, channel=channel)
    if template is None:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel=channel,
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="failed",
            rendered_subject=None,
            rendered_body=None,
            error="template not found",
        )
        return None

    ctx = _build_render_ctx(alert=alert, rule=rule, locale=locale, tenant_id=tenant_id)
    subject = render(template["subject"], ctx)
    body = render(template["body"], ctx)

    if channel == "in_app":
        item_id = _insert_inbox_item(
            session,
            user_id=user["user_id"],
            alert_id=event.alert_id,
            severity=alert["severity"],
            title=subject,
            body=body,
            link_url=ctx["link_url"],
        )
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="in_app",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="sent",
            rendered_subject=subject,
            rendered_body=body,
            error=None,
        )
        return InboxItemCreatedV1(
            inbox_item_id=item_id,
            user_id=user["user_id"],
            tenant_id=tenant_id,
            alert_id=event.alert_id,
            severity=alert["severity"],
            title=subject,
            body=body,
            link_url=ctx["link_url"],
            created_at=event.created_at,
        )

    # email
    _send_email_channel(
        session,
        event=event,
        user=user,
        locale=locale,
        subject=subject,
        body=body,
        body_html=template.get("body_html"),
    )
    return None


def _send_email_channel(
    session: Session,
    *,
    event: AlertOpenedV1,
    user: dict[str, Any],
    locale: str,
    subject: str,
    body: str,
    body_html: str | None,
) -> None:
    """Send the alert email via SMTP and record the dispatch.

    Skips with a descriptive status when the user has no email
    address. Failures from the SMTP layer become ``status='failed'``
    rows so an operator can read the error string later.
    """
    address = user.get("email")
    if not address:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error="user has no email address",
        )
        return

    try:
        send_email(
            to_address=address,
            subject=subject,
            body_text=body,
            body_html=body_html,
        )
    except SmtpSendError as exc:
        _log.warning(
            "email_send_failed",
            alert_id=str(event.alert_id),
            user_id=str(user["user_id"]),
            error=str(exc),
        )
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=address,
            status="failed",
            rendered_subject=subject,
            rendered_body=body,
            error=str(exc)[:1000],
        )
        return

    _insert_dispatch(
        session,
        alert_id=event.alert_id,
        template_code="alert_opened",
        locale=locale,
        channel="email",
        recipient_user_id=user["user_id"],
        recipient_address=address,
        status="sent",
        rendered_subject=subject,
        rendered_body=body,
        error=None,
    )


def _on_alert_opened(event: AlertOpenedV1) -> None:
    """Fan out an opened alert to every (user, channel) pair the tenant
    has subscribed to.
    """
    schema = event.tenant_schema
    if schema is None:
        _log.warning("alert_opened_missing_tenant_schema", alert_id=str(event.alert_id))
        return
    if event.farm_id is None:
        _log.warning("alert_opened_missing_farm_id", alert_id=str(event.alert_id))
        return
    try:
        sanitize_tenant_schema(schema)
    except ValueError:
        _log.warning("alert_opened_invalid_tenant_schema", schema=schema)
        return

    factory = _session_factory()
    bus = get_default_bus()
    with factory() as session:
        session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        tenant_id = _resolve_tenant_id(session, schema)
        if tenant_id is None:
            _log.warning("alert_opened_tenant_not_found", schema=schema)
            return

        # Build the alert dict from the event payload — the alerts row
        # itself isn't committed yet on this separate connection.
        names = _load_block_and_farm(session, block_id=event.block_id, farm_id=event.farm_id) or {}
        alert: dict[str, Any] = {
            "alert_id": event.alert_id,
            "block_id": event.block_id,
            "farm_id": event.farm_id,
            "rule_code": event.rule_code,
            "severity": event.severity,
            "diagnosis_en": event.diagnosis_en,
            "diagnosis_ar": event.diagnosis_ar,
            "prescription_en": event.prescription_en,
            "prescription_ar": event.prescription_ar,
            "signal_snapshot": event.signal_snapshot,
            "created_at": event.created_at,
            "block_code": names.get("block_code"),
            "farm_code": names.get("farm_code"),
            "farm_name": names.get("farm_name"),
        }

        rule = _load_default_rule(session, event.rule_code)
        tenant_channels = _load_tenant_channels(session, tenant_id)
        recipients = _load_recipients(session, farm_id=event.farm_id, tenant_id=tenant_id)

        if not recipients:
            _log.info(
                "alert_opened_no_recipients",
                alert_id=str(event.alert_id),
                farm_id=str(event.farm_id),
            )
            session.commit()
            return

        inbox_events: list[InboxItemCreatedV1] = []
        for user in recipients:
            user_channels = list(user.get("notification_channels") or ["in_app"])
            effective = [c for c in tenant_channels if c in user_channels and c in _KNOWN_CHANNELS]
            locale = user.get("locale") or _DEFAULT_LOCALE
            for channel in _PER_USER_CHANNELS:
                inbox = _dispatch_channel_for_user(
                    session,
                    event=event,
                    user=user,
                    channel=channel,
                    locale=locale,
                    effective_channels=effective,
                    tenant_id=tenant_id,
                    alert=alert,
                    rule=rule,
                )
                if inbox is not None:
                    inbox_events.append(inbox)

        _dispatch_webhook_once(
            session,
            event=event,
            tenant_channels=tenant_channels,
            tenant_id=tenant_id,
            alert=alert,
            rule=rule,
        )
        session.commit()

    # Publish per-inbox events outside the tenant transaction so SSE
    # subscribers never see an event whose row hasn't committed. Two
    # dispatch paths:
    #   * Eventbus — for any future in-process consumer.
    #   * Redis — for the SSE endpoint to fan out to connected clients.
    for ev in inbox_events:
        bus.publish(ev)
        publish_to_user(
            tenant_id=ev.tenant_id,
            user_id=ev.user_id,
            payload={
                "id": str(ev.inbox_item_id),
                "alert_id": str(ev.alert_id) if ev.alert_id else None,
                "severity": ev.severity,
                "title": ev.title,
                "body": ev.body,
                "link_url": ev.link_url,
                "created_at": ev.created_at.isoformat(),
            },
        )


# =====================================================================
# Recommendations fan-out — parallel to the alerts handler above.
# =====================================================================


def _load_decision_tree(session: Session, tree_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT name_en, name_ar FROM public.decision_trees "
                "WHERE code = :c AND deleted_at IS NULL"
            ),
            {"c": tree_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def _build_render_ctx_for_recommendation(
    *,
    rec: dict[str, Any],
    tree: dict[str, Any] | None,
    locale: str,
    tenant_id: UUID,
) -> dict[str, Any]:
    """Variables exposed to the recommendation template renderer."""
    is_ar = locale == "ar"
    severity_label = (
        {
            "info": "Info",
            "warning": "Warning",
            "critical": "Critical",
        }
        .get(rec["severity"], rec["severity"])
        .upper()
    )
    text_localized = rec.get("text_ar") if is_ar else rec.get("text_en")
    tree_name = (
        (tree.get("name_ar") if is_ar else tree.get("name_en"))
        if tree is not None
        else rec["tree_code"]
    ) or rec["tree_code"]
    return {
        "tenant_id": str(tenant_id),
        "recommendation_id": str(rec["recommendation_id"]),
        "block_id": str(rec["block_id"]),
        "block_code": rec.get("block_code"),
        "farm_id": str(rec["farm_id"]),
        "farm_name": rec.get("farm_name"),
        "tree_code": rec["tree_code"],
        "tree_name": tree_name,
        "action_type": rec["action_type"],
        "severity": rec["severity"],
        "severity_label": severity_label,
        "text": text_localized or "",
        "fired_at": rec["created_at"].isoformat() if rec.get("created_at") else "",
        "evaluation_snapshot_json": json.dumps(rec.get("evaluation_snapshot") or {}),
        "link_url": f"/recommendations/{rec['farm_id']}?recommendation={rec['recommendation_id']}",
    }


def _dispatch_rec_channel_for_user(
    session: Session,
    *,
    event: RecommendationOpenedV1,
    user: dict[str, Any],
    channel: str,
    locale: str,
    effective_channels: list[str],
    tenant_id: UUID,
    rec: dict[str, Any],
    tree: dict[str, Any] | None,
) -> InboxItemCreatedV1 | None:
    """Per-(user, channel) fan-out for a recommendation. Returns the
    inbox event when in_app inserted a row so the caller can publish to
    SSE after commit.
    """
    if channel not in effective_channels:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=locale,
            channel=channel,
            recipient_user_id=user["user_id"],
            recipient_address=user.get("email") if channel == "email" else None,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="channel disabled by tenant or user",
        )
        return None

    template = _load_template(
        session, template_code="recommendation_opened", locale=locale, channel=channel
    )
    if template is None:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=locale,
            channel=channel,
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="failed",
            rendered_subject=None,
            rendered_body=None,
            error="template not found",
        )
        return None

    ctx = _build_render_ctx_for_recommendation(
        rec=rec, tree=tree, locale=locale, tenant_id=tenant_id
    )
    subject = render(template["subject"], ctx)
    body = render(template["body"], ctx)

    if channel == "in_app":
        item_id = _insert_inbox_item(
            session,
            user_id=user["user_id"],
            recommendation_id=event.recommendation_id,
            severity=rec["severity"],
            title=subject,
            body=body,
            link_url=ctx["link_url"],
        )
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=locale,
            channel="in_app",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="sent",
            rendered_subject=subject,
            rendered_body=body,
            error=None,
        )
        return InboxItemCreatedV1(
            inbox_item_id=item_id,
            user_id=user["user_id"],
            tenant_id=tenant_id,
            recommendation_id=event.recommendation_id,
            severity=rec["severity"],
            title=subject,
            body=body,
            link_url=ctx["link_url"],
            created_at=event.created_at,
        )

    # email
    _send_rec_email_channel(
        session,
        event=event,
        user=user,
        locale=locale,
        subject=subject,
        body=body,
        body_html=template.get("body_html"),
    )
    return None


def _send_rec_email_channel(
    session: Session,
    *,
    event: RecommendationOpenedV1,
    user: dict[str, Any],
    locale: str,
    subject: str,
    body: str,
    body_html: str | None,
) -> None:
    address = user.get("email")
    if not address:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error="user has no email address",
        )
        return

    try:
        send_email(
            to_address=address,
            subject=subject,
            body_text=body,
            body_html=body_html,
        )
    except SmtpSendError as exc:
        _log.warning(
            "rec_email_send_failed",
            recommendation_id=str(event.recommendation_id),
            user_id=str(user["user_id"]),
            error=str(exc),
        )
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=address,
            status="failed",
            rendered_subject=subject,
            rendered_body=body,
            error=str(exc)[:1000],
        )
        return

    _insert_dispatch(
        session,
        recommendation_id=event.recommendation_id,
        template_code="recommendation_opened",
        locale=locale,
        channel="email",
        recipient_user_id=user["user_id"],
        recipient_address=address,
        status="sent",
        rendered_subject=subject,
        rendered_body=body,
        error=None,
    )


def _dispatch_rec_webhook_once(
    session: Session,
    *,
    event: RecommendationOpenedV1,
    tenant_channels: list[str],
    tenant_id: UUID,
    rec: dict[str, Any],
    tree: dict[str, Any] | None,
) -> None:
    """Single per-recommendation webhook dispatch, mirroring the alerts
    webhook path. The body is the structured JSON event itself; we
    render the template's body for parity in the dispatch audit log.
    """
    if "webhook" not in tenant_channels:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=None,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="channel disabled by tenant",
        )
        return

    webhook_url, kms_key = _load_webhook_target(session, tenant_id)
    webhook_secret = _resolve_webhook_secret(kms_key)
    template = _load_template(
        session,
        template_code="recommendation_opened",
        locale=_DEFAULT_LOCALE,
        channel="webhook",
    )
    if template is None:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=webhook_url,
            status="failed",
            rendered_subject=None,
            rendered_body=None,
            error="template not found",
        )
        return

    ctx = _build_render_ctx_for_recommendation(
        rec=rec, tree=tree, locale=_DEFAULT_LOCALE, tenant_id=tenant_id
    )
    if not webhook_url:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=None,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="tenant has no webhook_endpoint_url",
        )
        return
    if not webhook_secret:
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=webhook_url,
            status="skipped",
            rendered_subject=None,
            rendered_body=None,
            error="no signing secret configured (KMS not wired and webhook_dev_secret empty)",
        )
        return

    rendered = render(template["body"], ctx)
    delivery_id = uuid4()
    payload = {
        "event": "recommendation.opened",
        "delivery_id": str(delivery_id),
        "tenant_id": ctx.get("tenant_id"),
        "recommendation_id": str(event.recommendation_id),
        "block_id": str(event.block_id),
        "farm_id": str(event.farm_id),
        "tree_code": event.tree_code,
        "tree_version": event.tree_version,
        "action_type": event.action_type,
        "severity": event.severity,
        "fired_at": event.created_at.isoformat(),
        "evaluation_snapshot": event.evaluation_snapshot or {},
    }

    try:
        result = send_webhook(
            url=webhook_url,
            secret=webhook_secret,
            event_name="recommendation.opened",
            delivery_id=delivery_id,
            body=payload,
        )
    except WebhookSendError as exc:
        _log.warning(
            "rec_webhook_send_failed",
            recommendation_id=str(event.recommendation_id),
            url=webhook_url,
            error=str(exc),
        )
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=_DEFAULT_LOCALE,
            channel="webhook",
            recipient_user_id=None,
            recipient_address=webhook_url,
            status="failed",
            rendered_subject=None,
            rendered_body=rendered,
            error=str(exc)[:1000],
        )
        return

    _insert_dispatch(
        session,
        recommendation_id=event.recommendation_id,
        template_code="recommendation_opened",
        locale=_DEFAULT_LOCALE,
        channel="webhook",
        recipient_user_id=None,
        recipient_address=webhook_url,
        status="sent",
        rendered_subject=f"HTTP {result.status_code}",
        rendered_body=rendered,
        error=None,
    )


def _on_recommendation_opened(event: RecommendationOpenedV1) -> None:
    """Fan out an opened recommendation to every (user, channel) pair
    the tenant has subscribed to. Mirrors ``_on_alert_opened``."""
    schema = event.tenant_schema
    if schema is None:
        _log.warning(
            "recommendation_opened_missing_tenant_schema",
            recommendation_id=str(event.recommendation_id),
        )
        return
    try:
        sanitize_tenant_schema(schema)
    except ValueError:
        _log.warning("recommendation_opened_invalid_tenant_schema", schema=schema)
        return

    factory = _session_factory()
    bus = get_default_bus()
    with factory() as session:
        session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        tenant_id = _resolve_tenant_id(session, schema)
        if tenant_id is None:
            _log.warning("recommendation_opened_tenant_not_found", schema=schema)
            return

        names = (
            _load_block_and_farm(session, block_id=event.block_id, farm_id=event.farm_id) or {}
        )
        rec: dict[str, Any] = {
            "recommendation_id": event.recommendation_id,
            "block_id": event.block_id,
            "farm_id": event.farm_id,
            "tree_code": event.tree_code,
            "tree_version": event.tree_version,
            "action_type": event.action_type,
            "severity": event.severity,
            "text_en": event.text_en,
            "text_ar": event.text_ar,
            "evaluation_snapshot": event.evaluation_snapshot,
            "created_at": event.created_at,
            "block_code": names.get("block_code"),
            "farm_code": names.get("farm_code"),
            "farm_name": names.get("farm_name"),
        }

        tree = _load_decision_tree(session, event.tree_code)
        tenant_channels = _load_tenant_channels(session, tenant_id)
        recipients = _load_recipients(session, farm_id=event.farm_id, tenant_id=tenant_id)

        if not recipients:
            _log.info(
                "recommendation_opened_no_recipients",
                recommendation_id=str(event.recommendation_id),
                farm_id=str(event.farm_id),
            )
            session.commit()
            return

        inbox_events: list[InboxItemCreatedV1] = []
        for user in recipients:
            user_channels = list(user.get("notification_channels") or ["in_app"])
            effective = [
                c for c in tenant_channels if c in user_channels and c in _KNOWN_CHANNELS
            ]
            locale = user.get("locale") or _DEFAULT_LOCALE
            for channel in _PER_USER_CHANNELS:
                inbox = _dispatch_rec_channel_for_user(
                    session,
                    event=event,
                    user=user,
                    channel=channel,
                    locale=locale,
                    effective_channels=effective,
                    tenant_id=tenant_id,
                    rec=rec,
                    tree=tree,
                )
                if inbox is not None:
                    inbox_events.append(inbox)

        _dispatch_rec_webhook_once(
            session,
            event=event,
            tenant_channels=tenant_channels,
            tenant_id=tenant_id,
            rec=rec,
            tree=tree,
        )
        session.commit()

    for ev in inbox_events:
        bus.publish(ev)
        publish_to_user(
            tenant_id=ev.tenant_id,
            user_id=ev.user_id,
            payload={
                "id": str(ev.inbox_item_id),
                "recommendation_id": (
                    str(ev.recommendation_id) if ev.recommendation_id else None
                ),
                "severity": ev.severity,
                "title": ev.title,
                "body": ev.body,
                "link_url": ev.link_url,
                "created_at": ev.created_at.isoformat(),
            },
        )


def register_subscribers(bus: EventBus) -> None:
    """Register notifications' cross-module event handlers.

    Idempotent — safe to call multiple times (tests do this when they
    import the module repeatedly across the same process).
    """
    has_alert_handler = any(
        sub.handler is _on_alert_opened for sub in bus.handlers_for(AlertOpenedV1)
    )
    if not has_alert_handler:
        bus.register(AlertOpenedV1, _on_alert_opened, mode="sync")

    has_rec_handler = any(
        sub.handler is _on_recommendation_opened
        for sub in bus.handlers_for(RecommendationOpenedV1)
    )
    if not has_rec_handler:
        bus.register(RecommendationOpenedV1, _on_recommendation_opened, mode="sync")
