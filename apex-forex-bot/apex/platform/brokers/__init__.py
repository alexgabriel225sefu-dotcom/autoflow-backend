"""Broker connectors, behind one platform-neutral contract.

Nothing here places an order. `base.py` defines what a provider must answer
about itself and what read-only data it can serve; a provider that wants to
execute is a separate, later decision with its own review gate.

See docs/MT5_CLOUD_CONNECTOR_SPIKE.md for why this package exists.
"""
