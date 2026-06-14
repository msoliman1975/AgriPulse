"""Reports module — read-only farm reports composed from existing repos.

Five standard farm-management / vegetation reports (crop health, zone
anomaly, water balance, weather + GDD, operations log) surfaced as
per-farm GET endpoints under /api/v1/farms/{farm_id}/reports. Like the
insights module this owns no tables; it orchestrates the feature repos
(farms, indices, grid, weather, irrigation, plans, recommendations,
alerts) plus a few module-level SQL helpers for report-specific
rollups. Export (CSV / print-to-PDF) lives entirely on the frontend.
"""
