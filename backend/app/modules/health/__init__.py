"""Health module — what "healthy" means, per platform and per crop.

The rule itself is in `app.shared.health_definition`: a bounded set of
values and a resolver that turns evidence into a class. This module holds
the values behind it, which live in two public tables since migration 0095:

  * ``public.health_definition_platform`` — the platform default, one row.
  * ``public.crop_health_definitions`` — one partial body per crop path.

A platform admin edits both in the app (``admin_router``). Nothing is read
from disk.

Public surface (importable by other modules):

  * ``service.load_health_definitions`` — read every tier for one farm once.
  * ``service.CropHealthDefinitions`` — resolve one block's crop path to
    the definition that applies to it.
"""
