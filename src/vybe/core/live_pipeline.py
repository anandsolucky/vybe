"""Slice 4 live loop: source -> beats -> director -> TTS -> published segments.

The session writes per-segment mp3 files plus a manifest the player polls.
Deadline guard (ADR-012 consequence): a segment that is not ready by
(anchor + delay - margin) is dropped and logged — video never waits.

Replay mode re-publishes saved segments (TTS cache makes it free) so the
player can be tested without spending LLM/TTS credits.
"""

import json
import queue
import threading
import time
from pathlib import Path

from ..providers.asr_deepgram import DeepgramStreamingASR
from ..providers.base import DeliverySegment
from ..providers.tts_elevenlabs import ElevenLabsTTS
from .avatars import Avatar
from .capture import AVFoundationSource, CaptureMux, FileSource
from .director import BEAT_GAP, Director, beats_from_words
from . import audio

ASR_RATE = 16000
DEADLINE_MARGIN = 0.5   # seconds of slack required at publish time
WATCHDOG_SILENCE = 2.5  # wall seconds without words before closing a beat

CREDIT_ALERT_30MIN = 15_000  # user threshold: highlight when the trailing
                             # 30 minutes bill more than this many credits

# Reference rates for the cost report (checked 2026-08-16; adjust in one place).
DEEPGRAM_USD_PER_MIN = 0.0077          # Nova-3 streaming
ELEVEN_USD_PER_1K_CHARS = 0.10         # measured from dashboard 2026-08-16 (1,540 chars = $0.154)
LLM_USD_PER_M_IN = 0.25                # mini-tier estimate; see provider pricing
LLM_USD_PER_M_OUT = 2.00


