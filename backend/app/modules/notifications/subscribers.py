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
from datetime import UTC, datetime
from html import escape
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
from app.modules.notifications.presentation import (
    absolute_url,
    action_type_label,
    callout_html,
    format_timestamp,
    preferences_url,
    severity_colours,
    severity_label,
    titled_block_html,
    titled_block_text,
    titled_paragraph_html,
)
from app.modules.notifications.push import PushSendError, send_push
from app.modules.notifications.sink import (
    SUPPRESSED_REASON,
    activate_for_tenant,
    is_suppressed,
    resets_outbound,
)
from app.modules.notifications.smtp import SmtpSendError, send_email
from app.modules.notifications.templates import SafeMarkup, render
from app.modules.notifications.webhook import WebhookSendError, send_webhook
from app.modules.recommendations.events import (
    EvaluationRunFinishedV1,
    RecommendationOpenedV1,
)
from app.modules.scouting.events import ScoutingVisitAssignedV1
from app.shared.db.session import sanitize_tenant_schema
from app.shared.eventbus import EventBus, get_default_bus
from app.shared.finding_evidence import evidence_rows, evidence_text
from app.shared.realtime import publish_to_user

_log = get_logger(__name__)
_DEFAULT_LOCALE = "en"
# Channels iterated *per user*. The webhook channel is tenant-scoped
# (one URL per tenant) so it runs once per alert, outside this loop.
# `push` joins the per-user fan-out: it targets a person's devices, unlike
# webhook which is tenant-scoped. Opt-in still runs through the existing
# user_preferences.notification_channels array.
_PER_USER_CHANNELS = ("in_app", "email", "push")
_KNOWN_CHANNELS = ("in_app", "email", "webhook", "push")

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


def _activate_sink_for_schema(session: Session, schema: str) -> None:
    """Decide outbound suppression for a handler that has only the schema.

    ``_on_scouting_visit_assigned`` never needed the tenant id: it targets one
    named assignee and never consults the tenant's channel settings. That is
    precisely why it is the leak a channel-level filter would miss, so it
    resolves the tenant purely to decide suppression.
    """
    tenant_id = _resolve_tenant_id(session, schema)
    if tenant_id is not None:
        activate_for_tenant(session, tenant_id)


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
                "SELECT b.code AS block_code, f.code AS farm_code, "
                "       f.name AS farm_name, f.name_ar AS farm_name_ar "
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
    """Resolve a display name for an alert's `rule_code`.

    Stage 2 of the rules sunset dropped `public.default_rules`. After
    that drop:
      * Tree-sourced alerts have `rule_code = tree:<tree_code>:<leaf>`;
        we look the tree up in `public.decision_trees` by code and
        return its `name_en`/`name_ar` if found.
      * Legacy rule-sourced alerts whose `rule_code` lacks the `tree:`
        prefix (rows that pre-date PR-F) — there's no catalog table to
        look up anymore; we return `None` and the renderer falls back
        to the alert's `diagnosis_en` as the title.
    """
    if rule_code.startswith("tree:"):
        # Format: "tree:<tree_code>:<leaf_node_id>".
        parts = rule_code.split(":", 2)
        if len(parts) >= 2:
            tree_code = parts[1]
            row = (
                session.execute(
                    text(
                        "SELECT name_en, name_ar, description_en, description_ar "
                        "FROM public.decision_trees "
                        "WHERE code = :c AND deleted_at IS NULL"
                    ),
                    {"c": tree_code},
                )
                .mappings()
                .first()
            )
            return dict(row) if row is not None else None
    return None


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


# Values a template can drop straight in. The renderer is a flat
# substituter with no loops (templates.py), so a variable-length list has
# to arrive already marked up. Both forms are built from the same rows so
# the HTML and the plain-text part of one email cannot disagree.
_EVIDENCE_LINE = (
    "<tr>"
    '<td style="padding:6px 0;border-bottom:1px solid #f0eee7;'
    'font-size:12px;color:#5e7669;">{label}</td>'
    '<td style="padding:6px 0;border-bottom:1px solid #f0eee7;'
    'font-size:14px;color:#2e4a3d;">{value}</td>'
    "</tr>"
)


def _evidence_html(snapshot: dict[str, Any] | None, *, locale: str) -> str:
    """The measured-values table, or "" when the walk resolved nothing.

    Empty rather than an empty table: a template that always prints a
    heading would show "What we measured" above nothing at all, which
    reads as a bug rather than as an absence.
    """
    rows = evidence_rows(snapshot, locale=locale)
    if not rows:
        return ""
    body = "".join(
        _EVIDENCE_LINE.format(label=escape(label), value=escape(value)) for label, value in rows
    )
    return SafeMarkup(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        f' border="0">{body}</table>'
    )


def _evidence_text_block(snapshot: dict[str, Any] | None, *, locale: str) -> str:
    """The same rows as indented plain-text lines, for the text part."""
    rows = evidence_rows(snapshot, locale=locale)
    if not rows:
        return ""
    return "\n".join(f"  {label}: {value}" for label, value in rows)


# Headings for the two sections the reader was missing. Kept here rather
# than in the templates because the sections are built in Python (a flat
# renderer cannot hide a heading whose body is empty) and a heading that
# lived apart from the thing it heads would be free to drift from it.
_WHY_TITLE = {"en": "Why this tree ran", "ar": "لماذا ظهر هذا"}
_MEASURED_TITLE = {"en": "What we measured", "ar": "ما الذي قِيس"}
_ACTION_TITLE = {"en": "What to do", "ar": "الإجراء المطلوب"}


