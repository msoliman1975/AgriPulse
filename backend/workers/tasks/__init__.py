"""Tasks shared across all worker entrypoints. Each task is auto-discovered
by `workers.celery_factory.build_celery` via the `include=` list.

Module-level imports of submodules are required so Celery sees their
`@task` decorators on app startup.
"""

from workers.tasks import eventbus_dispatch  # noqa: F401