class LiveSession:
    def __init__(self, input_spec: str, avatar: Avatar, llm, cfg: dict,
                 session_dir: Path, replay: list[DeliverySegment] | None = None,
                 ingest=None):
        self.ingest = ingest
        self.input_spec = input_spec
        self.avatar = avatar
        self.cfg = cfg
        self.dir = session_dir
        self.replay = replay
        self.delay = cfg.get("delay_seconds", 15)
        self.rate = cfg.get("sample_rate", 44100)
        self.t0: float | None = None
        self.asr_seconds = 0.0
        self.fit_retries = 0        # double renders (billed twice)
        self.tts_wasted = 0         # chars rendered then deadline-dropped
        self._cps_samples: list[tuple[int, float]] = []
        self._prev_text = ""        # prosody context for the next render
        self.lock = threading.Lock()
        self.manifest = {
            "video": "/media/source", "video_type": "file",
            "delay": self.delay, "sport": "cricket",
            "avatar": avatar.name, "started": False, "segments": [], "drops": 0,
        }
        settings = avatar.voice_settings
        self.tts = ElevenLabsTTS(
            voice_id=avatar.engine_config.get("fallback_voice_id")
            if avatar.status == "locked-dormant" else avatar.voice_id,
            stability=settings.get("stability", 0.0),
            speed=settings.get("speed", 1.1),
            model_id=avatar.engine_config.get("model_id", "eleven_v3"),
        )

    # -- state the server reads ------------------------------------------
    def state(self) -> dict:
        with self.lock:
            snapshot = json.loads(json.dumps(self.manifest))
        snapshot["t0"] = self.t0
        snapshot["server_now"] = time.time()
        snapshot["usage"] = self.usage()
        return snapshot

    def usage(self) -> dict:
        llm = getattr(self, "llm", None)
        report = {
            "asr_minutes": round(self.asr_seconds / 60, 2),
            "asr_usd": round(self.asr_seconds / 60 * DEEPGRAM_USD_PER_MIN, 3),
            "tts_billed_chars": self.tts.billed_chars,
            "tts_cached_chars": self.tts.cached_chars,
            "tts_usd_est": round(self.tts.billed_chars / 1000 * ELEVEN_USD_PER_1K_CHARS, 3),
            "tts_chars_30min": self.tts.billed_last(1800),
            "credit_alert": self.tts.billed_last(1800) > CREDIT_ALERT_30MIN,
            "tts_fit_retries": self.fit_retries,
            "tts_wasted_chars": self.tts_wasted,
            # >1.5s means audio reaches ASR slower than real time: PCM
            # loss or backlog -> anchors drift vs the video. Diagnostic.
            "asr_ingest_lag": round(max(0.0, (time.time() - self.t0) - self.asr_seconds), 1)
            if (self.t0 and self.asr_seconds) else 0.0,
        }
        if llm:
            report.update({
                "llm_calls": llm.calls,
                "llm_tokens_in": llm.prompt_tokens,
                "llm_tokens_out": llm.completion_tokens,
                "llm_usd_est": round(llm.prompt_tokens / 1e6 * LLM_USD_PER_M_IN
                                     + llm.completion_tokens / 1e6 * LLM_USD_PER_M_OUT, 3),
            })
        return report

    def print_usage(self) -> None:
        u = self.usage()
        print(f"[cost] ASR {u['asr_minutes']} min ≈ ${u['asr_usd']}"
              f" · TTS {u['tts_billed_chars']:,} credits billed"
              f" ({u['tts_cached_chars']:,} cached free)"
              f" ≈ ${u['tts_usd_est']} at Creator rate"
              + (f" · LLM {u['llm_calls']} calls,"
                 f" {u['llm_tokens_in']:,}/{u['llm_tokens_out']:,} tokens"
                 f" ≈ ${u['llm_usd_est']}" if "llm_calls" in u else ""))

    # -- publishing -------------------------------------------------------
    def _publish(self, seg: DeliverySegment, mp3_bytes: bytes, duration: float) -> None:
        ready_at = time.time()
        deadline = self.t0 + seg.anchor + self.delay
        lead = deadline - ready_at
        if lead < DEADLINE_MARGIN:
            with self.lock:
                self.manifest["drops"] += 1
                self.tts_wasted += len(seg.text)
            print(f"[pipeline] DROP anchor={seg.anchor:.2f}s (late by {-lead:.2f}s)")
            return
        name = f"seg_{int(seg.anchor * 100):07d}.mp3"
        (self.dir / name).write_bytes(mp3_bytes)
        with self.lock:
            self.manifest["segments"].append({
                "anchor": seg.anchor, "slot_end": seg.slot_end,
                "duration": round(duration, 2), "url": f"/media/{name}",
                "text": seg.text, "english": seg.english, "lead": round(lead, 1),
            })
        with self.lock:
            self._prev_text = (self._prev_text + " " + seg.text)[-500:]
        print(f"[pipeline] published anchor={seg.anchor:6.2f}s lead={lead:4.1f}s  {seg.text[:60]}")
        burn = self.tts.billed_last(1800)
        if burn > CREDIT_ALERT_30MIN and not getattr(self, "_credit_alerted", False):
            self._credit_alerted = True
            print(f"[cost] ⚠⚠⚠ HIGH BURN: {burn:,} credits in the last 30 minutes "
                  f"(threshold {CREDIT_ALERT_30MIN:,}) ⚠⚠⚠")

    TTS_ESTIMATE = 3.5  # seconds a render usually takes (measured 3.3)

    def _render_and_publish(self, seg: DeliverySegment) -> None:
        # Runs in a worker thread; never let an error vanish silently.
        if getattr(self, "tts_exhausted", False):
            with self.lock:
                self.manifest["drops"] += 1
            return
        try:
            self._render_and_publish_inner(seg)
        except Exception as err:
            with self.lock:
                self.manifest["drops"] += 1
            if "quota_exceeded" in str(err):
                self.tts_exhausted = True
                with self.lock:
                    self.manifest["tts_exhausted"] = True
                print("[pipeline] TTS QUOTA EXHAUSTED — no further renders this "
                      "session. Upgrade the ElevenLabs plan or wait for the "
                      "monthly reset.")
            else:
                print(f"[pipeline] ERROR anchor={seg.anchor:.2f}s: {err}")

    def _render_and_publish_inner(self, seg: DeliverySegment) -> None:
        # Pre-drop: if the render cannot make the deadline, save the credits.
        deadline = self.t0 + seg.anchor + self.delay
        if time.time() + self.TTS_ESTIMATE > deadline - DEADLINE_MARGIN:
            with self.lock:
                self.manifest["drops"] += 1
            print(f"[pipeline] PRE-DROP anchor={seg.anchor:.2f}s (no time to render)")
            return
        # Tag guard: a line with no delivery tag renders flat. Baseline it.
        if "[" not in seg.text:
            seg.text = "[excited] " + seg.text

        # Calibrated speed pick: estimate duration from observed
        # chars-per-second and choose the speed UP FRONT — one render
        # instead of render-measure-rerender (double billing).
        base = self.tts.base_speed
        estimate = len(seg.text) / self._cps()
        speed = base
        if seg.slot > 0 and estimate > seg.slot:
            speed = min(1.2, round(base * estimate / seg.slot, 2))
        with self.lock:
            prev = self._prev_text

        mp3 = self.tts.render(seg.text, speed=speed, previous_text=prev)
        samples = audio.mp3_to_mono(mp3, self.rate)
        duration = len(samples) / self.rate
        self._cps_samples.append((len(seg.text), duration * speed / base))

        # Overlap fade in the player absorbs small overshoots; re-render
        # only when the line badly outruns its slot and speed has room.
        if duration > seg.slot * 1.15 and speed < 1.2:
            self.fit_retries += 1
            mp3 = self.tts.render(seg.text, speed=1.2, previous_text=prev)
            samples = audio.mp3_to_mono(mp3, self.rate)
            duration = len(samples) / self.rate
        self._publish(seg, mp3, duration)

    def _cps(self) -> float:
        """Observed characters per second at base speed (default 14)."""
        recent = self._cps_samples[-20:]
        if not recent:
            return 14.0
        chars = sum(c for c, _ in recent)
        seconds = sum(d for _, d in recent)
        return max(8.0, chars / max(seconds, 0.1))

    def _detect_title(self, words) -> None:
        try:
            transcript = " ".join(w.text for w in words[:250])
            reply = self.llm.complete(
                "You name cricket fixtures from commentary. Reply with ONLY a "
                "short title like 'AUS vs BAN — 1st Test' or 'IND vs PAK — T20 "
                "World Cup'. If the teams are unclear, reply exactly UNKNOWN.",
                transcript,
            ).strip()
            if reply and "UNKNOWN" not in reply.upper() and len(reply) <= 60:
                with self.lock:
                    self.manifest["title"] = reply
                print(f"[pipeline] match identified: {reply}")
        except Exception as err:
            print(f"[pipeline] title detection failed: {err}")

    # -- replay mode ------------------------------------------------------
    def _run_replay(self) -> None:
        print(f"[pipeline] replay: {len(self.replay)} segments")
        pending = sorted(self.replay, key=lambda s: s.anchor)
        for seg in pending:
            # Simulate the live pipeline finishing ~10s before the viewer
            # reaches the anchor.
            publish_at = self.t0 + seg.anchor + self.delay - 10
            wait = publish_at - time.time()
            if wait > 0:
                time.sleep(wait)
            self._render_and_publish(seg)

    # -- live mode --------------------------------------------------------
    def _run_live(self) -> None:
        # The director (LLM, ~1.2s) stays sequential so each line knows the
        # previous ones. TTS (~3.3s, the fat stage) renders in parallel
        # workers so a burst of beats does not serialize into drops.
        from concurrent.futures import ThreadPoolExecutor

        director = Director(self.llm, self.avatar)
        words_q: queue.Queue = queue.Queue()
        # Creator plan allows 5 concurrent ElevenLabs requests; 4 workers
        # leave headroom for a fit-retry. (Free plan was 2.)
        tts_pool = ThreadPoolExecutor(max_workers=4)

        if self.input_spec == "browser":
            # Tab mode: the player captures a Chrome tab and streams PCM to
            # the ingest WebSocket. The source clock starts at the first
            # chunk, so anchors line up with the browser's capture start.
            source = self.ingest
            with self.lock:
                self.manifest["video"] = ""
                self.manifest["video_type"] = "tab"
        elif self.input_spec.startswith("screen:"):
            _, video_idx, audio_idx = self.input_spec.split(":")
            source = CaptureMux(int(video_idx), int(audio_idx), self.dir, ASR_RATE)
            self._source = source
            import atexit
            atexit.register(source.stop)  # no orphaned captures holding devices
            source.start()
            self.t0 = time.time()  # clock starts when the encoder starts
            with self.lock:
                self.manifest["video"] = "/media/live.m3u8"
                self.manifest["video_type"] = "hls"
        elif self.input_spec.startswith("avf:"):
            source = AVFoundationSource(int(self.input_spec[4:]), ASR_RATE)
        else:
            source = FileSource(self.input_spec, ASR_RATE, realtime=True)

        # Browser mode: Deepgram drops idle sockets after ~10 s, so do not
        # connect until the tab capture actually sends audio.
        first_chunk = None
        if self.input_spec == "browser":
            print("[pipeline] waiting for tab capture to start …")
            while first_chunk is None:
                first_chunk = self.ingest.queue.get()
            print("[pipeline] tab audio flowing — starting ASR")

        def clocked_chunks():
            first = True
            if first_chunk is not None:
                self.t0 = time.time()
                first = False
                self.asr_seconds += len(first_chunk) / (ASR_RATE * 2)
                yield first_chunk
            for chunk in source.chunks():
                if first:
                    self.t0 = time.time()
                    first = False
                self.asr_seconds += len(chunk) / (ASR_RATE * 2)
                yield chunk

        asr = DeepgramStreamingASR(ASR_RATE)
        asr_thread = threading.Thread(
            target=lambda: asr.stream(clocked_chunks(), words_q.put), daemon=True,
        )
        asr_thread.start()

        all_words: list = []
        processed = 0
        last_word_wall = time.time()
        stream_done = False

        while not (stream_done and words_q.empty()):
            try:
                batch = words_q.get(timeout=0.25)
                all_words.extend(batch)
                last_word_wall = time.time()
            except queue.Empty:
                if not asr_thread.is_alive():
                    stream_done = True

            beats = beats_from_words(all_words)
            # A beat is safe to process when a later beat exists (its slot
            # is known) or the watchdog says the source has gone quiet.
            closable = len(beats) - 1
            if (beats and time.time() - last_word_wall > WATCHDOG_SILENCE):
                closable = len(beats)
            # Chrome hides the captured tab's title (privacy), so VYBE
            # names the match from the commentary itself — once, early.
            if ("title" not in self.manifest and all_words
                    and all_words[-1].end > 40):
                self.manifest["title"] = ""  # sentinel: one attempt only
                words_snapshot = list(all_words)
                threading.Thread(target=self._detect_title,
                                 args=(words_snapshot,), daemon=True).start()

            for i in range(processed, closable):
                seg = director.segment_for(beats[: i + 2] if i + 1 < len(beats) else beats, i)
                processed = i + 1
                if seg:
                    tts_pool.submit(self._render_and_publish, seg)
                else:
                    print(f"[director] skip beat at {beats[i].start:.2f}s "
                          f"({beats[i].text[:50]!r})")

        # Stream ended: close out any beats the watchdog never reached.
        beats = beats_from_words(all_words)
        for i in range(processed, len(beats)):
            seg = director.segment_for(beats, i)
            if seg:
                tts_pool.submit(self._render_and_publish, seg)
            else:
                print(f"[director] skip beat at {beats[i].start:.2f}s")
        tts_pool.shutdown(wait=True)

    def run(self, llm=None) -> None:
        self.llm = llm
        self.t0 = time.time()
        with self.lock:
            self.manifest["started"] = True
        try:
            if self.replay is not None:
                self._run_replay()
            else:
                self._run_live()
        finally:
            print(f"[pipeline] done — {len(self.manifest['segments'])} published, "
                  f"{self.manifest['drops']} dropped")
            self.print_usage()
