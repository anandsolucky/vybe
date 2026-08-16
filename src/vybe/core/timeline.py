"""Anchor-based timeline (ADR-012).

Rules enforced here:
- A segment starts at its anchor, never before (never-early).
- A segment that outlasts its slot is flagged OVERFLOW; the caller must
  shorten the text or raise speed. The clock never moves.
"""

import array
from dataclasses import dataclass

from ..providers.base import DeliverySegment


@dataclass
class Placement:
    segment: DeliverySegment
    duration: float
    speed: float
    fits: bool


def place(placements: list[tuple[DeliverySegment, "array.array", float]],
          total_seconds: float, rate: int) -> tuple[array.array, list[Placement]]:
    """Place rendered segments on a silent track at their anchors.

    placements: (segment, samples, speed) triples, any order.
    Returns the assembled mono track and a fit report.
    """
    track = array.array("h", bytes(2 * int(total_seconds * rate)))
    report = []
    ordered = sorted(placements, key=lambda p: p[0].anchor)
    for segment, samples, speed in ordered:
        if segment.anchor < 0 or segment.anchor >= total_seconds:
            raise ValueError(f"anchor {segment.anchor} outside track")
        duration = len(samples) / rate
        report.append(Placement(segment, duration, speed, duration <= segment.slot))
        start = int(segment.anchor * rate)
        end = min(start + len(samples), len(track))
        track[start:end] = samples[: end - start]
    return track, report
