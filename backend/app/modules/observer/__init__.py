"""AgriPulse Observer — platform-admin transparency for the indices pipeline.

Answers a different question from Platform → Health. Health asks *"did the
fetch work?"* (attempts, queue depth, provider errors). Observer asks *"is the
number right, and where did it come from?"* — from the raw scene count in a
window, down through masking and per-pixel arithmetic, up to the block
aggregate and the trend, and onward into the alerts it produced.

Read-only. This module owns no tables of its own in OBS-1: every number it
serves is derived from what the imagery, indices and grid modules already
write. It reaches those tables through raw SQL on an admin session scoped to
one tenant schema at a time — the same shape as the backfill console — rather
than importing those modules, so there is no import edge in either direction.

Design: docs/proposals/agripulse-observer.md
"""
