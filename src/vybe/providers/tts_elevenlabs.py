"""ElevenLabs v3 adapter — the expressive engine (ADR-006 update).

render() returns mp3 bytes. render_fit() enforces the slot budget
(ADR-012): render at base speed, retry once at max_speed, report the fit.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

MAX_SPEED = 1.2
CACHE_DIR = Path(__file__).resolve().parents[3] / ".cache" / "tts"


class ElevenLabsTTS:
    def __init__(self, voice_id: str, stability: float = 0.0, speed: float = 1.1,
                 model_id: str = "eleven_v3", api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        self.voice_id = voice_id
        self.stability = stability
        self.base_speed = speed
        self.model_id = model_id
        self.billed_chars = 0   # cache misses — these consume credits
        self.cached_chars = 0   # cache hits — free
        self.billed_events: list[tuple[float, int]] = []  # (timestamp, chars)

    def render(self, text: str, speed: float | None = None) -> bytes:
        # Cache on the full voice recipe: identical requests never bill twice.
        key = hashlib.sha256(
            f"{self.voice_id}|{self.model_id}|{self.stability}|"
            f"{speed or self.base_speed}|{text}".encode()
        ).hexdigest()
        cache_path = CACHE_DIR / f"{key}.mp3"
        if cache_path.exists():
            self.cached_chars += len(text)
            return cache_path.read_bytes()
        self.billed_chars += len(text)
        import time
        self.billed_events.append((time.time(), len(text)))

        url = (f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
               f"?output_format=mp3_44100_128")
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "speed": speed or self.base_speed,
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "xi-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                audio = resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"ElevenLabs HTTP {e.code}: {body}") from None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(audio)
        return audio

    def billed_last(self, window_seconds: float = 1800) -> int:
        """Credits billed inside the trailing window (default 30 min)."""
        import time
        cutoff = time.time() - window_seconds
        return sum(chars for ts, chars in self.billed_events if ts >= cutoff)

    def render_fit(self, text: str, slot: float, decode, rate: int):
        """Render text to fit a slot. decode(mp3_bytes) -> sample array.

        Returns (samples, speed, duration, fits).
        """
        speed = self.base_speed
        samples = decode(self.render(text, speed))
        duration = len(samples) / rate
        if duration > slot:
            speed = MAX_SPEED
            samples = decode(self.render(text, speed))
            duration = len(samples) / rate
        return samples, speed, duration, duration <= slot
