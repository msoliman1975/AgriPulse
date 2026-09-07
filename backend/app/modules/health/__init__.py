"""Health module — what "healthy" means, per crop.

The rule itself is in `app.shared.health_definition`: a bounded set of
values and a resolver that turns evidence into a class. This module is
the knowledge base behind it — the per-crop values, authored as YAML in
``seeds/`` and synced into ``public.crop_health_definitions`` at app
startup by ``loader.sync_from_disk``, the same shape the decision-tree
catalog uses.

Public surface (importable by other modules):

  * ``service.load_health_definitions`` — read the crop catalog and the
    farm's override once.
  * ``service.CropHealthDefinitions`` — resolve one block's crop path to
    the definition that applies to it.

``loader`` and ``seeds`` are private; only ``app.core.app_factory`` calls
the loader, which is the wiring layer's one allowed direction.
"""
