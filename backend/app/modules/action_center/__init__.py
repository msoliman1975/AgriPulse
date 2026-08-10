"""Action Center — one queue over recommendations and alerts, plus dispatch.

Both kinds come from the same decision-tree engine and land in different
tables for good reasons (an alert expresses certainty and has its own
ack/resolve lifecycle; a recommendation carries confidence and can be applied
or deferred). The person looking at them does not care about that split — they
are deciding what gets done today and by whom — so this module reads across
both and hands back one row shape.

It owns no tables. Reads union `recommendations` + `alerts`; dispatch writes
`plan_activities` through the plans service.
"""
