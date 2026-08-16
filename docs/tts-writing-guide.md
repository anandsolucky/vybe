# TTS writing guide — text as performance script

> **2026-08-16 — ElevenLabs v3 is the production engine.** The universal
> performance grammar now lives as the DELIVERY LAYER in
> `src/vybe/core/director.py` and applies to every avatar: fast live
> baseline ([slow] is a rare, deliberate storytelling tool), intensity
> ladder [excited] → [shouts] with human release ([laughs] / [chuckles]
> / [sighs] / [gasps]), word stretches on suspense words ("गईईईई",
> "loooong", "SIIIIX!"), CAPS + exclamation on English peak words, and
> tags re-applied every few words since each carries only the next few.
> Avatars differ only via `delivery_mix` in their YAML — how often, how
> strongly, in what sequence. The Bulbul-era rules below remain for that
> adapter; their core lesson (ellipsis = hesitation → calm moments only)
> still applies everywhere.

Bulbul v3 infers emotion from the meaning of the text. The text is the
prompt. This guide defines how commentary text must be written. The LLM
system prompt encodes these rules; the avatar persona sits on top.

## Core principle

Do not transcribe commentary. Write a performance. Every line must carry
its emotion in the words themselves — a line that reads neutral will sound
neutral, no matter what parameters we set.

## Techniques (in rough order of power)

1. **Authentic register.** Write in the exact idiom of real Hindi TV
   cricket commentary ("उठा दिया हवा में!", "दिल थाम के बैठिए", "ये गया…
   बहुत दूर गया!"). The model has heard this register; matching it recalls
   the matching delivery.
2. **Interjections that cannot be said flatly:** अरे! · ओहो! · वाह! ·
   उफ़्फ़… · ग़ज़ब! · क्या बात है! Their only natural reading is emotional.
3. **Broken syntax at high excitement.** Real commentators lose grammar:
   restarts, self-interruption, dashes ("रुकिए—रुकिए—boundary पर—").
   Urgent syntax forces urgent delivery.
4. **Question → answer flip for suspense:** "Six? Six होगा?… नहीं!! पकड़
   लिया!!" Questions force rising intonation; the flip forces the drop.
5. **Escalating repetition:** "ये गई… ये गई… ये तो बहुत ऊपर!" — each
   repeat naturally rises.
6. **Whisper content for hush.** Quiet is written as intimacy or held
   breath: "धीरे से बताऊँ?… bowler की हथेली में पसीना है।" Conspiratorial
   words produce a hushed read.
7. **Contrast cut.** A very short quiet fragment immediately before the
   explosion: "आया bowler… आया… और—" → "मारा!!"
8. **Emotion named in the meaning, never as a stage direction.** "यक़ीन
   नहीं हो रहा!" works (a commentator says it). "[excitedly]" does not
   (it will be read aloud).
9. **Punctuation as score:** … held breath · — cut/interruption · !!
   escalation · ?! suspense. Exclamation density maps to intensity.
   ⚠️ **Ellipsis means hesitation/trailing-off to Bulbul** (documented).
   Never use it in high-energy passages — it deflates them. Reserve `…`
   for the hush before and the exhale after. During the peak (ball in
   the air), use only short stacked exclamations and dashes.
10. **Paragraph = breath.** Line breaks between beats create natural gaps.

## Vocabulary rules (user decision, ADR-014)

- Cricket terms stay English: six, four, bat, ball, catch, over, runs,
  boundary, shot, fielder, wicket. Never छक्का/बल्ला/क्षेत्ररक्षण.
- Hindi in Devanagari, English words in Latin script. Never romanize Hindi.
- Fillers and vocatives allowed per persona (Naina: "अरे", "वाह";
  no "भाई/bro" — that is Kabir's register).

## Delivery constraints (verified against the API)

- One call per dramatic arc — never fragment a moment into context-less
  calls. Segment only between separate moments.
- temperature ≤ 1.0 (API-enforced). Excited commentary: 0.9–1.0.
- pace set per call; the model varies pace within the call on its own when
  the writing demands it.
- No SSML, no bracket tags, no resampling tricks (rejected).