def _finding_blocks(
    *,
    description: str | None,
    snapshot: dict[str, Any] | None,
    locale: str,
    prescription: str | None = None,
) -> dict[str, Any]:
    """The optional sections of a message body, each whole or absent.

    Returns one HTML variable and one text variable that a template
    places once. Building the concatenation here rather than in the
    template is what keeps an absent section from leaving its heading, or
    a blank gap, behind: a template that placed three separate variables
    would print two empty lines whenever two of the three were empty.

    ``prescription`` is separate from the other two because it is the
    line a person acts on, so it is rendered as the tinted callout and
    stays last. Tree-sourced alerts never set it — the leaf writes a
    diagnosis and no prescription — which is why "WHAT TO DO" was
    printing above nothing on every alert this platform has sent.
    """
    rtl = locale == "ar"
    why_title = _WHY_TITLE.get(locale, _WHY_TITLE["en"])
    measured_title = _MEASURED_TITLE.get(locale, _MEASURED_TITLE["en"])
    action_title = _ACTION_TITLE.get(locale, _ACTION_TITLE["en"])
    table = _evidence_html(snapshot, locale=locale)

    html_parts = [
        titled_paragraph_html(why_title, description or "", rtl=rtl),
        titled_block_html(measured_title, table, rtl=rtl),
    ]
    text_parts = [
        titled_block_text(why_title.upper(), description or ""),
        titled_block_text(measured_title.upper(), _evidence_text_block(snapshot, locale=locale)),
    ]
    action_html = callout_html(action_title, prescription, rtl=rtl) if prescription else ""
    action_text = titled_block_text(action_title.upper(), prescription or "")

    # The spacing contract for the plain-text parts: a non-empty block
    # ends with a blank line, an empty one is the empty string. So the
    # template places these back to back with no newlines of its own and
    # gets correct spacing whichever combination is present. Putting the
    # separator in the template instead is what leaves a three-newline
    # gap when the block between them turns out to be empty.
    extras = "\n".join(part for part in text_parts if part)
    return {
        "extra_blocks_html": SafeMarkup("".join(part for part in html_parts if part)),
        "extra_blocks_text": f"{extras}\n" if extras else "",
        "action_block_html": SafeMarkup(action_html),
        "action_block_text": f"{action_text}\n" if action_text else "",
    }


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
    severity = alert["severity"]
    fg, bg, border = severity_colours(severity)
    diagnosis = alert.get("diagnosis_ar") if is_ar else alert.get("diagnosis_en")
    prescription = alert.get("prescription_ar") if is_ar else alert.get("prescription_en")
    rule_name = (
        (rule.get("name_ar") if is_ar else rule.get("name_en"))
        if rule is not None
        else alert["rule_code"]
    ) or alert["rule_code"]
    rule_description = (
        (rule.get("description_ar") if is_ar else rule.get("description_en"))
        if rule is not None
        else None
    )
    link_url = f"/action-center/{alert['farm_id']}?kind=alert&item={alert['alert_id']}"
    return {
        "tenant_id": str(tenant_id),
        "alert_id": str(alert["alert_id"]),
        "block_id": str(alert["block_id"]),
        "block_code": alert.get("block_code"),
        "farm_id": str(alert["farm_id"]),
        # The email is already rendered per recipient locale, so the name is
        # resolved here rather than shipped as a pair the template would have
        # to choose between.
        "farm_name": ((alert.get("farm_name_ar") if is_ar else None) or alert.get("farm_name")),
        "rule_code": alert["rule_code"],
        "rule_name": rule_name,
        "severity": severity,
        "severity_label": severity_label(severity, locale),
        "severity_color": fg,
        "severity_bg": bg,
        "severity_border": border,
        "diagnosis": diagnosis or "",
        "prescription": prescription or "",
        # The two fields the reader was missing. `rule_description` is the
        # tree author's own paragraph on what this tree looks for, which
        # until now was written at authoring time and shown on no surface
        # at all. `evidence` is what the walk actually resolved.
        "rule_description": rule_description or "",
        "evidence": evidence_text(alert.get("signal_snapshot"), locale=locale),
        "evidence_html": _evidence_html(alert.get("signal_snapshot"), locale=locale),
        "evidence_text_block": _evidence_text_block(alert.get("signal_snapshot"), locale=locale),
        **_finding_blocks(
            description=rule_description,
            snapshot=alert.get("signal_snapshot"),
            locale=locale,
            prescription=prescription,
        ),
        "fired_at": alert["created_at"].isoformat() if alert.get("created_at") else "",
        "fired_at_display": format_timestamp(alert.get("created_at"), locale),
        "signal_snapshot_json": json.dumps(alert.get("signal_snapshot") or {}),
        # The Action Center is the queue now; /alerts is delisted. `item`
        # opens this row rather than dropping the reader into a farm-wide
        # list, which is what the old link did — /alerts never read its
        # `?alert=` parameter.
        "link_url": link_url,
        # Email has no origin to resolve a relative path against. The bell
        # keeps `link_url`; only the email templates read this one.
        "link_url_abs": absolute_url(link_url),
        "preferences_url": preferences_url(),
    }


