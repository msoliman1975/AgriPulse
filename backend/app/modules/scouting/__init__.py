"""Scouting — dispatch and lifecycle for field visits.

Public surface (other modules may import these):

  * ``models.ScoutingVisit`` / ``models.ScoutingRoutingRule``
  * ``service.get_scouting_service``

Observations are **not** stored here. A visit points at the
``signal_observations`` group it produced, so the recommendations engine keeps
reading signals exactly as before.
"""
