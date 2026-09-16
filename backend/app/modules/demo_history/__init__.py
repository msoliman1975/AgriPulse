"""Build a farm's past by replaying the real engine under a moved clock.

The runner in `runner.py` walks one simulated day at a time and calls the
same per-tenant task functions the scheduler calls in production. Nothing
here is a second implementation of the engine, because a second
implementation would drift and the demo would stop matching the product.

This only ever runs on an internal build tenant. `runner.replay` refuses to
start anywhere else.
"""
