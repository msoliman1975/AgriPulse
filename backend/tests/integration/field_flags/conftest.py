"""Fixtures for the field-flag tests.

`scouting_env` builds exactly the cast these tests need — a tenant, a farm, a
block, a Scout with a farm scope and no tenant role, and an Agronomist — but it
lives in the scouting package's conftest, which is a sibling of this one rather
than an ancestor. pytest only collects fixtures from conftest files on a test's
own path, so importing the name here is what puts it in scope.

Re-exported rather than copied: two builders of the same cast would drift, and
the Scout-with-no-tenant-role shape is the part worth having identical.
"""

from tests.integration.scouting.conftest import scouting_env  # noqa: F401
