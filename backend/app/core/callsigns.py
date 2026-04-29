"""Callsign generator.

A callsign is a Contact's anonymous in-channel handle. They are deliberately
short, evocative, and ambiguous so two of them sound like they could be
the same person, or three different people, or none at all. We never want
the callsign to leak the underlying Operator.

Three patterns are produced with roughly equal frequency:

    "The {Adjective} {Noun}"   -> "The Silent Carrier"
    "{Noun}-and-{Noun}"        -> "Echo-and-Drift"
    "{Number} {Noun}s"         -> "Seven Pulses"

Use ``generate_callsign()`` for a one-shot draw. The ``contact_service`` is
responsible for retrying on uniqueness collisions within a single Channel.
"""

from __future__ import annotations

import secrets

_ADJECTIVES: tuple[str, ...] = (
    "Silent", "Scrambled", "Encrypted", "Dead", "Blind", "Ghost",
    "Lost", "Dark", "Rogue", "Cold", "Faded", "Drifting", "Broken",
    "Phantom", "Fixed", "Scattered", "Jammed", "Distant", "Spent",
    "Hollow", "Midnight", "Garbled", "Dimmed", "Isolated", "Stranded",
    "Muted", "Unverified", "Sparse", "Clipped", "Severed",
)

_NOUNS: tuple[str, ...] = (
    "Frequency", "Band", "Carrier", "Beacon", "Station", "Signal",
    "Pulse", "Echo", "Noise", "Drift", "Sweep", "Burst", "Tone",
    "Header", "Sequence", "Pattern", "Marker", "Grid", "Node",
    "Uplink", "Monitor", "Loop", "Antenna", "Bearing", "Vector",
    "Shadow", "Interval", "Segment", "Null", "Offset", "Threshold",
    "Squelch",
)

_NUMBERS: tuple[str, ...] = (
    "Three", "Five", "Seven", "Nine", "Eleven", "Thirteen",
)


def _the_pattern() -> str:
    return f"The {secrets.choice(_ADJECTIVES)} {secrets.choice(_NOUNS)}"


def _and_pattern() -> str:
    a = secrets.choice(_NOUNS)
    b = secrets.choice(_NOUNS)
    if b == a:
        b = secrets.choice(_NOUNS)
    return f"{a}-and-{b}"


def _number_pattern() -> str:
    return f"{secrets.choice(_NUMBERS)} {secrets.choice(_NOUNS)}s"


_PATTERNS = (_the_pattern, _and_pattern, _number_pattern)


def generate_callsign() -> str:
    """Return one randomly-styled callsign."""
    return secrets.choice(_PATTERNS)()
