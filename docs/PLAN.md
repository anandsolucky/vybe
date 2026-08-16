# Build plan — VYBE

> **Branding:** the product is **VYBE** (ADR-016). `brand.md` at repo root
> is binding for all UI/UX, naming, and copy. `CLAUDE.md` enforces it.
> Current directive: **backend first** — UI stays minimal until Slice 5.

**How to resume in a fresh session:** read `docs/DECISIONS.md` (15 ADRs —
the source of truth), then this file. Checked boxes = done and verified.
Update checkboxes as work lands. New decisions go into DECISIONS.md, not
here.

## Status snapshot (2026-08-16)

- All architecture decided (ADR-001…015). POC approved: `poc/` renders the
  Kohli six with Kabir commentary, perfectly timed, center-cancelled crowd.
- Avatars: **Kabir finalized + active** (`avatars/hi/kabir.yaml`, premade
  voice Chris — works on Free plan). **Naina locked but dormant**
  (`avatars/hi/naina.yaml`, library voice needs plan upgrade).
- Keys in `.env`: Deepgram ✓, ElevenLabs (Free) ✓, Sarvam ✓.
  **Missing: `LLM_API_KEY` (OpenAI) — blocks Slice 2.**
- ElevenLabs stays on Free plan during the build (user decision).

## Slice 0 — scaffold  ✅ (2026-08-16)

- [x] `src/vybe/` layout: `providers/` (asr, llm, tts), `core/` (timeline,
      avatars, audio); `config.yaml` + `.env` loader; `.venv` + pyyaml
- [x] Provider interfaces per ADR-005 (`providers/base.py`)
- [x] POC code ported: `providers/tts_elevenlabs.py` (render_fit, speed
      ≤1.2), `core/timeline.py` (anchor placement, never-early),
      `core/audio.py` (center-cancel bed with mono fallback, mux)
- [x] Avatar loader with `speaking_rate_wps` (Kabir 3.2, Naina 2.6)

**Done:** `PYTHONPATH=src .venv/bin/python -m vybe.cli check` → all green;
`tests/test_timeline.py` → PASS (placement, never-early, overflow).

## Slice 1 — capture, delay, live transcript  ✅ core (2026-08-16)

- [x] Input abstraction (`core/capture.py`): file source paced at real
      time; AVFoundation source implemented (untested until an iPhone is
      connected); RTMP later — ADR-010
- [x] Deepgram streaming adapter (Nova-3 WS, word timestamps on the
      source clock)
- [x] Dev harness + live console: `vybe.cli live [input] [--video]` —
      delayed-viewer marker at exactly 15.00 s, per-word lead readout
- [ ] True A/V ring buffer (buffered delayed playback of the live feed) —
      lands with the mix bus in Slice 3/4; harness simulates it for now

**Measured on poc/source.mov:** 73 words · avg transcription lag 4.8 s ·
min headroom before viewer 5.5 s. Two findings for Slice 2:
1. Lag is bursty because `interim_results=false` waits for utterance
   ends. Turn interim results on for the director path to win back ~3 s.
2. ASR mishears names ("Kohli" → "Golly"/"goalie"). The commentary LLM
   must treat proper nouns as noisy and lean on match context.

## Slice 2 — commentary engine (the director)  ✅ core (2026-08-16)

