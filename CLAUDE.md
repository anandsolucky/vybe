# VYBE — project instructions

VYBE is the personalized live-sports experience: fans choose the language,
voice, and energy of live commentary. Same game. Your vibe.

## Read first, every session

1. **`brand.md`** — the brand law (see rules below).
2. **`docs/DECISIONS.md`** — 16 ADRs. The source of truth for every
   architecture and product decision. New decisions go here, nowhere else.
3. **`docs/PLAN.md`** — build slices with checkboxes. Update as work lands.

## Brand rules (hard requirements)

- **`brand.md` governs ALL UI/UX, naming, and copy.** Any UI/UX design
  change must comply with it. Before adding a screen, flow, or line of
  copy, run the VYBE Test (brand.md §22).
- The brand is **VYBE** (uppercase). Tagline: **Same game. Your vibe.**
  Primary CTA: **Choose your VYBE.** Never append "AI" to the brand.
- User-facing copy uses brand vocabulary (§7, §9): personas are **VYBES**
  (The Pro, The Gen Z, The Hype, The Fan, The Chill, The Analyst).
  Never say "AI dubbing", "voice synthesis", "avatars", or "localization"
  in consumer surfaces (§12). Technical docs may use technical terms.
- Visuals (when UI work happens): colors and type per brand.md §14–16 —
  VYBE Black `#0A0A0F`, Violet `#7357FF`, Lime `#D8FF3E` (signal only,
  never background), White `#F7F7F2`; SF Pro + Inter. 60/25/10/5
  distribution. Logo and design-system assets land in `brand/assets/`.

## Current phase directive (2026-08-16)

**Backend first.** Build the pipeline (PLAN Slices 0–3) before UI polish.
Keep any interim UI minimal and functional; the full brand revamp is
Slice 5. Even interim UI copy must already use brand vocabulary.

## Engineering conventions

- Timing rules (ADR-012) are hard constraints: anchor to source reaction,
  never start early, causality cutoff at anchor time.
- TTS text is a performance script — rules in `docs/tts-writing-guide.md`.
- Personas live in `avatars/<lang>/<id>.yaml` ("avatars" is fine as an
  internal code name; user-facing name is VYBES). Each carries voice
  config and a calibrated `speaking_rate_wps`.
- Keys in `.env`: `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`,
  `SARVAM_API_KEY`, `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`.
  ElevenLabs: **Creator plan** (2026-08-16), 121K credits/month; library
  voices unlocked (Jatin + Naina run their real voices).
- **TTS testing budget policy (user rule, strict):** state the estimated
  credit cost BEFORE any test. Up to ~200 credits: proceed. Around 1,000
  credits or more: get the user's approval first. Prefer short tests.
  Never run long or repeated renders "just to see". The pipeline alerts
  when the trailing 30 minutes bill over 15K credits
  (`CREDIT_ALERT_30MIN` in `core/live_pipeline.py`).
- Python 3 + `.venv`, stdlib-first, minimal dependencies. FFmpeg for all
  media work.
- Write docs, commits, and comments in plain technical English (short
  sentences, active voice).
