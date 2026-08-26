"""Farm Timeline — one day-bucketed read over everything that happened.

The screen replays a farm (or one block) day by day. The map layer comes
from the imagery routes that already exist; this module supplies the other
half: the datapoints that landed on each day, from seven tables, in one
request.

One request rather than seven is the whole point. The console's
``/farms/{id}/scenes`` and ``/farms/{id}/grid-cells`` exist because a
per-block fan-out exhausted the 15-slot connection pool (#311). A replay
screen that scrubs across 90 days must not reopen that.
"""
