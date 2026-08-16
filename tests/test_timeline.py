"""Timeline unit test: placement, never-early, overflow detection."""

import array
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vybe.core.timeline import place
from vybe.providers.base import DeliverySegment

RATE = 1000  # small rate keeps the test fast and readable


def tone(seconds: float) -> array.array:
    return array.array("h", [1000] * int(seconds * RATE))


def main() -> None:
    seg_a = DeliverySegment("a", anchor=1.0, slot_end=3.0)
    seg_b = DeliverySegment("b", anchor=3.0, slot_end=5.0)
    seg_c = DeliverySegment("c", anchor=5.0, slot_end=6.0)  # will overflow

    track, report = place(
        [(seg_b, tone(1.5), 1.1), (seg_a, tone(2.0), 1.1), (seg_c, tone(1.4), 1.2)],
        total_seconds=8.0, rate=RATE,
    )

    assert len(track) == 8 * RATE
    assert track[int(0.5 * RATE)] == 0, "audio before first anchor must be silent"
    assert track[int(1.0 * RATE)] == 1000, "segment must start exactly at its anchor"
    assert track[int(0.99 * RATE)] == 0, "never-early: nothing before the anchor"

    fits = {p.segment.text: p.fits for p in report}
    assert fits == {"a": True, "b": True, "c": False}, fits

    try:
        place([(DeliverySegment("x", 9.0, 10.0), tone(0.5), 1.1)], 8.0, RATE)
        raise AssertionError("anchor outside track must raise")
    except ValueError:
        pass

    print("test_timeline: PASS")


if __name__ == "__main__":
    main()
