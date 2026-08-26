"""Fixtures for the timeline tests.

`scouting_env` builds the cast these tests need — a tenant, a farm, a
block, a farm-scoped-only Scout and an Agronomist. It lives in the
scouting package's conftest, which is a sibling of this one rather than an
ancestor, so importing the name here is what puts it in scope. Same
arrangement the field_flags tests use, and for the same reason: two
builders of one cast would drift.
"""

from tests.integration.scouting.conftest import scouting_env  # noqa: F401
