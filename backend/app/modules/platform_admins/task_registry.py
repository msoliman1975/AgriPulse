"""Allowlist of background tasks a platform admin may run on demand.

Every periodic task in this product is dispatched by name from Beat and there
is no way to say "run this now, for this tenant". That costs twice: an
operator whose sweep was missed can only wait for the next cycle, and the
simulation harness (``docs/testing/org-simulation-harness.md``) cannot make a
seeded tenant produce recommendations without one.

Why an allowlist rather than a name passthrough
-----------------------------------------------
A generic ``send_task`` bridge would be a remote code execution primitive
wearing an HTTP endpoint: Celery dispatches by string, so any task in any
worker — including ``purge.run_job`` — would be reachable with attacker-chosen
kwargs. The allowlist is the whole security model, so it is a literal here
rather than anything derived at runtime.

The tenant-scoping rule
-----------------------
Every entry takes ``tenant_schema``, which the endpoint fills in from the
resolved tenant and the caller can never supply. Sweep tasks
(``*_sweep``, ``discover_*``) are deliberately absent: they walk every active
tenant, so exposing one would let a test run against a throwaway tenant touch
production data on every other tenant in the platform. If you are tempted to
add a sweep here, add its per-tenant counterpart instead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerableTask:
    """One task an admin may run, and the parameters it will accept."""

    name: str
    queue: str
    summary: str
    # Extra kwargs beyond tenant_schema. Anything not listed is rejected —
    # the caller cannot invent kwargs for a task that does not take them.
    optional_params: tuple[str, ...] = ()
    required_params: tuple[str, ...] = ()

    @property
    def accepted_params(self) -> frozenset[str]:
        return frozenset(self.optional_params) | frozenset(self.required_params)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "queue": self.queue,
            "summary": self.summary,
            "required_params": list(self.required_params),
            "optional_params": list(self.optional_params),
        }


TRIGGERABLE: tuple[TriggerableTask, ...] = (
    TriggerableTask(
        name="recommendations.evaluate_for_tenant",
        queue="light",
        summary="Evaluate every published decision tree and open the resulting "
        "recommendations and alerts.",
    ),
    TriggerableTask(
        name="indices.refresh_index_caggs_for_tenant",
        queue="light",
        summary="Materialize the index continuous aggregates. Backfilled history "
        "is invisible to readers until this runs.",
    ),
    TriggerableTask(
        name="indices.recompute_baselines_for_tenant",
        queue="light",
        summary="Refresh block_index_baselines from the rolling history.",
    ),
    TriggerableTask(
        name="weather.recompute_baselines_for_tenant",
        queue="light",
        summary="Refresh the farm-scoped weather index climatology and re-derive "
        "z-scores on existing rows.",
    ),
    TriggerableTask(
        name="weather.compute_risk_for_tenant",
        queue="light",
        summary="Score each crop block against its trailing weather window into "
        "weather_risk_daily.",
    ),
    TriggerableTask(
        name="weather.compute_spi_for_tenant",
        queue="light",
        summary="Recompute the standardised precipitation index.",
        optional_params=("target_iso",),
    ),
    TriggerableTask(
        name="weather.derive_weather_daily",
        queue="light",
        summary="Recompute weather_derived_daily for one farm and reproject its "
        "forecast horizon into weather_index_daily.",
        required_params=("farm_id",),
    ),
    TriggerableTask(
        name="irrigation.generate_for_tenant",
        queue="light",
        summary="Generate irrigation recommendations.",
    ),
    TriggerableTask(
        name="irrigation.water_balance_for_tenant",
        queue="light",
        summary="Recompute the block water balance.",
        optional_params=("target_iso",),
    ),
    TriggerableTask(
        name="grid.detect_anomalies_for_tenant",
        queue="light",
        summary="Re-run grid cell anomaly detection.",
    ),
)

BY_NAME: dict[str, TriggerableTask] = {t.name: t for t in TRIGGERABLE}

# Guards the literal above against a copy-paste that would widen it silently.
_FORBIDDEN_SUFFIXES = ("_sweep",)
_FORBIDDEN_PREFIXES = ("purge.", "eventbus.")


def _validate() -> None:
    for task in TRIGGERABLE:
        if task.name.endswith(_FORBIDDEN_SUFFIXES) or task.name.startswith(_FORBIDDEN_PREFIXES):
            raise ValueError(
                f"{task.name}: cross-tenant or destructive tasks cannot be triggered "
                "through the admin endpoint"
            )
        if "tenant_schema" in task.accepted_params:
            raise ValueError(
                f"{task.name}: tenant_schema is supplied by the endpoint from the "
                "resolved tenant and must never be caller-controlled"
            )
    if len(BY_NAME) != len(TRIGGERABLE):
        raise ValueError("duplicate task name in TRIGGERABLE")


_validate()

__all__ = ["BY_NAME", "TRIGGERABLE", "TriggerableTask"]
