"""Slice 3: segments -> rendered commentary -> mixed output video.

Offline mode reproduces the POC with zero manual steps:
media file -> (transcript -> director) or saved segments -> TTS with
slot-fit -> anchored timeline -> crowd bed -> mux.
"""

import subprocess
import tempfile
from pathlib import Path

from ..providers.base import DeliverySegment
from ..providers.tts_elevenlabs import ElevenLabsTTS
from .avatars import Avatar
from . import audio
from .timeline import place


def media_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def render_file(input_path: str, avatar: Avatar, cfg: dict,
                segments: list[DeliverySegment], out_path: str) -> list[dict]:
    rate = cfg.get("sample_rate", 44100)
    settings = avatar.voice_settings
    tts = ElevenLabsTTS(
        voice_id=avatar.engine_config.get("fallback_voice_id")
        if avatar.status == "locked-dormant" else avatar.voice_id,
        stability=settings.get("stability", 0.0),
        speed=settings.get("speed", 1.1),
        model_id=avatar.engine_config.get("model_id", "eleven_v3"),
    )

    rendered = []
    report = []
    for seg in segments:
        samples, speed, duration, fits = tts.render_fit(
            seg.text, seg.slot, decode=lambda b: audio.mp3_to_mono(b, rate), rate=rate,
        )
        rendered.append((seg, samples, speed))
        report.append({
            "anchor": seg.anchor, "slot": round(seg.slot, 2),
            "audio": round(duration, 2), "speed": speed, "fits": fits,
        })

    total = media_duration(input_path)
    track, placements = place(rendered, total, rate)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio.write_wav(track, rate, tmp.name)
        bed = audio.bed_filter(input_path, cfg.get("audio", {}))
        audio.mux(input_path, tmp.name, out_path, bed)
        Path(tmp.name).unlink()
    return report