def _insert_dispatch(
    session: Session,
    *,
    alert_id: UUID | None = None,
    recommendation_id: UUID | None = None,
    visit_id: UUID | None = None,
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
    # Mirrors the table's CHECK: a dispatch names exactly one source.
    sources = sum(x is not None for x in (alert_id, recommendation_id, visit_id))
    if sources != 1:
        raise ValueError("exactly one of alert_id / recommendation_id / visit_id must be set")
    sp = session.begin_nested()
    try:
        session.execute(
            text(
                """
                INSERT INTO notification_dispatches (
                    alert_id, recommendation_id, visit_id, template_code, locale, channel,
                    recipient_user_id, recipient_address,
                    status, rendered_subject, rendered_body, error,
                    sent_at
                ) VALUES (
                    :alert_id, :rec_id, :visit_id, :code, :loc, :chan,
                    :uid, :addr,
                    :status, :rs, :rb, :err,
                    CASE WHEN :status = 'sent' THEN now() ELSE NULL END
                )
                """
            ),
            {
                "alert_id": alert_id,
                "rec_id": recommendation_id,
                "visit_id": visit_id,
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
        # Sub-block grid cell for cell-scoped tree alerts (per-cell P2).
        "cell_id": str(event.cell_id) if event.cell_id else None,
        "farm_id": ctx.get("farm_id"),
        "rule_code": event.rule_code,
        "severity": event.severity,
        "fired_at": event.created_at.isoformat(),
        "signal_snapshot": event.signal_snapshot or {},
    }

    if is_suppressed():
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
            rendered_body=rendered,
            error=SUPPRESSED_REASON,
        )
        return

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

    if channel == "push":
        _send_push_channel(
            session,
            event=event,
            user=user,
            locale=locale,
            subject=subject,
            body=body,
            severity=str(alert["severity"]),
        )
        return None

    # email. `body_html` has to be rendered like the other two — it was
    # being passed through raw, which nobody saw only because every seeded
    # row had body_html NULL. `escape=True` because the substituted values
    # (farm name, diagnosis, a rule name an operator typed) land inside
    # markup here, unlike the text body.
    _send_email_channel(
        session,
        event=event,
        user=user,
        locale=locale,
        subject=subject,
        body=body,
        body_html=render(template.get("body_html"), ctx, escape=True) or None,
    )
    return None


def _live_device_tokens(session: Session, *, user_id: UUID) -> list[str]:
    """Every device this user still has registered."""
    rows = session.execute(
        text(
            "SELECT token FROM device_tokens "
            "WHERE user_id = :uid AND revoked_at IS NULL AND deleted_at IS NULL"
        ),
        {"uid": user_id},
    ).all()
    return [r[0] for r in rows]


def _send_push_channel(
    session: Session,
    *,
    event: AlertOpenedV1,
    user: dict[str, Any],
    locale: str,
    subject: str,
    body: str,
    severity: str,
) -> None:
    """Push the alert to every device this user has registered.

    One dispatch row per device, because "did it reach them" is a per-device
    question: a scout whose phone is off but whose tablet is on has been
    reached, and a row per device is the only way to say so honestly.

    A token FCM reports as unregistered is revoked rather than retried — an
    uninstalled app is permanent, and left alone it would fail on every
    subsequent alert forever.
    """
    tokens = _live_device_tokens(session, user_id=user["user_id"])
    if not tokens:
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="push",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error="no registered devices",
        )
        return

    data = {
        "type": "alert",
        "alert_id": str(event.alert_id),
        "block_id": str(event.block_id),
        "severity": severity,
        "deep_link": f"agripulse://alerts/{event.alert_id}",
    }
    for token in tokens:
        status_value, error = "sent", None
        try:
            if is_suppressed():
                status_value, error = "skipped", SUPPRESSED_REASON
            else:
                result = send_push(token=token, title=subject, body=body, data=data)
                if result.skipped:
                    status_value, error = "skipped", "push channel disabled"
        except PushSendError as exc:
            status_value, error = "failed", str(exc)
            if exc.unregistered:
                session.execute(
                    text(
                        "UPDATE device_tokens SET revoked_at = now() "
                        "WHERE token = :t AND revoked_at IS NULL"
                    ),
                    {"t": token},
                )
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="push",
            recipient_user_id=user["user_id"],
            # The device, not an address — enough to identify which handset
            # without storing a full token in a table operators read.
            recipient_address=f"device:{token[-8:]}",
            status=status_value,
            rendered_subject=subject,
            rendered_body=body,
            error=error,
        )


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

    if is_suppressed():
        _insert_dispatch(
            session,
            alert_id=event.alert_id,
            template_code="alert_opened",
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=address,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error=SUPPRESSED_REASON,
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


@resets_outbound
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
        activate_for_tenant(session, tenant_id)

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
            "farm_name_ar": names.get("farm_name_ar"),
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
        # One sweep opens one alert per block. Sending each of those on its
        # own is how a 23-block farm produced 23 identical emails with a
        # different number in the subject. Inside a run, the per-user
        # channels wait: `_on_evaluation_run_finished` below sends ONE
        # message per (farm, tree, leaf, severity) when the run ends.
        #
        # The webhook is deliberately not held back. It is machine-read,
        # one payload per alert is the contract receivers already parse,
        # and nobody's inbox is the worse for it.
        if event.run_id is None:
            for user in recipients:
                user_channels = list(user.get("notification_channels") or ["in_app"])
                effective = [
                    c for c in tenant_channels if c in user_channels and c in _KNOWN_CHANNELS
                ]
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
        else:
            _log.debug(
                "alert_opened_deferred_to_run_digest",
                alert_id=str(event.alert_id),
                run_id=str(event.run_id),
            )

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


def _load_decision_tree(
    session: Session, tree_code: str, *, tenant_id: UUID
) -> dict[str, Any] | None:
    # After PR-A the catalog mixes platform + tenant trees; the same
    # `code` can resolve to two different rows in different tenant
    # scopes, so we must scope by tenant_id to find the same row that
    # was evaluated. Platform trees (tenant_id IS NULL) are visible to
    # every tenant.
    row = (
        session.execute(
            text(
                "SELECT name_en, name_ar, description_en, description_ar "
                "FROM public.decision_trees "
                "WHERE code = :c AND deleted_at IS NULL "
                "  AND (tenant_id IS NULL OR tenant_id = :tid)"
            ),
            {"c": tree_code, "tid": tenant_id},
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
    severity = rec["severity"]
    fg, bg, border = severity_colours(severity)
    text_localized = rec.get("text_ar") if is_ar else rec.get("text_en")
    tree_name = (
        (tree.get("name_ar") if is_ar else tree.get("name_en"))
        if tree is not None
        else rec["tree_code"]
    ) or rec["tree_code"]
    tree_description = (
        (tree.get("description_ar") if is_ar else tree.get("description_en"))
        if tree is not None
        else None
    )
    link_url = (
        f"/action-center/{rec['farm_id']}?kind=recommendation&item={rec['recommendation_id']}"
    )
    return {
        "tenant_id": str(tenant_id),
        "recommendation_id": str(rec["recommendation_id"]),
        "block_id": str(rec["block_id"]),
        "block_code": rec.get("block_code"),
        "farm_id": str(rec["farm_id"]),
        "farm_name": ((rec.get("farm_name_ar") if is_ar else None) or rec.get("farm_name")),
        "tree_code": rec["tree_code"],
        "tree_name": tree_name,
        "action_type": rec["action_type"],
        "action_type_label": action_type_label(rec["action_type"], locale),
        "severity": severity,
        "severity_label": severity_label(severity, locale),
        "severity_color": fg,
        "severity_bg": bg,
        "severity_border": border,
        "text": text_localized or "",
        # Same two additions as the alert context, from the same source of
        # truth, so a recommendation and an alert describe themselves the
        # same way on every channel.
        "tree_description": tree_description or "",
        "evidence": evidence_text(rec.get("evaluation_snapshot"), locale=locale),
        "evidence_html": _evidence_html(rec.get("evaluation_snapshot"), locale=locale),
        "evidence_text_block": _evidence_text_block(rec.get("evaluation_snapshot"), locale=locale),
        **_finding_blocks(
            description=tree_description,
            snapshot=rec.get("evaluation_snapshot"),
            locale=locale,
        ),
        "fired_at": rec["created_at"].isoformat() if rec.get("created_at") else "",
        "fired_at_display": format_timestamp(rec.get("created_at"), locale),
        "evaluation_snapshot_json": json.dumps(rec.get("evaluation_snapshot") or {}),
        "link_url": link_url,
        "link_url_abs": absolute_url(link_url),
        "preferences_url": preferences_url(),
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

    # email. Same as the alert path: render body_html rather than passing
    # the template through raw, and escape the substituted values because
    # they land inside markup here.
    _send_rec_email_channel(
        session,
        event=event,
        user=user,
        locale=locale,
        subject=subject,
        body=body,
        body_html=render(template.get("body_html"), ctx, escape=True) or None,
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

    if is_suppressed():
        _insert_dispatch(
            session,
            recommendation_id=event.recommendation_id,
            template_code="recommendation_opened",
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=address,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error=SUPPRESSED_REASON,
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
        # Sub-block grid cell for cell-scoped recs (per-cell P2).
        "cell_id": str(event.cell_id) if event.cell_id else None,
        "farm_id": str(event.farm_id),
        "tree_code": event.tree_code,
        "tree_version": event.tree_version,
        "action_type": event.action_type,
        "severity": event.severity,
        "fired_at": event.created_at.isoformat(),
        "evaluation_snapshot": event.evaluation_snapshot or {},
    }

    if is_suppressed():
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
            rendered_body=rendered,
            error=SUPPRESSED_REASON,
        )
        return

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


@resets_outbound
def _on_recommendation_opened(event: RecommendationOpenedV1) -> None:
    """Fan out an opened recommendation to every (user, channel) pair
    the tenant has subscribed to. Mirrors ``_on_alert_opened``."""
    # Per-cell P2: a cell-scoped tree opens one rec per grid cell. Suppress the
    # per-cell events here to avoid an N-notification flood — the sweep emits a
    # single block-level digest event (cell_id=None, zone_count set) that this
    # same handler fans out as one "N zones flagged" notification. The per-cell
    # events still reach the map / recs page via their own reads.
    if event.cell_id is not None:
        return

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
        activate_for_tenant(session, tenant_id)

        names = _load_block_and_farm(session, block_id=event.block_id, farm_id=event.farm_id) or {}
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
            "farm_name_ar": names.get("farm_name_ar"),
        }

        tree = _load_decision_tree(session, event.tree_code, tenant_id=tenant_id)
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
        # Same hold as the alert path, and for the larger flood: one sweep
        # opened 287 recommendations on a single day, which went out as 574
        # emails. Inside a run the per-user channels wait for
        # `_on_evaluation_run_finished` to send one message per (farm, tree,
        # leaf, severity). The webhook is not held back — one payload per
        # recommendation is the contract receivers parse.
        if event.run_id is None:
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
        else:
            _log.debug(
                "recommendation_opened_deferred_to_run_digest",
                recommendation_id=str(event.recommendation_id),
                run_id=str(event.run_id),
            )

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
                "recommendation_id": (str(ev.recommendation_id) if ev.recommendation_id else None),
                "severity": ev.severity,
                "title": ev.title,
                "body": ev.body,
                "link_url": ev.link_url,
                "created_at": ev.created_at.isoformat(),
            },
        )


# =====================================================================
# Run digest — one message per (farm, tree, leaf, severity) per run.
#
# A sweep walks every block of every farm and opens one alert per block
# that matches. Fanned out one at a time, a 23-block farm produced 23
# emails whose subjects differed only in the block number. The alerts
# themselves are right and stay one-per-block: the Action Center needs a
# row it can close per block. Only the *telling* is consolidated.
#
# The grouping identity is `alerts.group_key`
# (``<tree>:<leaf>:<action>:<severity>``, built by shared/action_items.py)
# paired with the farm. That is already "same tree, same verdict" — it is
# the key the Action Center groups on — so the digest does not invent a
# second, drifting definition of what counts as the same finding.
# "Same day" comes free: a run happens on one day, and the shortest
# tenant sweep cadence is four hours.
# =====================================================================

# One template family per kind. They render from the same context and
# say the same things; only the noun changes ("alert" / "recommendation")
# and the recommendation's callout carries the leaf's advice rather than
# a prescription the tree never wrote.
_DIGEST_TEMPLATE_CODES = {
    "alert": "alert_digest",
    "recommendation": "recommendation_digest",
}
# Kept as its own name because the alert half shipped with it and the
# dispatch rows already written carry this exact string.
_DIGEST_TEMPLATE_CODE = _DIGEST_TEMPLATE_CODES["alert"]


def _anchor_columns(kind: str, anchor_id: UUID) -> dict[str, UUID]:
    """``{alert_id: ...}`` or ``{recommendation_id: ...}``.

    Both `in_app_inbox` and `notification_dispatches` carry a CHECK that
    exactly one of the two is set, so the digest cannot hard-code either
    now that it serves both kinds. Returning the kwargs rather than a
    column name keeps the call sites reading as ordinary keyword
    arguments.
    """
    key = "alert_id" if kind == "alert" else "recommendation_id"
    return {key: anchor_id}


# How many block codes the subject names before falling back to a count.
# Three fits an email subject at phone width; the full list is always in
# the body underneath.
_DIGEST_SUBJECT_BLOCKS = 3
_DIGEST_BODY_BLOCKS = 40


# Every alert this run opened, folded onto (farm, group_key).
#
# The join runs through `decision_tree_eval_traces` rather than through a
# new column on `alerts`: the trace row already records which run fired
# which alert, which is the exact question being asked, and a second
# place to record it would be a second place for it to be wrong.
#
# `a.created_at >= r.started_at` is what restricts this to alerts the run
# OPENED. A re-fired alert keeps its original created_at and was
# announced when it first opened. Telling somebody again that a block
# they have not closed is still open is not news, and it is what a plain
# "every alert this run touched" query would do on every sweep.
_DIGEST_ROWS = """
SELECT t.farm_id                                          AS farm_id,
       a.group_key                                        AS group_key,
       min(t.tree_code)                                   AS tree_code,
       min(a.severity)                                    AS severity,
       min(a.rule_code)                                   AS rule_code,
       min(a.action_type)                                 AS action_type,
       min(a.diagnosis_en)                                AS diagnosis_en,
       min(a.diagnosis_ar)                                AS diagnosis_ar,
       (array_agg(a.signal_snapshot ORDER BY a.created_at, a.id))[1] AS signal_snapshot,
       (array_agg(a.id ORDER BY a.created_at, a.id))[1]   AS anchor_id,
       min(a.created_at)                                  AS first_created_at,
       count(DISTINCT a.id)                               AS alert_count,
       array_agg(DISTINCT b.code)                         AS block_codes
  FROM decision_tree_eval_traces t
  JOIN decision_tree_eval_runs r ON r.id = t.run_id
  JOIN alerts a  ON a.id = t.alert_id AND a.deleted_at IS NULL
  JOIN blocks b  ON b.id = a.block_id AND b.deleted_at IS NULL
 WHERE t.run_id = :run_id
   AND t.alert_id IS NOT NULL
   AND a.group_key IS NOT NULL
   AND a.created_at >= r.started_at
 GROUP BY t.farm_id, a.group_key
 ORDER BY t.farm_id, a.group_key
"""


# The recommendation half of the same question. Structurally identical
# to `_DIGEST_ROWS`: the run's traces name the rows it opened, the row
# supplies the grouping key and the words, and `created_at >=
# started_at` keeps re-fired rows out.
#
# `r.text_en` rather than `a.diagnosis_en`, and `r.evaluation_snapshot`
# rather than `a.signal_snapshot` — the two tables named the same two
# things differently long before this code existed, and renaming them is
# not this change's job.
_DIGEST_REC_ROWS = """
SELECT t.farm_id                                          AS farm_id,
       r.group_key                                        AS group_key,
       min(t.tree_code)                                   AS tree_code,
       min(r.severity)                                    AS severity,
       min(r.action_type)                                 AS action_type,
       min(r.text_en)                                     AS diagnosis_en,
       min(r.text_ar)                                     AS diagnosis_ar,
       (array_agg(r.evaluation_snapshot ORDER BY r.created_at, r.id))[1]
                                                          AS signal_snapshot,
       (array_agg(r.id ORDER BY r.created_at, r.id))[1]   AS anchor_id,
       min(r.created_at)                                  AS first_created_at,
       count(DISTINCT r.id)                               AS alert_count,
       array_agg(DISTINCT b.code)                         AS block_codes
  FROM decision_tree_eval_traces t
  JOIN decision_tree_eval_runs r2 ON r2.id = t.run_id
  JOIN recommendations r ON r.id = t.recommendation_id AND r.deleted_at IS NULL
  JOIN blocks b ON b.id = r.block_id AND b.deleted_at IS NULL
 WHERE t.run_id = :run_id
   AND t.recommendation_id IS NOT NULL
   AND r.group_key IS NOT NULL
   AND r.group_parent_id IS NULL
   AND r.created_at >= r2.started_at
 GROUP BY t.farm_id, r.group_key
 ORDER BY t.farm_id, r.group_key
"""


def _load_digest_rows(session: Session, run_id: UUID) -> list[dict[str, Any]]:
    """Every group this run opened, alerts and recommendations together.

    Each row carries its own ``kind`` so the caller picks the template
    family without having to remember which query it came from. The two
    queries return the same column names on purpose — everything
    downstream then has one shape to handle.
    """
    rows: list[dict[str, Any]] = []
    for kind, query in (("alert", _DIGEST_ROWS), ("recommendation", _DIGEST_REC_ROWS)):
        for row in session.execute(text(query), {"run_id": run_id}).mappings().all():
            rows.append({**dict(row), "kind": kind})
    return rows


def _load_farm_names(session: Session, farm_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    if not farm_ids:
        return {}
    rows = (
        session.execute(
            text(
                "SELECT id, name, name_ar FROM farms " "WHERE id = ANY(:ids) AND deleted_at IS NULL"
            ),
            {"ids": farm_ids},
        )
        .mappings()
        .all()
    )
    return {row["id"]: dict(row) for row in rows}


def _format_block_list(codes: list[str], limit: int, locale: str) -> str:
    """``011, 012, 013 and 20 more`` — never a bare truncation.

    A list that stops at an ellipsis leaves the reader unable to tell
    three blocks from thirty, which is the one number this message exists
    to carry.
    """
    ordered = sorted(c for c in codes if c)
    if not ordered:
        return ""
    joiner = "، " if locale == "ar" else ", "
    if len(ordered) <= limit:
        return joiner.join(ordered)
    rest = len(ordered) - limit
    tail = f" و{rest} غيرها" if locale == "ar" else f" and {rest} more"
    return joiner.join(ordered[:limit]) + tail


def _block_count_label(count: int, locale: str) -> str:
    """``1 block`` / ``23 blocks`` — Arabic takes its own forms."""
    if locale == "ar":
        if count == 1:
            return "قطعة واحدة"
        if count == 2:
            return "قطعتان"
        if 3 <= count <= 10:
            return f"{count} قطع"
        return f"{count} قطعة"
    return "1 block" if count == 1 else f"{count} blocks"


def _build_digest_ctx(
    *,
    row: dict[str, Any],
    tree: dict[str, Any] | None,
    farm: dict[str, Any] | None,
    locale: str,
    tenant_id: UUID,
) -> dict[str, Any]:
    """Variables the digest templates render.

    Deliberately a superset of the single-alert context's names
    (``severity_label``, ``evidence``, ``link_url_abs`` ...). The two
    template families then read the same variable for the same idea,
    which is what stops one channel's wording drifting from another's.
    """
    is_ar = locale == "ar"
    severity = str(row["severity"])
    fg, bg, border = severity_colours(severity)
    codes = [str(c) for c in (row.get("block_codes") or [])]
    count = int(row["alert_count"])
    tree_name = (
        (tree.get("name_ar") if is_ar else tree.get("name_en")) if tree is not None else None
    ) or str(row["tree_code"])
    tree_description = (
        (tree.get("description_ar") if is_ar else tree.get("description_en"))
        if tree is not None
        else None
    )
    farm_name = (
        ((farm.get("name_ar") if is_ar else None) or farm.get("name")) if farm else None
    ) or ""
    verdict = (row.get("diagnosis_ar") if is_ar else row.get("diagnosis_en")) or ""
    snapshot = row.get("signal_snapshot")
    # The queue, filtered to this farm's alerts — every block named in the
    # message is in that list. There is no per-group deep link to send
    # them to; `?item=` opens exactly one row, which is the opposite of
    # what the reader of a 23-block message needs.
    link_url = f"/action-center/{row['farm_id']}?kind={row.get('kind') or 'alert'}"
    action = row.get("action_type")
    return {
        "tenant_id": str(tenant_id),
        "farm_id": str(row["farm_id"]),
        "farm_name": farm_name,
        "tree_code": str(row["tree_code"]),
        "tree_name": tree_name,
        "tree_description": tree_description or "",
        # The alert family calls the same two things `rule_*`. Both names
        # are published so one template family can be read against the
        # other without a mental translation step.
        "rule_name": tree_name,
        "rule_description": tree_description or "",
        "group_key": str(row["group_key"]),
        "severity": severity,
        "severity_label": severity_label(severity, locale),
        "severity_color": fg,
        "severity_bg": bg,
        "severity_border": border,
        "action_type": action or "",
        "action_type_label": action_type_label(action, locale) if action else "",
        "verdict": verdict,
        "diagnosis": verdict,
        "block_count": str(count),
        "block_count_label": _block_count_label(count, locale),
        "block_list": _format_block_list(codes, _DIGEST_SUBJECT_BLOCKS, locale),
        "block_list_full": _format_block_list(codes, _DIGEST_BODY_BLOCKS, locale),
        "evidence": evidence_text(snapshot, locale=locale),
        "evidence_html": _evidence_html(snapshot, locale=locale),
        "evidence_text_block": _evidence_text_block(snapshot, locale=locale),
        **_finding_blocks(description=tree_description, snapshot=snapshot, locale=locale),
        "fired_at": (row["first_created_at"].isoformat() if row.get("first_created_at") else ""),
        "fired_at_display": format_timestamp(row.get("first_created_at"), locale),
        "link_url": link_url,
        "link_url_abs": absolute_url(link_url),
        "preferences_url": preferences_url(),
    }


# ``{column}`` is filled from a two-element literal map below, never from
# anything a caller supplies — a column name cannot be a bind parameter,
# and this is the only reason any SQL in this module is formatted at all.
_MARK_DISPATCH_SQL = """
    UPDATE notification_dispatches
       SET status = :st,
           error = :err,
           sent_at = CASE WHEN :st = 'sent' THEN now() ELSE sent_at END,
           updated_at = now()
     WHERE {column} = :aid
       AND channel = :ch
       AND recipient_user_id = :uid
       AND recipient_address IS NOT DISTINCT FROM :addr
       AND template_code = :tc
       AND status = 'pending'
"""


def _mark_dispatch(
    session: Session,
    *,
    anchor_id: UUID,
    kind: str,
    user_id: UUID,
    address: str | None,
    channel: str,
    status: str,
    error: str | None,
    template_code: str = _DIGEST_TEMPLATE_CODE,
) -> None:
    """Settle a row this module claimed as 'pending'.

    'failed' sits outside the partial UNIQUE's predicate, so a send that
    failed frees the slot and a later run may retry it.

    The anchor lives in ``alert_id`` or ``recommendation_id`` depending on
    the kind — both tables carry a CHECK that exactly one is set — so the
    predicate has to name the same column the claim wrote.
    """
    column = "alert_id" if kind == "alert" else "recommendation_id"
    session.execute(
        text(_MARK_DISPATCH_SQL.format(column=column)),
        {
            "st": status,
            "err": error,
            "aid": anchor_id,
            "ch": channel,
            "uid": user_id,
            "addr": address,
            "tc": template_code,
        },
    )


def _send_digest_email(
    session: Session,
    *,
    anchor_id: UUID,
    kind: str,
    template_code: str,
    user: dict[str, Any],
    locale: str,
    subject: str,
    body: str,
    body_html: str | None,
) -> None:
    """Deliver one consolidated email and record the dispatch.

    The dispatch row is keyed on the anchor alert, so the partial UNIQUE
    on ``(alert_id, channel, recipient_user_id, recipient_address)`` turns
    a second flush of the same run into a no-op instead of a second
    email. That is what lets the run-finished event be published from a
    ``finally`` without anyone being told twice.
    """
    address = user.get("email")
    if not address:
        _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
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

    if is_suppressed():
        _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
            locale=locale,
            channel="email",
            recipient_user_id=user["user_id"],
            recipient_address=address,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error=SUPPRESSED_REASON,
        )
        return

    # Claim the dispatch row BEFORE the SMTP call. If the claim loses to a
    # concurrent flush the message is already somebody else's to send, and
    # sending it here would be the duplicate the claim exists to prevent.
    if not _insert_dispatch(
        session,
        **_anchor_columns(kind, anchor_id),
        template_code=template_code,
        locale=locale,
        channel="email",
        recipient_user_id=user["user_id"],
        recipient_address=address,
        status="pending",
        rendered_subject=subject,
        rendered_body=body,
        error=None,
    ):
        return

    try:
        send_email(to_address=address, subject=subject, body_text=body, body_html=body_html)
    except SmtpSendError as exc:
        _log.warning(
            "digest_email_send_failed",
            anchor_id=str(anchor_id),
            user_id=str(user["user_id"]),
            error=str(exc),
        )
        _mark_dispatch(
            session,
            anchor_id=anchor_id,
            kind=kind,
            user_id=user["user_id"],
            address=address,
            channel="email",
            status="failed",
            error=str(exc)[:1000],
            template_code=template_code,
        )
        return

    _mark_dispatch(
        session,
        anchor_id=anchor_id,
        kind=kind,
        user_id=user["user_id"],
        address=address,
        channel="email",
        status="sent",
        error=None,
        template_code=template_code,
    )


def _send_digest_push(
    session: Session,
    *,
    anchor_id: UUID,
    kind: str,
    template_code: str,
    farm_id: UUID,
    user: dict[str, Any],
    locale: str,
    subject: str,
    body: str,
    severity: str,
) -> None:
    tokens = _live_device_tokens(session, user_id=user["user_id"])
    if not tokens:
        _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
            locale=locale,
            channel="push",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="skipped",
            rendered_subject=subject,
            rendered_body=body,
            error="no registered devices",
        )
        return

    # The handset opens the farm's alert queue, not one alert: this push
    # stands for every block in the group.
    data = {
        "type": template_code,
        "item_id": str(anchor_id),
        "farm_id": str(farm_id),
        "severity": severity,
        "deep_link": f"agripulse://action-center/{farm_id}?kind=alert",
    }
    for token in tokens:
        status_value, error = "sent", None
        try:
            if is_suppressed():
                status_value, error = "skipped", SUPPRESSED_REASON
            else:
                result = send_push(token=token, title=subject, body=body, data=data)
                if result.skipped:
                    status_value, error = "skipped", "push channel disabled"
        except PushSendError as exc:
            status_value, error = "failed", str(exc)
            if exc.unregistered:
                session.execute(
                    text(
                        "UPDATE device_tokens SET revoked_at = now() "
                        "WHERE token = :t AND revoked_at IS NULL"
                    ),
                    {"t": token},
                )
        _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
            locale=locale,
            channel="push",
            recipient_user_id=user["user_id"],
            recipient_address=f"device:{token[-8:]}",
            status=status_value,
            rendered_subject=subject,
            rendered_body=body,
            error=error,
        )


