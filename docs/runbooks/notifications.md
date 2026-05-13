# Notifications runbook

The notifications module fans out alert events across three channels:
in-app inbox (with SSE push), email (SMTP), and webhook (HMAC-signed
HTTP POST). This runbook describes the wire formats, on-call symptoms,
and the dev-fallback paths.

## Architecture summary

When `alerts` publishes `AlertOpenedV1`, the synchronous notifications
subscriber (registered in `app.core.app_factory`) runs inline:

1. Loads tenant context, the affected farm's scoped users, and the
   tenant's `alert_notification_channels` preference.
2. For each user, dispatches the channels they've opted into:
   - **in_app** â€” inserts a row in `<tenant>.in_app_inbox` and
     publishes to Redis channel `inbox:<tenant_id>:<user_id>` for SSE
     listeners.
   - **email** â€” renders the `alert_opened` template and sends through
     the configured SMTP relay (MailHog in dev).
3. **webhook** â€” runs once per alert (tenant-scoped, not per-user).
   POSTs the structured event to
   `tenant_settings.webhook_endpoint_url`.

Every attempt records a row in `<tenant>.notification_dispatches`
(`status` âˆˆ `pending | sent | skipped | failed`) so the audit trail is
complete regardless of channel outcome.

## Webhook contract

### Request

`POST <tenant_settings.webhook_endpoint_url>`

Headers:

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `User-Agent` | `AgriPulse-Webhooks/1.0` |
| `X-AgriPulse-Event` | `alert.opened` |
| `X-AgriPulse-Delivery` | UUID â€” unique per attempt; receivers can use this for idempotency |
| `X-AgriPulse-Signature` | `sha256=<hex>` HMAC-SHA256 of the raw body bytes |

Body (sorted keys, UTF-8):

```json
{
  "alert_id": "<uuid>",
  "block_id": "<uuid>",
  "delivery_id": "<uuid>",
  "event": "alert.opened",
  "farm_id": "<uuid>",
  "fired_at": "<iso8601>",
  "rule_code": "<code>",
  "severity": "info | warning | critical",
  "signal_snapshot": {<rule-specific>},
  "tenant_id": "<uuid>"
}
```

### Receiver verification (Python)

```python
import hmac, hashlib

expected = "sha256=" + hmac.new(
    secret.encode("utf-8"),
    raw_body_bytes,
    hashlib.sha256,
).hexdigest()
if not hmac.compare_digest(expected, request.headers["X-AgriPulse-Signature"]):
    abort(401)
```

Always use `hmac.compare_digest` (or your stack's constant-time equivalent).

### Sender semantics

- Single attempt per dispatch (no retries in PR-E). A future Beat task
  may sweep `status='failed'` rows for delayed retry.
- 5-second timeout. Transport errors and non-2xx responses both record
  `status='failed'` with the error message.
- If the tenant has no `webhook_endpoint_url`, the dispatch is recorded
  as `status='skipped'`.

## Signing-secret resolution

Production:
- `tenant_settings.webhook_signing_secret_kms_key` names a KMS key.
- A future enhancement will derive the per-tenant secret from KMS at
  send time. Until then, the dev fallback applies (see below).

Development / test:
- `WEBHOOK_DEV_SECRET` env var (default `dev-only-not-for-prod`) is the
  base secret.
- If the tenant has a `kms_key` set, it is appended (`<secret>::<kms_key>`)
  so two tenants on the same dev secret still produce distinct
  signatures.
- Setting `WEBHOOK_DEV_SECRET=` (empty) disables dev signing â€” the
  webhook channel will record `status='skipped'` with reason
  `no signing secret configured`.

## SMTP

| Setting | Default (dev) | Notes |
|---|---|---|
| `SMTP_HOST` | `localhost` | MailHog from `infra/dev/compose.yaml` |
| `SMTP_PORT` | `1025` | MailHog SMTP port |
| `SMTP_USERNAME` | (empty) | MailHog has no auth |
| `SMTP_PASSWORD` | (empty) | |
| `SMTP_STARTTLS` | `false` | Production must set to `true` |
| `SMTP_FROM` | `AgriPulse <noreply@agripulse.local>` | |

MailHog web UI: http://localhost:8025/. The compose stack starts it
alongside Postgres / Redis / Keycloak / MinIO.

## Common symptoms

| Symptom | Likely cause | Where to look |
|---|---|---|
| Bell badge stuck at 0 | SSE stream not connected | Network tab for `/api/v1/inbox/stream`; falls back to 60s poll if the stream errors |
| Alert fired but no inbox row | Subscriber not registered, or alert had no recipients | Logs for `alert_opened_no_recipients` / `alert_opened_missing_*` |
| Email channel marked `failed` | SMTP unreachable / auth | `notification_dispatches.error` |
| Webhook channel marked `failed` | Receiver returned non-2xx, or transport error | `notification_dispatches.error` (truncated to 1KB) |
| Receiver rejects every webhook | Signature mismatch | Confirm `WEBHOOK_DEV_SECRET` matches the receiver's; check kms_key suffix |

## Replays / backfill

Manually replay an alert through the channels:

```bash
# As a tenant admin:
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://api.<env>.agripulse.cloud/api/v1/blocks/<block_id>/alerts:evaluate
```

Re-running is idempotent: the partial UNIQUE on
`(block_id, rule_code) WHERE status IN (open,acknowledged,snoozed)`
prevents duplicate alerts, so the subscriber only fires when a new
alert actually opens.
