"""Recommendations module — decision-tree-driven, per-block daily evaluation.

Trees are rows in ``public.decision_trees``, authored in the app: a platform
admin edits the platform catalogue, a tenant admin edits their own trees.
Public migration 0085 installed the 33 platform trees; ``loader.compile_tree``
turns an authored spec into the stored body. The Beat task
``recommendations.evaluate_sweep`` walks every tenant's active blocks daily
and writes open recommendations.

Public surface (importable by other modules):

  * ``events.RecommendationOpenedV1`` and friends — for notifications fan-out.
  * ``service.RecommendationsService`` Protocol + ``get_recommendations_service``.

Internals (``models``, ``repository``, ``router``, ``schemas``) are
private per the import-linter contract.
"""
