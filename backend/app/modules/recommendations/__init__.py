"""Recommendations module — decision-tree-driven, per-block daily evaluation.

Trees are authored as YAML in ``seeds/`` and synced into the
``public.decision_trees`` catalog at app startup via
``loader.sync_from_disk``. The Beat task ``recommendations.evaluate_sweep``
walks every tenant's active blocks daily and writes open recommendations.

Public surface (importable by other modules):

  * ``events.RecommendationOpenedV1`` and friends — for notifications fan-out.
  * ``service.RecommendationsService`` Protocol + ``get_recommendations_service``.

Internals (``models``, ``repository``, ``router``, ``schemas``) are
private per the import-linter contract.
"""
