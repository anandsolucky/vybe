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
from .avatars import Avatar, list_avatars, load_avatar
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
            "avatar": avatar.name, "avatar_id": avatar.id,
            "active_vybes": [avatar.id], "language": "hi",
            "avatars": self._roster(cfg), "started": False,
            "segments": [], "drops": 0,
        }
        self.lanes = [self._make_lane(avatar)]
        self.active_idx = 0
        self._pending_id: str | None = None
        self.language = "hi"
        self._pending_lang: str | None = None
        self.tts = self.lanes[0]["tts"]  # primary lane alias (replay, usage)

    def _make_lane(self, avatar: Avatar) -> dict:
        return {"id": avatar.id, "avatar": avatar,
                "tts": self._build_tts(avatar),
                "prev_text": "", "cps_samples": [], "director": None}

    @staticmethod
    def _build_tts(avatar: Avatar) -> ElevenLabsTTS:
        settings = avatar.voice_settings
        return ElevenLabsTTS(
            voice_id=avatar.engine_config.get("fallback_voice_id")
            if avatar.status == "locked-dormant" else avatar.voice_id,
            stability=settings.get("stability", 0.0),
            speed=settings.get("speed", 1.1),
            model_id=avatar.engine_config.get("model_id", "eleven_v3"),
        )

    def _roster(self, cfg: dict) -> list[dict]:
        language = cfg.get("default_language", "hi")
        roster = []
        for avatar_id in list_avatars(language):
            a = load_avatar(language, avatar_id)
            roster.append({
                "id": a.id, "name": a.name, "description": a.description,
                "status": a.status,
                "label": a.raw.get("vybe_label", "VYBE"),
                "blurb": a.raw.get("card_blurb", a.description),
                "quote": a.raw.get("card_quote", ""),
                "image": a.raw.get("card_image"),
                "locked": bool(a.raw.get("coming_soon")),
            })
        return roster

    def set_avatars(self, avatar_ids: list[str]) -> bool:
        """Picker pre-selection of the STARTING lane. Pre-audio only."""
        if self.t0 is not None or not avatar_ids:
            return False
        try:
            avatar = load_avatar(self.cfg.get("default_language", "hi"), avatar_ids[0])
            if avatar.raw.get("coming_soon"):
                return False
        except Exception:
            return False
        with self.lock:
            self.lanes = [self._make_lane(avatar)]
            self.active_idx = 0
            self.avatar = avatar
            self.tts = self.lanes[0]["tts"]
            self.manifest["avatar"] = avatar.name
            self.manifest["avatar_id"] = avatar.id
            self.manifest["active_vybes"] = [avatar.id]
        print(f"[pipeline] starting VYBE: {avatar.name}")
        return True

    def switch_lane(self, avatar_id: str) -> bool:
        """On-demand mid-match switch. The new VYBE takes the mic from the
        next beat at the live edge; the viewer hears it one buffer-delay
        later (the 'warming up' clock in the player)."""
        try:
            avatar = load_avatar(self.cfg.get("default_language", "hi"), avatar_id)
            if avatar.raw.get("coming_soon"):
                return False
        except Exception:
            return False
        with self.lock:
            if self.lanes[self.active_idx]["id"] == avatar_id:
                self._pending_id = None
                self.manifest.pop("queued_vybe", None)
                return True
            self._pending_id = avatar_id
            self.manifest["queued_vybe"] = avatar_id
        print(f"[pipeline] VYBE queued: {avatar_id}")
        return True

    def switch_language(self, code: str) -> bool:
        """On-demand language switch — same warming-up mechanic as VYBEs.
        Voices are multilingual (v3); only the director's writing changes."""
        from .director import LANGUAGES
        if code not in LANGUAGES:
            return False
        with self.lock:
            if code == self.language:
                self._pending_lang = None
                self.manifest.pop("queued_language", None)
                return True
            self._pending_lang = code
            self.manifest["queued_language"] = code
        print(f"[pipeline] language queued: {code}")
        return True

    def _activate_pending(self) -> None:
        lang = self._pending_lang
        if lang:
            self.language = lang
            for lane in self.lanes:
                if lane["director"] is not None and getattr(self, "llm", None):
                    lane["director"] = Director(self.llm, lane["avatar"], self.language)
            with self.lock:
                self._pending_lang = None
                self.manifest["language"] = lang
                self.manifest.pop("queued_language", None)
            print(f"[pipeline] language on the mic: {lang}")
        pending = self._pending_id
        if not pending:
            return
        lane = next((l for l in self.lanes if l["id"] == pending), None)
        if lane is None:
            lane = self._make_lane(load_avatar(self.cfg.get("default_language", "hi"), pending))
            self.lanes.append(lane)
        if lane["director"] is None and getattr(self, "llm", None):
            lane["director"] = Director(self.llm, lane["avatar"], self.language)
        with self.lock:
            self.active_idx = self.lanes.index(lane)
            self._pending_id = None
            self.manifest.pop("queued_vybe", None)
            self.manifest["avatar"] = lane["avatar"].name
            self.manifest["avatar_id"] = lane["id"]
            self.manifest["active_vybes"] = [lane["id"]]
        print(f"[pipeline] VYBE on the mic: {lane['id']}")

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
            "tts_billed_chars": sum(l["tts"].billed_chars for l in self.lanes),
            "tts_cached_chars": sum(l["tts"].cached_chars for l in self.lanes),
            "tts_usd_est": round(sum(l["tts"].billed_chars for l in self.lanes) / 1000 * ELEVEN_USD_PER_1K_CHARS, 3),
            "tts_chars_30min": sum(l["tts"].billed_last(1800) for l in self.lanes),
            "credit_alert": sum(l["tts"].billed_last(1800) for l in self.lanes) > CREDIT_ALERT_30MIN,
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
    def _publish(self, seg: DeliverySegment, mp3_bytes: bytes, duration: float,
                 lane: dict | None = None) -> None:
        lane = lane or self.lanes[0]
        ready_at = time.time()
        deadline = self.t0 + seg.anchor + self.delay
        lead = deadline - ready_at
        if lead < DEADLINE_MARGIN:
            with self.lock:
                self.manifest["drops"] += 1
                self.tts_wasted += len(seg.text)
            print(f"[pipeline] DROP anchor={seg.anchor:.2f}s (late by {-lead:.2f}s)")
            return
        name = f"seg_{lane['id']}_{int(seg.anchor * 100):07d}.mp3"
        (self.dir / name).write_bytes(mp3_bytes)
        with self.lock:
            self.manifest["segments"].append({
                "anchor": seg.anchor, "slot_end": seg.slot_end,
                "duration": round(duration, 2), "url": f"/media/{name}",
                "text": seg.text, "english": seg.english, "lead": round(lead, 1),
                "vybe": lane["id"], "lang": getattr(seg, "lang", "hi"),
            })
        with self.lock:
            lane["prev_text"] = (lane["prev_text"] + " " + seg.text)[-500:]
        print(f"[pipeline] published [{lane['id']}] anchor={seg.anchor:6.2f}s lead={lead:4.1f}s  {seg.text[:50]}")
        burn = self.tts.billed_last(1800)
        if burn > CREDIT_ALERT_30MIN and not getattr(self, "_credit_alerted", False):
            self._credit_alerted = True
            print(f"[cost] ⚠⚠⚠ HIGH BURN: {burn:,} credits in the last 30 minutes "
                  f"(threshold {CREDIT_ALERT_30MIN:,}) ⚠⚠⚠")

    TTS_ESTIMATE = 3.5  # seconds a render usually takes (measured 3.3)

    def _render_and_publish(self, seg: DeliverySegment, lane: dict | None = None) -> None:
        # Runs in a worker thread; never let an error vanish silently.
        lane = lane or self.lanes[0]
        if getattr(self, "tts_exhausted", False):
            with self.lock:
                self.manifest["drops"] += 1
            return
        try:
            self._render_and_publish_inner(seg, lane)
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

    def _render_and_publish_inner(self, seg: DeliverySegment, lane: dict) -> None:
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
        tts = lane["tts"]
        base = tts.base_speed
        estimate = len(seg.text) / self._cps(lane)
        speed = base
        if seg.slot > 0 and estimate > seg.slot:
            speed = min(1.2, round(base * estimate / seg.slot, 2))
        with self.lock:
            prev = lane["prev_text"]

        mp3 = tts.render(seg.text, speed=speed, previous_text=prev)
        samples = audio.mp3_to_mono(mp3, self.rate)
        duration = len(samples) / self.rate
        lane["cps_samples"].append((len(seg.text), duration * speed / base))

        # Overlap fade in the player absorbs small overshoots; re-render
        # only when the line badly outruns its slot and speed has room.
        if duration > seg.slot * 1.15 and speed < 1.2:
            self.fit_retries += 1
            mp3 = tts.render(seg.text, speed=1.2, previous_text=prev)
            samples = audio.mp3_to_mono(mp3, self.rate)
            duration = len(samples) / self.rate
        self._publish(seg, mp3, duration, lane)

    @staticmethod
    def _cps(lane: dict) -> float:
        """Observed characters per second at base speed (default 14)."""
        recent = lane["cps_samples"][-20:]
        if not recent:
            return 14.0
        chars = sum(c for c, _ in recent)
        seconds = sum(d for _, d in recent)
        return max(8.0, chars / max(seconds, 0.1))

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

        # Built after the picker window closes, so a pre-capture VYBE
        # selection takes effect.
        self._activate_pending()   # pre-start language/VYBE choices apply
        self.lanes[self.active_idx]["director"] = Director(
            self.llm, self.lanes[self.active_idx]["avatar"], self.language)

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
            for i in range(processed, closable):
                self._activate_pending()   # switches land between beats
                lane = self.lanes[self.active_idx]
                view = beats[: i + 2] if i + 1 < len(beats) else beats
                processed = i + 1
                seg = lane["director"].segment_for(view, i)
                if seg:
                    seg.lang = lane["director"].language
                    tts_pool.submit(self._render_and_publish, seg, lane)
                else:
                    print(f"[director] [{lane['id']}] skip beat at {beats[i].start:.2f}s")

        # Stream ended: close out any beats the watchdog never reached.
        beats = beats_from_words(all_words)
        lane = self.lanes[self.active_idx]
        for i in range(processed, len(beats)):
            seg = lane["director"].segment_for(beats, i)
            if seg:
                tts_pool.submit(self._render_and_publish, seg, lane)
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
