"""The director (Slice 2): source transcript -> anchored delivery segments.

Flow (ADR-012):
- Group transcript words into beats (silence gap > BEAT_GAP splits).
- A segment anchors at its beat's start — the source reaction time.
- Slot ends where the next beat starts. The LLM gets a hard word budget
  from the avatar's speaking rate; the clock never moves for text.
- Causality: the prompt for beat i contains beats 0..i and nothing later,
  even when later beats are already known.
"""

import json
import re
from dataclasses import dataclass

from ..providers.base import DeliverySegment, Word
from .avatars import Avatar

BEAT_GAP = 0.8       # silence that separates two beats (seconds)
MAX_BEAT_LEN = 7.0   # force-close a beat after this much continuous speech
MAX_SLOT = 12.0      # cap a slot even when the source goes quiet
TAIL_SLOT = 3.0      # slot for the final beat of a stream
BUDGET_SAFETY = 0.85 # spend at most this share of the slot


@dataclass
class Beat:
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def beats_from_words(words: list[Word], gap: float = BEAT_GAP,
                     max_len: float = MAX_BEAT_LEN) -> list[Beat]:
    """Split on silence gaps — and force-split continuous speech.

    TV commentators rarely pause 0.8 s. Without the max_len split, a long
    stretch becomes one giant beat: it closes late and yields a single
    capped line, so the avatar falls silent between rare anchors.
    """
    beats: list[Beat] = []
    current: list[Word] = []
    for word in words:
        if current and (word.start - current[-1].end > gap
                        or word.end - current[0].start > max_len):
            beats.append(Beat(current[0].start, current[-1].end, current))
            current = []
        current.append(word)
    if current:
        beats.append(Beat(current[0].start, current[-1].end, current))
    return beats


CRICKET_PRESET = """Sport: cricket. You know the game cold: field positions,
shot names, match situations, the weight of a wicket or a six. Read the
match state from the source words (score, overs, who is on strike) and use
it naturally. Never invent facts the transcript does not support."""

OUTPUT_RULES = """Reply with STRICT JSON only, no code fences:
{"skip": false, "text": "..."}  — one commentary line for the new beat
{"skip": true}                  — say nothing for this beat
Skip only when the beat truly has nothing (dead air, pure repetition of
what you just said). A live commentator keeps the mic warm — when in
doubt, speak."""


def system_prompt(avatar: Avatar) -> str:
    style = avatar.style
    rules = "\n".join(f"- {r}" for r in style.get("sentence_rules", []))
    return f"""You are {avatar.name} — {avatar.description}
You re-voice live cricket commentary in your own words and language. You are
the viewer's commentator: react to what just happened, never narrate the
transcript back.

{CRICKET_PRESET}

RULE #1 — SCRIPT (never break this): every Hindi word in Devanagari,
every English word in Latin. No romanized Hindi, ever.
  WRONG: "Yeh proper trap set hai, bro."
  RIGHT: "ये proper trap set है, bro."

RULE #2 — NAMES: the transcript comes from speech recognition and mangles
names ("Golly", "goalie" = Kohli). Always write the real name; never copy
a mangled token. Cricket scores read "68 off 49", not "68 of 49".

Register: {style.get('register', '').strip()}
Slang budget: {style.get('slang_budget', '')} Use "bhai"/"bro" in at most
one line out of three; vary how lines open and close.
Sentence rules:
{rules}
Audio tags: {style.get('audio_tags', '')}
Punctuation is prosody: ellipses ONLY in calm moments, never during action.
Dashes cut, exclamations lift. CAPS only on English peak words.

Hard constraints:
- WORD BUDGET: each request states a maximum word count. Never exceed it.
  Shorter is always fine. Audio tags do not count as words.
- Causality: react only to what the transcript shows has already happened.
  Never predict or reveal anything beyond it.
- ASR noise: names may be mangled (Kohli can appear as "Golly"/"goalie").
  Infer the real name from cricket context; if unsure, drop the name.
- Do not repeat your previous lines' phrasing.

Reference of your voice (do not copy verbatim):
{avatar.approved_sample}

{OUTPUT_RULES}"""


def beat_prompt(beats: list[Beat], index: int, budget_words: int,
                slot: float, previous_lines: list[tuple[float, str]]) -> str:
    history = "\n".join(
        f"[t={b.start:.1f}-{b.end:.1f}] {b.text}" for b in beats[: index]
    ) or "(match just started)"
    ours = "\n".join(f"[t={t:.1f}] {line}" for t, line in previous_lines) or "(none yet)"
    beat = beats[index]
    return f"""Source commentary so far (English, timestamped):
{history}

Your previous lines:
{ours}

NEW BEAT — react to this. Anchor t={beat.start:.2f}s, slot {slot:.1f}s,
word budget {budget_words} words MAX:
[t={beat.start:.1f}-{beat.end:.1f}] {beat.text}"""


def parse_reply(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"no JSON in LLM reply: {raw[:200]}")
    return json.loads(match.group(0))


class Director:
    def __init__(self, llm, avatar: Avatar):
        self.llm = llm
        self.avatar = avatar
        self.system = system_prompt(avatar)
        self.previous: list[tuple[float, str]] = []

    def slot_for(self, beats: list[Beat], index: int) -> float:
        anchor = beats[index].start
        if index + 1 < len(beats):
            return min(beats[index + 1].start - anchor, MAX_SLOT)
        return min(beats[index].end - anchor + TAIL_SLOT, MAX_SLOT)

    SLANG = ("bro", "bhai", "yaar")

    def segment_for(self, beats: list[Beat], index: int) -> DeliverySegment | None:
        slot = self.slot_for(beats, index)
        budget = max(4, int(slot * self.avatar.speaking_rate_wps * BUDGET_SAFETY))
        prompt = beat_prompt(beats, index, budget, slot, self.previous)

        recent = " ".join(line.lower() for _, line in self.previous[-2:])
        if any(s in recent for s in self.SLANG):
            prompt += ("\n\nYou used bro/bhai/yaar in your recent lines. "
                       "Do NOT use any of them in this line.")

        reply = parse_reply(self.llm.complete(self.system, prompt))
        if reply.get("skip"):
            return None
        text = reply["text"].strip()

        # Hard budget enforcement: one rewrite, then accept (TTS speed
        # absorbs small overshoots in Slice 3).
        if spoken_words(text) > budget:
            retry = (prompt + f"\n\nYour attempt was {spoken_words(text)} words — "
                     f"over the {budget}-word budget. Rewrite the same line in at "
                     f"most {budget} words:\n{text}")
            reply = parse_reply(self.llm.complete(self.system, retry))
            if reply.get("skip"):
                return None
            text = reply["text"].strip()

        anchor = beats[index].start
        self.previous.append((anchor, text))
        return DeliverySegment(text=text, anchor=anchor, slot_end=anchor + slot)

    def direct(self, words: list[Word]) -> list[DeliverySegment]:
        """Offline mode: full transcript in, all segments out."""
        beats = beats_from_words(words)
        segments = []
        for i in range(len(beats)):
            segment = self.segment_for(beats, i)
            if segment:
                segments.append(segment)
        return segments


def spoken_words(text: str) -> int:
    """Word count excluding audio tags."""
    return len(re.sub(r"\[[^\]]+\]", " ", text).split())
