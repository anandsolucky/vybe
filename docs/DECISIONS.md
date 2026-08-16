# Decision Record — Live AI Commentary

**Date:** 2026-08-16
**Deciders:** Anand Solanki (product), Claude (engineering, where delegated)
**Project:** Live multilingual AI re-commentary for sports broadcasts.

This file is the single source of truth for project decisions. One entry per
decision. Update the status when a decision changes.

---

## ADR-001: Product scope

**Status:** Accepted

### Context
We want live AI commentary on sports video, in a language the viewer picks.
Broadcasters already run ~15 seconds behind live. We can use that gap.

### Decision
Build a pipeline that ingests a live audio/video feed, delays it 15 seconds,
and plays it back with AI commentary in the selected language. The viewer
sees no gap: audio and video stay in sync.

Demo setup: a phone plays the match. A data cable connects it to the Mac.
The Mac shows the delayed stream with the new commentary.

### Consequences
- The 15-second buffer turns a real-time problem into a fast-batch problem.
- Every pipeline stage gets a generous latency budget (total ~4–9 s used).

---

## ADR-002: Perception source — listen, don't watch

**Status:** Accepted

### Context
The AI must know what happens in the match before it can comment. Options:
computer vision on frames, OCR on the score graphic, a ball-by-ball data
feed, or the source commentary audio itself.

### Decision
Use the source commentary audio as the only sensor. Transcribe it with ASR,
then re-express it in the target language. This makes the product a live
re-commentary (dubbing-plus) system, not an original-commentary system.

Event timing comes free: the source commentator reacts at second N, so the
new line plays at second N on the delayed stream.

### Consequences
- No vision models, no OCR, no data-feed dependency, no per-broadcaster tuning.
- The pipeline is sport-agnostic by construction (see ADR-003).
- Requires source audio with commentary. Raw feeds without commentary need
  the deferred sensor stack (vision + score-bug OCR).
- Deferred: score-bug OCR as a fact-check layer for numbers and names.

---

## ADR-003: Sport-agnostic core with sport presets

**Status:** Accepted

### Context
The pipeline never watches the game, so ASR, LLM, and TTS stages do not
depend on the sport. Only commentary idiom and terminology do.

### Decision
Keep the core sport-agnostic. Add a sport selector in the UI. Each sport maps
to a prompt preset: terminology, register, and style for the LLM. Cricket is
the first preset; tennis and soccer follow.

### Consequences
- Adding a sport costs one prompt preset, not new pipeline code.
- Later option: auto-detect the sport from the transcript, keep the toggle
  as override.
- Fast sports (soccer) need a tuning pass for speech-length fitting.

---

## ADR-004: Phased delivery

**Status:** Accepted

### Decision
- **Phase 1:** Cricket, Hindi only, one language at a time. Full working demo.
- **Phase 2:** More sports via presets (tennis, soccer).
- **Phase 3:** Parallel language processing. All languages render at once, so
  a language switch (for example to Gujarati) is instant.

### Consequences
- Phase 1 runs the selected language only. A switch takes a few seconds.
- Phase 3 multiplies LLM + TTS cost by the language count. Design for it,
  build it last.

---

## ADR-005: Model-agnostic provider architecture

**Status:** Accepted

### Context
The project should be open-source ready. Users must be able to paste their
own API keys and pick their own models. We must not lock into one vendor.

### Decision
Three provider interfaces, each with swappable adapters:

| Slot | Interface contract |
|---|---|
| ASR | audio chunks in → timestamped text out |
| LLM | match context + transcript segment → commentary line |
| TTS | text + language + emotion → audio stream |

Configuration lives in `.env` / `config.yaml`: one provider name and one key
per slot. The LLM slot ships two adapters: native Anthropic, and
OpenAI-compatible. The OpenAI-compatible adapter covers OpenAI, Gemini, Groq,
Mistral, and local runtimes (Ollama, vLLM, LM Studio).

Each slot also gets one local, keyless adapter so the project runs with zero
API keys (at lower quality).

