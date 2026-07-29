"""Platform-admin backfill console.

Owns ``public.backfill_runs`` — the operational log behind
``/api/v1/admin/backfill-runs`` — and dispatches the historical-load work
that already lives in the imagery and weather modules.

It dispatches by Celery task *name* (``send_task``) rather than importing
those modules, so this module stays fully decoupled from them: no import
edge in either direction, and the tasks report progress back through
``app.shared.backfill_progress``.
"""
