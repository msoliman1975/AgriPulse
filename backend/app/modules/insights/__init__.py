"""Insights module — farm-level analytical rollups.

V1 (B.2 of [[project-insights-health-overview]]) ships two read
endpoints feeding the "Farm health overview" page:

  * `GET /api/v1/farms/{id}/index-timeseries` — per-block series of
    the selected index, across the whole farm in one round-trip.
  * `GET /api/v1/farms/{id}/health-summary` — one scorecard row per
    block (health badge + 30d trend + open alert count + last
    observation).

Composes existing repositories (farms, indices, alerts) rather than
owning data of its own.
"""