### Consequences
- Vendor choice becomes a config change, not a code change.
- A single-vendor "Sarvam-only mode" is possible: one key drives ASR + LLM
  + TTS (Saaras + Sarvam LLM + Bulbul).
- Prompts stay provider-neutral: plain text in and out, no provider-specific
  tool calling.

---

## ADR-006: TTS — Sarvam Bulbul v3

**Status:** Accepted (user decision)

### Context
TTS is the quality-critical slot and the main cost. The demo targets Hindi;
later phases target more Indian languages.

### Decision
Sarvam Bulbul v3 is the default TTS. Reasons: built for 22 Indian languages,
native Hinglish code-switching, sub-250 ms streaming latency, voice cloning
for the later fine-tuning phase, and ~₹30 per 10K characters (~$0.60 per
match hour).

Alternate adapters: ElevenLabs (strong English/Spanish), local Indic
Parler-TTS (free, keyless mode).

### Consequences
- Sarvam covers the demo languages well at low cost.
- No lock-in: TTS is one adapter behind the abstraction (ADR-005).

---

### Update 2026-08-16 — expressive engine decided by audition
User verdict after five Bulbul rounds and an ElevenLabs A/B: **night and
day — ElevenLabs v3 wins on emotion.** New TTS lineup:
- **ElevenLabs v3** is the expressive engine for Hindi commentary
  (inline audio tags, CAPS loudness, stability modes). Pricing ~5× Sarvam
  (~$3–4/match-hour vs ~$0.60); acceptable at demo scale.
- **Sarvam Bulbul v3** stays as the low-cost adapter: Phase 3 parallel
  languages, cost-sensitive modes, and the hybrid pattern (Bulbul for
  routine play, ElevenLabs for climax lines). Re-test when Bulbul v4
  ships (announced with richer emotion, not yet in API).
- Account note: ElevenLabs Free plan blocks community-library voices via
  API (402) — premade voices work. Commercial use needs Starter+.

## ADR-007: ASR — Deepgram Nova-3 default, Saaras adapter alongside

**Status:** Accepted (confirmed by user — Deepgram key in hand)

### Context
The demo source commentary is English (international cricket broadcasts).
The user delegated this choice: pick whichever transcribes better, and do
not lock into Sarvam for every slot.

### Options considered

#### Option A: Deepgram Nova-3 (streaming)
| Dimension | Assessment |
|---|---|
| English accuracy | Strong — English-optimized flagship model |
| Streaming latency | Low; word-level timestamps included |
| Cost | $0.0077/min streaming; $200 free credit (~430 h) |
| Indic-language sources | Weaker than Saaras |

#### Option B: Sarvam Saaras v3-realtime
| Dimension | Assessment |
|---|---|
| English accuracy | Good; optimized for Indic + code-mixed speech |
| Streaming latency | Low; true partial transcripts, VAD tuning |
| Cost | Low; shares the Sarvam key (one-vendor mode) |
| Extra ability | Live translate mode: Indic speech → English text |

### Decision
Ship both adapters from day one; they share the same WebSocket pattern.

- **Default for English source audio: Deepgram Nova-3.** English commentary
  is Nova-3's home ground, and the free credit makes the demo cost zero.
- **Default for Indian-language source audio: Saaras v3-realtime.** It is
  Indic-optimized and its translate mode gives Indic → English in one step.

A bake-off on real commentary recordings decides the long-term default
(see Pending).

### Consequences
- Best transcription quality per source language, no vendor lock.
- The one-key Sarvam mode still works: users can set Saaras for everything.

---

## ADR-008: LLM — provider-agnostic via one OpenAI-compatible adapter

**Status:** Accepted (user decision)

### Context
The LLM slot fires a short generation every 15–20 seconds. It rewrites a
transcript segment into exciting target-language commentary. This is a
simple task: it needs fast first-token latency, not deep reasoning. The
user has OpenAI API keys and wants full provider independence.

### Decision
The LLM slot uses one OpenAI-compatible chat-completions adapter. Three
values in `.env` select the provider and model — no code change:

```
LLM_BASE_URL=https://api.openai.com/v1   # or openrouter.ai/api/v1, localhost, ...
LLM_API_KEY=sk-...
LLM_MODEL=<any small model the endpoint serves>
```