- [x] OpenAI-compatible LLM adapter, verified (`gpt-5.4-mini` auto-picked
      from the key's model list) — ADR-008
- [x] Event segmentation: silence-gap beats; anchor = beat start;
      slot = next beat's start (`core/director.py`)
- [x] Prompt assembly: cricket preset + avatar YAML style + approved
      sample + word budget from `speaking_rate_wps × slot × 0.85`
- [x] Causality: prompt for beat i contains beats ≤ i only — ADR-012.4
- [x] Hard budget enforcement: over-budget reply gets one rewrite pass
- [x] Golden test: `vybe.cli direct poc/source.mov kabir` → 4 segments,
      all inside their slots, names repaired (Golly→Kohli), facts correct;
      saved to `poc/segments.json`

**Hardening backlog (Slice 3, in order):**
1. Deterministic Devanagari post-pass — `gpt-5.4-mini` mixes scripts
   mid-line ("trap set है" vs "ready hai"); a ~50-word transliteration map
   for Hindi function words fixes it without prompt roulette. First: hear
   whether it matters on ElevenLabs at all.
2. Slang guard is soft (prompt-level); add post-filter if audible.
3. Live path: enable Deepgram interim results (~3 s headroom win).
4. skip-logic untested — the 30 s clip has no filler beats.

## Slice 3 — TTS + audio pipeline  ✅ offline path (2026-08-16)

- [x] TTS render with slot-fit in the pipeline (`core/pipeline.py`)
- [x] Crowd bed: center-cancellation with auto-fallback to ducking when
      side energy is low — ADR-009 (`core/audio.py`)
- [x] Mix bus: bed + anchored commentary track, muxed
- [x] End-to-end offline test: `vybe.cli render poc/source.mov kabir
      --segments poc/segments.json` → `poc/vybe_kabir_auto.mp4`; all 4
      segments fit at speed 1.10, zero manual steps
- [ ] Live-loop wiring: render ahead of the delayed clock + deadline
      guard (drop late segment, never delay video) — lands with Slice 4

**Done:** the POC is reproduced by the pipeline. Fresh-input path also
works: `render <file>` with no --segments runs transcript + director
first.

## Slice 4 — live player UI  ✅ core (2026-08-16)

- [x] Local web app (`src/vybe/ui/player.html`, served by `src/vybe/server.py`):
      delayed video + both audio experiences live at once — ADR-011.
      Center-cancel crowd bed runs client-side in Web Audio (same L−R math
      as the FFmpeg filter), commentary segments scheduled at anchors.
- [x] Instant switch: 150 ms crossfade between Original / VYBE buses;
      verified in-browser (segments schedule correctly, mid-join works)
- [x] Sport dropdown (Cricket; Football/Tennis visible, disabled)
- [x] VYBE picker (Original / Kabir — The Gen Z / Naina greyed "soon")
- [x] Live loop (`core/live_pipeline.py`): streaming ASR → incremental
      beats → director → TTS → published segments, with the deadline
      guard (late segment drops; video never waits). Replay mode
      (`--replay poc/segments.json`) tests the player at zero API cost.
- [x] **Tab mode (primary live ingest, user-chosen):** `play --tab` —
      the player captures a Chrome tab via getDisplayMedia (native picker,
      tab audio), records it locally and plays it back 15 s delayed
      (MediaRecorder → MediaSource), and streams 16 kHz PCM to the ingest
      WebSocket (`src/vybe/ingest.py`, port 8790) for ASR → director → TTS.
      Ingest path smoke-tested end to end. DRM caveat: Widevine content
      (Hotstar) may capture black video; YouTube/non-DRM captures fine.
- [~] Screen mode (`play --screen`): ffmpeg screen+BlackHole capture with
      HLS output — capture verified standalone; in-pipeline HLS run still
      flaky (device contention debugging parked; tab mode supersedes it).
- [ ] iPhone-specific ingest: superseded by tab mode for the demo; the
      phone path (mirror window + BlackHole) remains possible later.

**Run it:** `PYTHONPATH=src .venv/bin/python -m vybe.cli play poc/source.mov`
(add `--replay poc/segments.json` for free replays) → http://127.0.0.1:8791
→ press VYBE ON.

## Slice 5 — polish and release prep  ☐

- [ ] Apply branding brief (name, identity) across repo/UI/docs
- [ ] README: setup, keys, provider matrix, demo GIF
- [ ] Config hygiene for open source: keyless degradation, credit guards
- [ ] git init + first public-ready commit (after branding)

## Parked / later phases

- Naina activation + voice recalibration (on ElevenLabs upgrade — item 14/15)
- More sports presets (tennis, soccer) — ADR-003
- Phase 3: parallel language tracks, instant multi-language switch
- Demucs separation replacing center-cancel — ADR-009 v2
- Bulbul v4 re-test when it reaches the API (monthly check)
- LLM/ASR bake-offs; fine-tuning; rights/legal for public demos
