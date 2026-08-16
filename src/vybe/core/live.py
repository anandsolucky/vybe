"""Slice 1 live harness: source plays "live", transcript streams in,
the delayed viewer starts delay_seconds later (ADR-001).

The console shows each transcribed word with two clocks:
  src   — the word's time on the source clock
  lead  — seconds of processing headroom left before the viewer
          reaches that moment (delay - transcription lag)
"""

import subprocess
import threading
import time

from ..providers.asr_deepgram import DeepgramStreamingASR
from .capture import AVFoundationSource, FileSource

ASR_RATE = 16000


def run(input_spec: str, delay_seconds: float, video: bool = False) -> dict:
    if input_spec.startswith("avf:"):
        source = AVFoundationSource(int(input_spec[4:]), ASR_RATE)
    else:
        source = FileSource(input_spec, ASR_RATE, realtime=True)

    t0 = time.monotonic()
    stats = {"words": 0, "lag_sum": 0.0, "min_lead": float("inf")}

    def viewer() -> None:
        time.sleep(delay_seconds)
        print(f"[{time.monotonic() - t0:6.2f}s wall] ▶ delayed viewer starts now "
              f"(watching source t=0.00)")
        if video and not input_spec.startswith("avf:"):
            subprocess.Popen(
                ["ffplay", "-v", "error", "-autoexit", input_spec],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    threading.Thread(target=viewer, daemon=True).start()

    def on_words(words) -> None:
        wall = time.monotonic() - t0
        for w in words:
            lag = wall - w.end
            lead = delay_seconds - lag
            stats["words"] += 1
            stats["lag_sum"] += lag
            stats["min_lead"] = min(stats["min_lead"], lead)
            print(f"[{wall:6.2f}s wall] src {w.start:5.2f}-{w.end:5.2f}  "
                  f"lead {lead:4.1f}s  {w.text}")

    asr = DeepgramStreamingASR(ASR_RATE)
    asr.stream(source.chunks(), on_words)

    total = time.monotonic() - t0
    if stats["words"]:
        avg_lag = stats["lag_sum"] / stats["words"]
        print(f"\nsummary: {stats['words']} words in {total:.1f}s · "
              f"avg transcription lag {avg_lag:.2f}s · "
              f"min headroom before viewer {stats['min_lead']:.1f}s")
    return stats
