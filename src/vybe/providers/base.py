"""Provider contracts (ADR-005) and shared data types."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Word:
    """One transcript word on the source clock."""
    text: str
    start: float
    end: float


@dataclass
class DeliverySegment:
    """One commentary line, ready for TTS (ADR-012 + ADR-014).

    text carries the performance: audio tags, punctuation, CAPS.
    anchor is the earliest allowed start on the source clock.
    slot_end is where the next anchor begins.
    """
    text: str
    anchor: float
    slot_end: float

    @property
    def slot(self) -> float:
        return self.slot_end - self.anchor


class ASRProvider(Protocol):
    def transcribe_file(self, path: str) -> list[Word]: ...


class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class TTSProvider(Protocol):
    def render(self, text: str, speed: float) -> bytes: ...