This one adapter covers OpenAI, OpenRouter (which itself serves Claude,
Gemini, Llama, and more behind one key), Groq, Mistral, and local runtimes
(Ollama, vLLM, LM Studio). Demo runs on the user's OpenAI key with a small,
cheap model. Prefer the smallest model that produces good commentary.

### Consequences
- Switching model or provider = edit `.env`, restart. Nothing else changes.
- OpenRouter gives access to nearly every hosted model through the same
  adapter, so a native Anthropic adapter is optional, not required.
- Commentary lines generate in ~1–2 s, inside the latency budget.
- Demo cost stays near zero: a full match uses well under $1 on any small
  model.

---

## ADR-009: Audio handling v1 — duck, don't separate

**Status:** Accepted

### Context
The delayed track still carries the original commentators. We want crowd
atmosphere under the new commentary.

### Decision
v1: duck the original audio to low volume whenever generated speech plays.
v2 (later): source separation (Demucs-class) to remove the original voices
and keep pure stadium sound.

### Consequences
- v1 is simple and good enough to prove the concept.
- Faint original speech may bleed under the new track until v2.

### Update 2026-08-16 — center-cancellation replaces plain ducking (approved)
POC finding: the source clip has real stereo separation (side −26.7 dB vs
mid −20.5 dB). Cancelling the center channel (`pan: c0=c0-c1, c1=c1-c0`,
+6 dB makeup) removes most of the commentator while keeping the crowd —
zero ML, zero latency, one FFmpeg filter. **User approved for v1** with
known residue ("slight commentators' noise… we will keep this").
Demucs-class separation remains the v2 quality upgrade. Caveat: the trick
depends on the broadcast mixing commentary dead-center; keep plain ducking
as automatic fallback when a source has near-zero side energy.

---

## ADR-010: Capture — iPhone → Mac, with a generic input for portability

**Status:** Accepted

### Context
The demo runs on an iPhone (source) and a Mac (receiver). The open-source
release should also serve Android and Windows users, if that is cheap.

### Decision
v1 officially supports iPhone + Mac. The iPhone connects over USB and
appears to macOS as a capture device (AVFoundation).

Portability comes almost free: the pipeline reads any FFmpeg-readable
source — a device index, a file, or an RTMP/SRT URL. The capture source is
one config value.

### Consequences
- Android/Windows users can feed the pipeline today via scrcpy or
  OBS → RTMP, with zero code changes. Native capture helpers can come later.
- Testing gets easier: a recorded match file is a valid input source.

---

## ADR-011: UI — one player, two live audio tracks, instant switch

**Status:** Accepted

### Context
The viewer watches the stream 15 seconds behind the phone. They must switch
between Original and Hindi audio with zero latency and no A/V lag.

### Decision
A single-page local web app:

- Video plays 15 s behind the phone.
- Audio selector: **Original | Hindi** (more languages in Phase 3).
- Sport dropdown: **Cricket** enabled; other sports listed but disabled.

Mechanism for the instant switch: the pipeline always renders **both**
audio tracks — the original (delayed as-is) and the AI language
(generated continuously, even while the user listens to the original).
Both tracks align to the same timeline. The selector only changes which
track is audible, with a short crossfade. No re-mux, no reprocessing.

### Consequences
- Language switch is instant and gapless, because the other track already
  exists at that timestamp.
- Phase 1 spends LLM + TTS on one AI language continuously (~$1 per match).
  Phase 3 extends the same design to N parallel tracks.
- The sport dropdown selects the LLM prompt preset (ADR-003); switching
  sport re-configures the LLM slot only.

---

## ADR-012: Timing and causality rules

**Status:** Accepted

### Context
The pipeline sees the match 15 seconds before the viewer does. Two failure
modes can break the illusion:

1. **Early audio:** the Hindi line starts before its event appears on
   screen — the commentary calls the six before the batsman hits it.
2. **Future leaks:** a filler line written for a quiet moment reveals an
   event the pipeline already knows about but the viewer has not seen.

### Decision
Four rules. They are hard constraints, not preferences.