def _dispatch_digest_for_user(
    session: Session,
    *,
    row: dict[str, Any],
    ctx_cache: dict[str, dict[str, Any]],
    user: dict[str, Any],
    channel: str,
    locale: str,
    effective_channels: list[str],
    tenant_id: UUID,
    tree: dict[str, Any] | None,
    farm: dict[str, Any] | None,
) -> InboxItemCreatedV1 | None:
    """Per-(user, channel) leg of one group's consolidated message."""
    anchor_id = row["anchor_id"]
    kind = str(row["kind"])
    template_code = _DIGEST_TEMPLATE_CODES[row["kind"]]
    if channel not in effective_channels:
        _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
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

    template = _load_template(session, template_code=template_code, locale=locale, channel=channel)
    if template is None:
        _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
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

    # One context per locale, not per recipient: every value in it comes
    # from the finding and the reader's language, so a farm with forty
    # viewers would otherwise build the same strings forty times.
    ctx = ctx_cache.get(locale)
    if ctx is None:
        ctx = _build_digest_ctx(row=row, tree=tree, farm=farm, locale=locale, tenant_id=tenant_id)
        ctx_cache[locale] = ctx

    subject = render(template["subject"], ctx)
    body = render(template["body"], ctx)

    if channel == "in_app":
        if not _insert_dispatch(
            session,
            **_anchor_columns(kind, anchor_id),
            template_code=template_code,
            locale=locale,
            channel="in_app",
            recipient_user_id=user["user_id"],
            recipient_address=None,
            status="sent",
            rendered_subject=subject,
            rendered_body=body,
            error=None,
        ):
            # Already in this user's bell from an earlier flush of the
            # same run. Inserting the inbox row anyway would put a second
            # copy of a notification they have read in front of them.
            return None
        item_id = _insert_inbox_item(
            session,
            user_id=user["user_id"],
            **_anchor_columns(kind, anchor_id),
            severity=str(row["severity"]),
            title=subject,
            body=body,
            link_url=ctx["link_url"],
        )
        return InboxItemCreatedV1(
            inbox_item_id=item_id,
            user_id=user["user_id"],
            tenant_id=tenant_id,
            **_anchor_columns(kind, anchor_id),
            severity=str(row["severity"]),
            title=subject,
            body=body,
            link_url=ctx["link_url"],
            created_at=row["first_created_at"],
        )

    if channel == "push":
        _send_digest_push(
            session,
            anchor_id=anchor_id,
            kind=kind,
            template_code=template_code,
            farm_id=row["farm_id"],
            user=user,
            locale=locale,
            subject=subject,
            body=body,
            severity=str(row["severity"]),
        )
        return None

    _send_digest_email(
        session,
        anchor_id=anchor_id,
        kind=kind,
        template_code=template_code,
        user=user,
        locale=locale,
        subject=subject,
        body=body,
        body_html=render(template.get("body_html"), ctx, escape=True) or None,
    )
    return None


