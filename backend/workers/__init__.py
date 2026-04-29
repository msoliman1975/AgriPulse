"""Celery worker entrypoints.

Three processes share this codebase:

  - workers.light.main : short tasks (< 10s) — audit writes, notifications,
                         alert evaluation fan-out
  - workers.heavy.main : long tasks (> 10s) — index computation, imagery
                         refresh, recommendation evaluation
  - workers.beat.main  : scheduler (Celery Beat); no real schedules yet

Same code is loaded by all three; each main.py builds a `Celery(...)`
instance pinned to one queue. ARCHITECTURE.md § 3.1.
"""