1. **One clock.** Every frame, transcript word, and generated line carries
   a source-stream timestamp (PTS). Playback schedules by these timestamps
   only — never by wall clock.
2. **Anchor rule.** A generated line anchors to the start time of the
   source commentator's own reaction. It plays at that same timestamp on
   the delayed stream. The source commentator's timing is ground truth.
3. **Never-early rule.** A line may start at or after its anchor, never
   before. If the rendered Hindi audio runs longer than its slot, compress:
   give the LLM the slot duration so it writes to fit, raise TTS pace
   slightly (≤ ~10%), or trim the tail. Never shift the start earlier.
4. **Causality rule.** When the LLM writes a line anchored at source time
   T, its context stops at T. It never sees transcript after T, even though
   the pipeline holds up to 15 s more. The viewer's knowledge and the
   commentary's knowledge stay identical.

### Consequences
- Sync errors become one-sided and safe: a line can be late-and-trimmed,
  never early. Excited calls land exactly on the moment.
- The generation queue is per-anchor, so a language switch lands on a
  coherent track (ADR-011).
- Automated check: assert `line.start >= line.anchor` for every scheduled
  line; log any trim or pace adjustment.

---

## ADR-013: Commentator avatars per language

**Status:** Accepted (names are proposals — easy to change)

### Context
Commentary should have personality, not just language. Each language gets a
set of avatars. Hindi launches with three, on a spectrum from quirky to
professional. Adding or tweaking an avatar must be trivial.

### Decision
An avatar is one small data file: `avatars/hi/<id>.yaml`. It holds a name,
a one-sentence description, a Bulbul voice id, TTS settings (pace, pitch,
emotion defaults), and a style prompt block. The final LLM prompt composes
three layers: **sport preset** (what the terms mean) + **avatar persona**
(how it sounds) + **match context** (what is happening).

The three Hindi avatars:

| Avatar | Personality | One-line description |
|---|---|---|
| **Kabir** | Delhi Gen Z boy — quirkiest | Delhi ka Gen Z launda: calls a six "brutal" and a collapse "cooked", but knows his cricket cold. |
| **Naina** | Bombay girl — the middle | Warm, sharp Bombay girl next door — proper commentary with a grin and the occasional one-liner between overs. |
| **Tripathi ji** | Traditional professional | Old-school Hindi commentary at its finest — measured, poetic, every word weighed like a Test innings. |

Guardrails:
- Persona flavors the **delivery only**, never the facts. All avatars report
  the same events with the same accuracy.
- All ADR-012 timing and causality rules apply unchanged to every avatar.
- "Don't overdo it" is encoded in Kabir's style prompt: Gen Z terms land as
  seasoning (a few per over), not every sentence. Natural first, quirky second.

UI: an avatar picker appears when a non-original language is selected. It
shows the name and the one-line description. Each language sets a default
avatar (Hindi default: Naina — the middle of the spectrum).

Switching avatars takes effect from the next commentary line (a few
seconds), not instantly — rendering all avatars in parallel would multiply
TTS cost for little gain. Instant avatar switching can ride on the Phase 3
parallel-track design if wanted.

### Consequences
- A new avatar = one new YAML file. A tweak = editing prose in that file.
- Future avatars per language are unlimited; the picker reads the directory.
- Voice casting (mapping each avatar to a specific Bulbul speaker) is a
  pending task — it needs listening, not code.

---

## ADR-014: Expressive TTS text contract (no SSML)

**Status:** Accepted

### Context
Bulbul v3 does not support SSML or inline audio tags. Plain prose sounds
flat. Expressiveness comes from the text itself plus two API parameters:
`pace` (0.5–2.0) and `temperature` (0.01–2.0, default 0.6). Sarvam's own
best-practices doc defines the levers.

### Decision
The LLM slot does not emit plain prose. It emits **delivery segments**:
`{text, pace}` per segment, with punctuation written as performance. The
rules, from Sarvam's docs:

1. **Punctuation is the prosody control.** `,` short pause · `।` / `.`
   medium pause · `!` emphasis + pause · `…` trailing off / held breath ·
   line break = breathing pause. Write the excitement into the punctuation:
   short staccato sentences and stacked exclamations at a climax.