@resets_outbound
def _on_evaluation_run_finished(event: EvaluationRunFinishedV1) -> None:
    """Send the consolidated messages for every alert one run opened."""
    schema = event.tenant_schema
    try:
        sanitize_tenant_schema(schema)
    except ValueError:
        _log.warning("run_finished_invalid_tenant_schema", schema=schema)
        return

    factory = _session_factory()
    bus = get_default_bus()
    inbox_events: list[InboxItemCreatedV1] = []
    groups_sent = 0
    with factory() as session:
        session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        _activate_sink_for_schema(session, schema)
        tenant_id = _resolve_tenant_id(session, schema)
        if tenant_id is None:
            _log.warning("run_finished_tenant_not_found", schema=schema)
            return

        rows = _load_digest_rows(session, event.run_id)
        if not rows:
            session.commit()
            return

        tenant_channels = _load_tenant_channels(session, tenant_id)
        farms = _load_farm_names(session, sorted({r["farm_id"] for r in rows}))
        # Recipients are a per-farm answer and a run touches few farms, so
        # they are resolved once per farm rather than once per group.
        recipients_by_farm: dict[UUID, list[dict[str, Any]]] = {}
        trees: dict[str, dict[str, Any] | None] = {}

        for row in rows:
            farm_id = row["farm_id"]
            if farm_id not in recipients_by_farm:
                recipients_by_farm[farm_id] = _load_recipients(
                    session, farm_id=farm_id, tenant_id=tenant_id
                )
            recipients = recipients_by_farm[farm_id]
            if not recipients:
                continue

            tree_code = str(row["tree_code"])
            if tree_code not in trees:
                trees[tree_code] = _load_decision_tree(session, tree_code, tenant_id=tenant_id)

            ctx_cache: dict[str, dict[str, Any]] = {}
            for user in recipients:
                user_channels = list(user.get("notification_channels") or ["in_app"])
                effective = [
                    c for c in tenant_channels if c in user_channels and c in _KNOWN_CHANNELS
                ]
                locale = user.get("locale") or _DEFAULT_LOCALE
                for channel in _PER_USER_CHANNELS:
                    inbox = _dispatch_digest_for_user(
                        session,
                        row=row,
                        ctx_cache=ctx_cache,
                        user=user,
                        channel=channel,
                        locale=locale,
                        effective_channels=effective,
                        tenant_id=tenant_id,
                        tree=trees[tree_code],
                        farm=farms.get(farm_id),
                    )
                    if inbox is not None:
                        inbox_events.append(inbox)
            groups_sent += 1

        session.commit()

    _log.info(
        "alert_run_digest_sent",
        run_id=str(event.run_id),
        tenant_schema=schema,
        kind=event.kind,
        groups=groups_sent,
        inbox_items=len(inbox_events),
    )

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
        sub.handler is _on_recommendation_opened for sub in bus.handlers_for(RecommendationOpenedV1)
    )
    if not has_rec_handler:
        bus.register(RecommendationOpenedV1, _on_recommendation_opened, mode="sync")
    if not any(
        sub.handler is _on_scouting_visit_assigned
        for sub in bus.handlers_for(ScoutingVisitAssignedV1)
    ):
        bus.register(ScoutingVisitAssignedV1, _on_scouting_visit_assigned, mode="sync")

    # The other half of the alert fan-out. `_on_alert_opened` holds the
    # per-user channels back for any alert opened inside an evaluation
    # run; this is what then sends them, consolidated. Without it those
    # alerts reach the webhook and nothing else.
    if not any(
        sub.handler is _on_evaluation_run_finished
        for sub in bus.handlers_for(EvaluationRunFinishedV1)
    ):
        bus.register(EvaluationRunFinishedV1, _on_evaluation_run_finished, mode="sync")


