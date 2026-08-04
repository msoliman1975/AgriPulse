"""Product & engagement telemetry.

Deliberately NOT `app.modules.analytics`. `data_model.md § 14` reserves that
name for *agronomic* analytics — continuous aggregates and views over
`block_index_aggregates` / `weather_observations` / `alerts_history` — most of
which shipped inside the modules that own those source tables
(`block_index_daily`, `weather_hourly`, `v_active_alerts`,
`v_farm_integration_health`). Reusing the name for engagement telemetry would
collide with a different meaning.

This module is a **leaf**: nothing in the domain imports it. The frontend posts
to its router and the platform dashboard reads from its repository. The
`"telemetry internals are private"` import-linter contract enforces that.

See docs/proposals/product-telemetry-plan.md.
"""

from __future__ import annotations