2. **Segment the moment.** One event = 3–4 short TTS calls, each with its
   own `pace`: build-up (~1.0) → strike (~1.2) → climax (~1.3–1.4) →
   reaction (back to base). Segments map 1:1 to our anchored lines
   (ADR-012), so this costs nothing extra.
3. **Per-avatar voice settings** live in the avatar YAML:
   temperature ~0.85 for Kabir (expressive), ~0.75 for Naina (warm),
   ~0.5 for Tripathi ji (controlled); base pace 1.2 / 1.05 / 0.95.
4. **Native script is mandatory.** Hindi words in Devanagari, English words
   in Latin script (Bulbul handles Hinglish natively). Romanized Hindi is
   the #1 quality killer. Hindi sentences end with `।`, English with `.`.
5. **Fillers are legal and useful.** `arre`, `um`, natural interjections
   add texture. Numbers over 4 digits take commas (`10,000`).
6. **Never emit SSML or bracket tags.** They are not supported and will
   degrade or be read aloud.

### Consequences
- The LLMProvider contract returns `[{text, pace}]`, not a string.
- Avatar YAML gains `temperature` and `base_pace` fields.
- The system prompt for the LLM teaches punctuation-as-performance once;
  every avatar inherits it.

### Update 2026-08-16 — post-processing levers (audition round 2)
Bulbul v3 has no loudness or pitch parameter. Round 2 tried local gain
contrast and a 3–4.5% pitch-lift resample. **User rejected the pitch/speed
manipulation — it sounds artificial. Do not use resampling tricks.**
Gain contrast (quiet build-ups attenuated) remains acceptable.
Audition feedback: Kabir's persona is parked pending a rewrite; Naina
(voice: priya) is the focus avatar until delivery is convincing.

### Update 2026-08-16 — round 3: how Bulbul emotion actually works
Research findings, now confirmed against the live API:
- **Bulbul v3 is LLM-prosody TTS: emotion comes from the meaning of the
  text.** There is no emotion parameter, tag, or style. The model acts what
  the words imply. Therefore: write the performance into the words, and
  send **one call per dramatic arc** — fragmenting a scene into short calls
  strips the context the prosody engine needs. Segmentation is now reserved
  for pace changes between separate moments, not within one moment.
- **`temperature` hard limit is 1.0** (docs claim 2.0; the API rejects
  anything above 1 — verified 2026-08-16). Use 0.9–1.0 for excited
  commentary.
- **Vocabulary rule (user decision): cricket terms stay English** — six,
  bat, ball, catch, over, runs, boundary. Never shuddh Hindi cricket words
  (छक्का/बल्ला). Hindi carries the sentences; English carries the cricket.