# ---------- Scouting: announce an assigned visit ----------------------------


@resets_outbound
def _on_scouting_visit_assigned(event: ScoutingVisitAssignedV1) -> None:
    """Tell one scout that a visit is theirs.

    Unlike the alert and recommendation fan-outs this targets exactly one
    person — the assignee — rather than everyone scoped to the farm. A visit is
    an instruction to a named individual, and broadcasting it would train the
    rest of the farm to ignore push.

    Push only. The alert/recommendation that spawned the visit already produced
    an inbox item; a second in-app row for the same underlying event would
    double-count the bell badge for everyone reading it.
    """
    schema = event.tenant_schema
    if schema is None:
        _log.warning("visit_assigned_missing_tenant_schema", visit_id=str(event.visit_id))
        return
    try:
        sanitize_tenant_schema(schema)
    except ValueError:
        _log.warning("visit_assigned_invalid_tenant_schema", schema=schema)
        return

    factory = _session_factory()
    with factory() as session:
        session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        _activate_sink_for_schema(session, schema)
        recipient = (
            session.execute(
                text(
                    """
                SELECT u.id AS user_id,
                       COALESCE(up.language, 'en') AS locale,
                       COALESCE(up.notification_channels, ARRAY['in_app','email']::text[])
                           AS notification_channels
                  FROM public.users u
                  LEFT JOIN public.user_preferences up ON up.user_id = u.id
                 WHERE u.id = :uid
                """
                ),
                {"uid": event.assignee_user_id},
            )
            .mappings()
            .first()
        )
        if recipient is None:
            _log.warning("visit_assigned_unknown_assignee", visit_id=str(event.visit_id))
            return
        if "push" not in list(recipient["notification_channels"]):
            # Opted out. Recorded rather than dropped, so "why didn't my phone
            # ring" has an answer that is not "we don't know".
            _insert_dispatch(
                session,
                alert_id=None,
                template_code="scouting_visit_assigned",
                locale=str(recipient["locale"]),
                channel="push",
                recipient_user_id=event.assignee_user_id,
                recipient_address=None,
                status="skipped",
                rendered_subject=None,
                rendered_body=None,
                error="user has not enabled push",
                visit_id=event.visit_id,
            )
            session.commit()
            return

        locale = str(recipient["locale"])
        template = _load_template(
            session, template_code="scouting_visit_assigned", locale=locale, channel="push"
        )
        if template is None:
            _log.warning("visit_assigned_template_missing", locale=locale)
            return

        # The instruction is the whole point of an ad-hoc visit, so it wins the
        # body over any generated summary.
        ctx = {
            "title": event.title,
            "block_code": "",
            "due_in": _humanise_due(event.due_by),
            "instruction": event.instruction or "",
        }
        subject = render(template["subject"], ctx)
        body = render(template["body"], ctx)

        tokens = _live_device_tokens(session, user_id=event.assignee_user_id)
        if not tokens:
            _insert_dispatch(
                session,
                alert_id=None,
                template_code="scouting_visit_assigned",
                locale=locale,
                channel="push",
                recipient_user_id=event.assignee_user_id,
                recipient_address=None,
                status="skipped",
                rendered_subject=subject,
                rendered_body=body,
                error="no registered devices",
                visit_id=event.visit_id,
            )
            session.commit()
            return

        data = {
            "type": "scouting_visit",
            "visit_id": str(event.visit_id),
            "farm_id": str(event.farm_id),
            "block_id": str(event.block_id),
            "severity": event.severity,
            "due_by": event.due_by.isoformat() if event.due_by else "",
            "deep_link": f"agripulse://scout/visits/{event.visit_id}",
        }
        for token in tokens:
            status_value, error = "sent", None
            try:
                if is_suppressed():
                    status_value, error = "skipped", SUPPRESSED_REASON
                else:
                    result = send_push(token=token, title=subject, body=body, data=data)
                    if result.skipped:
                        status_value, error = "skipped", "push channel disabled"
            except PushSendError as exc:
                status_value, error = "failed", str(exc)
                if exc.unregistered:
                    session.execute(
                        text(
                            "UPDATE device_tokens SET revoked_at = now() "
                            "WHERE token = :t AND revoked_at IS NULL"
                        ),
                        {"t": token},
                    )
            _insert_dispatch(
                session,
                alert_id=None,
                template_code="scouting_visit_assigned",
                locale=locale,
                channel="push",
                recipient_user_id=event.assignee_user_id,
                recipient_address=f"device:{token[-8:]}",
                status=status_value,
                rendered_subject=subject,
                rendered_body=body,
                error=error,
                visit_id=event.visit_id,
            )
        session.commit()


def _humanise_due(due_by: datetime | None) -> str:
    """ "18h" / "2d" — the countdown the ring shows, as words.

    Deliberately coarse: a scout glancing at a lock screen needs the order of
    magnitude, not a timestamp they have to subtract from.
    """
    if due_by is None:
        return ""
    delta = due_by - datetime.now(UTC)
    # Round rather than floor: a visit created with within_hours=24 is a
    # microsecond short of 24h by the time this renders, and announcing "23h"
    # reads as if the scout has already lost an hour they have not.
    hours = round(delta.total_seconds() / 3600)
    if delta.total_seconds() < 0:
        return "overdue"
    if hours < 48:
        return f"{max(hours, 1)}h"
    return f"{round(hours / 24)}d"
