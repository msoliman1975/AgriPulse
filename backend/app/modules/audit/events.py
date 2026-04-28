"""Public event types for the audit module.

The audit module's *public* events are intentionally minimal — most
modules push records *into* audit, they don't react to audit events.
This file exists so import-linter contracts have a non-empty target.
"""

from __future__ import annotations

# Reserved for future use.
__all__: list[str] = []