- **Bulbul v4 announced 2026-07-30** ("richer emotion, greater vocal
  range") but not yet in the API — no model ID or docs. Re-check monthly;
  upgrading is a one-line config change when it lands.
- **Fallback if v3's ceiling is too low:** ElevenLabs v3 supports Hindi
  with explicit inline audio tags ([excited], [shouting]) at higher cost.
  Run a bake-off only if the user rejects the round-3 output.

---

## ADR-015: POC complete — the risky piece is proven

**Status:** Accepted (user-approved output, 2026-08-16)

### What was proven
On a real 30 s clip (Kohli's MCG six, T20 WC 2022), the full offline
mirror of the pipeline ran end to end: Deepgram word-level transcript →
event anchors from source-reaction times → Kabir-style script written to
slot budgets → ElevenLabs v3 render → fit enforcement → center-cancelled
crowd bed → mux. The user approved the result. Artifacts in `poc/`.

### Findings that shape the build
1. **Timing rules work in practice.** Anchor + never-early + write-to-fit
   produced perfect sync; overflow is handled by trimming text, not
   sliding the clock.
2. **Words-per-second is a per-voice property.** Chris ≈ 3.2 w/s,
   Laura ≈ 2.6 w/s. Every avatar YAML gets a calibrated `speaking_rate`
   the LLM uses to size lines to slots.
3. **Speed ceiling:** ElevenLabs `voice_settings.speed` up to 1.2 is a
   usable fit lever; beyond that, rewrite shorter.
4. **Center-cancellation** (ADR-009 update) is the v1 crowd bed.
5. Free-plan limits: premade voices only via API (Kabir's Chris is
   premade, so the build is not blocked); library voices 402 until upgrade.

### Consequences
- Remaining work is deterministic engineering: capture, buffer, adapters,
  player. No open research questions.

---

## ADR-016: Branding — VYBE (brand.md is binding)

**Status:** Accepted (user-supplied brand foundation, 2026-08-16)

### Decision
The product is **VYBE** — "personalized live sports experience." The
user delivered a professional brand foundation (`brand.md` at repo root)
plus a logo and design system. **brand.md is binding for all UI/UX,
naming, and copy decisions.** Enforcement lives in `CLAUDE.md`.

Key bindings:
- Master tagline: **Same game. Your vibe.** · Primary CTA: **Choose your
  VYBE.** · Personas are **VYBES** in all user-facing surfaces.
- Consumer copy never leads with AI/dubbing/synthesis terminology.
- Colors: Black #0A0A0F · Violet #7357FF · Lime #D8FF3E (signal only) ·
  White #F7F7F2. Type: SF Pro + Inter.
- Experience model: Sport × Language × VYBE (matches ADR-003/004/013).

Project folder renamed `live-ai-commentary` → `vybe`.

### Build directive
Backend first (PLAN Slices 0–3). UI stays minimal until the brand revamp
pass (Slice 5). Logo/design assets go to `brand/assets/` when UI work
starts.

### Consequences
- Pending item #1 (project name) resolved.
- Kabir/Naina remain internal character names; user-facing persona
  labels follow brand.md §9 archetypes (mapping refined at UI time).

---

## Pending decisions and actions

| # | Item | Notes |
|---|---|---|
| 1 | ~~Project name~~ | Resolved → **VYBE** (ADR-016; brand.md is binding). |
| 2 | ~~Phone platform~~ | Resolved → ADR-010 (iPhone + Mac; generic FFmpeg input for others). |
| 3 | ~~UI shape~~ | Resolved → ADR-011 (dual-track player, sport dropdown). |
| 4 | ~~Sarvam Dub test~~ | Dropped — superseded by ADR-015 POC and the ElevenLabs decision. |
| 5 | ASR bake-off | Deepgram proven in POC. Saaras comparison deferred to Indic-source support. |
| 6 | API keys | In .env: Sarvam, Deepgram, ElevenLabs (Free). **Missing: LLM key (`LLM_API_KEY`) — needed before Slice 2.** |
| 7 | Delay-buffer design | FFmpeg ring buffer; validate A/V sync end to end. First build slice. |
| 8 | Speech-length fitting | Tune LLM slot-duration prompts + TTS speed for dense sports (soccer). Phase 2. |
| 9 | Fine-tuning plan | LLM style tune on commentary transcripts; Bulbul voice cloning. Later phase. |
| 10 | Parallel-language design | Phase 3 architecture: fan-out at LLM + TTS, shared ASR + timeline. |
| 11 | Rights / legal | Restreaming a broadcast with new audio needs rights. Decide demo source material before anything goes public. |
| 12 | v2 audio separation | Demucs-class separation to replace ducking (ADR-009). |
| 13 | ~~Voice casting (Kabir)~~ | Resolved 2026-08-16: **Kabir FINALIZED** — ElevenLabs v3, voice "Chris", bro-casual Hinglish style; spec + approved sample in `avatars/hi/kabir.yaml`. Kabir is the only active avatar for now; Naina and Tripathi ji deferred. |
| 14 | ElevenLabs plan upgrade | Free plan now: no commercial use, no library voices via API, 10K credits. Upgrade (Starter/Creator) before live demos or Indian library-voice casting. |
| 15 | Naina persona + voice | New direction from POC round: chatty Gen-Z vlogger register; user-picked library voice `3uuqz7fBxbNsCUVbBVKR` (402-blocked until upgrade; Laura was the stand-in). Not finalized. |
