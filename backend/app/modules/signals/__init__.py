"""Custom signals — tenant-defined data streams with manual entry.

Per data_model § 9. Three tables in the per-tenant schema:
``signal_definitions``, ``signal_assignments``, ``signal_observations``
(hypertable). Signals enter the alerts/recommendations decision
pipeline via ``snapshot.load_snapshot`` which exposes the latest
observation per applicable signal_code.

Public surface:
  * ``service.SignalsService`` Protocol + ``get_signals_service``.
  * ``snapshot.load_snapshot`` (cross-module — alerts + recs use it).

Internals (``models``, ``repository``, ``router``, ``schemas``) are
private per the import-linter contract.
"""
