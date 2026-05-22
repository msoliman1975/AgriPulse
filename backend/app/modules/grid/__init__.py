"""Sub-block grid zones module.

A fishnet of square cells inside each block, materialised once per
``(block, imagery_product)`` and stable across rezones via a
``retired_at`` soft-retirement column. Per-scene zonal aggregates land
in a TimescaleDB hypertable mirroring ``block_index_aggregates``.

PR-1 surface: schema + grid generation + REST config API. The ingest
hook that populates ``block_grid_aggregates`` and the frontend heatmap
land in PR-2 and PR-3 respectively.
"""
