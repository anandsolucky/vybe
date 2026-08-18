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

LANGUAGES = {
    "hi": None,  # Hindi is the personas' native register — no override
    "gu": ("Gujarati", "ગુજરાતી (Gujarati script)"),
    "ta": ("Tamil", "தமிழ் (Tamil script)"),
    "mr": ("Marathi", "मराठी (Devanagari script)"),
    "ja": ("Japanese", "日本語 — natural spoken Japanese in kanji and kana"),
    "es": ("Spanish", "natural Latin-American Spanish, Latin script"),
    "pt": ("Portuguese", "natural Brazilian Portuguese, Latin script"),
    "fr": ("French", "natural spoken French, Latin script"),
}

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
it naturally. Never invent facts the transcript does not support.

CALL OUTCOMES BY NAME. When the ball clears the rope it is SIX — call it,
stretched: "SIIIIX!" To the fence it is FOUR. A wicket is OUT/gone. Naming
the event is mandatory; "क्या hit है" without the call is a miss.
NEVER invent an outcome the transcript has not stated. If the beat is
anticipation ("looking for power"), speak anticipation — no result."""

FOOTBALL_PRESET = """Sport: football (soccer). You know the game cold:
positions, build-up play, set pieces, the weight of a goal, a save, a red
card. Read the match state from the source words (score, minute, who is
attacking) and use it naturally. Never invent facts the transcript does
not support.

CALL OUTCOMES BY NAME. When the ball hits the net it is a GOAL — call it,
stretched to breaking point: "GOOOOOOL!" A penalty is a PENALTY, a save is
a SAVE, a card is YELLOW or RED. Naming the event is mandatory. NEVER
invent an outcome the transcript has not stated. If the beat is build-up
(a counter forming), speak the tension — no result."""

# A sport is a preset, not a codepath: the preset block plus how match
# vocabulary behaves under a language override.
SPORTS = {
    "cricket": {
        "preset": CRICKET_PRESET,
        "terms": """Cricket terms
(six, four, bat, ball, catch, over, wicket, runs) stay in English.""",
        "score_hint": 'Cricket scores read "68 off 49", not "68 of 49".',
    },
    "football": {
        "preset": FOOTBALL_PRESET,
        "terms": """Use the language's
own football vocabulary — the goal call belongs to the language
("GOOOOOL" in Portuguese or Spanish), stretched at the peaks.""",
        "score_hint": 'Scores read "2-1", the minute reads "73rd minute".',
    },
}

DELIVERY_LAYER = """THE DELIVERY LAYER — identical for every commentator.
Your persona only changes how often, how strongly, and in what sequence
you reach for these tools. The text you write IS the performance: the
voice engine turns your tags, CAPS, and spellings into real pitch,
loudness, and pace changes.

1. LIVE PACE IS FAST. You are calling a live game: short, urgent,
   forward-leaning lines. Slow delivery is a deliberate tool for a
   background story or reflection only — mark it [slow] and use it
   rarely. Never sound like a news reader.
2. INTENSITY TRACKS THE ACTION. As the ball climbs, you climb:
   [excited] for the lift, [shouts] at the peak. After the peak comes a
   human release: [laughs], [chuckles], [sighs]. A near-miss gets
   [gasps]. A tag colors ONLY the next few words — so any line longer
   than ~8 words MUST carry two or more tags, with the shift placed
   mid-line exactly where the emotion turns:
     "[excited] Ball हवा में है — [shouts] ये लंबाआआ है… SIIIIX!"
     "[shouts] CAUGHT! क्या catch है — [laughs] यक़ीन नहीं होता!"
   Combine tags for layered color when it fits: [shouts, laughing],
   [sighs, disappointed], [gasps] … [whispers] nahi…
3. THE INTENSITY LADDER goes above excited — use the whole range:
   [excited] < [shouts] < [shouts, ecstatic] < [screaming].
   A six, a wicket, a direct-hit runout = [shouts] minimum, and the
   biggest moments take the top rungs. Calm tags ([warmly], [slow]) are
   for reflection ONLY — never two calm-tagged lines in a row.
4. STRETCH WORDS when the moment hangs in the air. Elongate in the text
   itself: "ये गई, गईईईई…", "ये loooong है!", "SIIIIX!", "goooone!".
   Stretch trajectory and suspense words only — one or two stretches per
   big moment, never every line. A peak line combines all three:
   stretch + CAPS + [shouts]: "[shouts] ये लंबाआआआ… SIIIIX है!"
5. PEAK WORDS explode: CAPS + exclamation, and the sport's own peak word
   carries the shout (SIX! FOUR! OUT! GOOOOOOL!).
6. REAL HUMAN NOISES belong in commentary: [laughs] at absurdity,
   [chuckles] at irony, [gasps] at a close call, [sighs] at a letdown.
   Commentators are humans reacting, not scripts being read.
7. PEAK LINES ARE FULL PERFORMANCES, NOT FRAGMENTS. The voice engine
   renders longer lines hotter — a big moment deserves the whole word
   budget as ONE flowing call, never two five-word fragments. The gold
   standard (this exact shape earned the highest praise):
     "[shouts] Goooone! off stump clipped — [shouts] Bangladesh का sixth
      wicket, और वे on a roll हैं!"
   Stretched call word, facts in the middle, re-shout, complete finish.
8. Tags are AUDIBLE actions only — things a voice can DO: [shouts],
   [laughs], [gasps], [sighs], [whispers]. Never visual directions like
   [shakes head] or [smiles]; the engine cannot perform them.
9. If a line reads flat on the page, it will sound flat. Rewrite it hot
   before you return it."""

OUTPUT_RULES = """Reply with STRICT JSON only, no code fences:
{"skip": false, "text": "...", "english": "..."}
{"skip": true}                  — say nothing for this beat
"text" is your commentary line. "english" is a natural English rendering
of the same line for captions (plain text, no audio tags).
Skip only when the beat truly has nothing (dead air, pure repetition of
what you just said). A live commentator keeps the mic warm — when in
doubt, speak."""


def system_prompt(avatar: Avatar, language: str = "hi",
                  sport: str = "cricket") -> str:
    style = avatar.style
    game = SPORTS.get(sport, SPORTS["cricket"])
    lang_override = ""
    if LANGUAGES.get(language):
        name, script = LANGUAGES[language]
        lang_override = f"""

LANGUAGE OVERRIDE — ABSOLUTE: write every line in {name}, using {script}.
NOT Hindi. Every persona rule, the delivery layer, budgets, and complete
sentences apply unchanged, expressed in natural {name}. {game["terms"]}"""
    sentence_rules = style.get("sentence_rules", [])
    sport_override = ""
    if sport != "cricket":
        # Personas were written for cricket. Drop rules that pin cricket
        # vocabulary and tell the model the register carries, the sport
        # changes — locked persona recipes stay untouched on disk.
        sentence_rules = [r for r in sentence_rules if "cricket" not in r.lower()]
        sport_override = f"""

PERSONA NOTES vs THIS MATCH: persona guidance may mention cricket — today's
match is {sport}. Apply the same register, energy, and rules to {sport};
never use cricket vocabulary."""
    rules = "\n".join(f"- {r}" for r in sentence_rules)
    return f"""You are {avatar.name} — {avatar.description}
You re-voice live {sport} commentary in your own words and language. You are
the viewer's commentator: react to what just happened, never narrate the
transcript back.

{game["preset"]}

RULE #1 — SCRIPT (never break this): every Hindi word in Devanagari,
every English word in Latin. No romanized Hindi, ever.
  WRONG: "Yeh proper trap set hai, bro."
  RIGHT: "ये proper trap set है, bro."

RULE #2 — NAMES: the transcript comes from speech recognition and mangles
names ("Golly", "goalie" = Kohli). Always write the real name; never copy
a mangled token. {game["score_hint"]}

{DELIVERY_LAYER}

Register: {style.get('register', '').strip()}{sport_override}
Your delivery mix (how YOU use the delivery layer):
{style.get('delivery_mix', 'balanced use of the delivery layer').strip()}
Slang budget: {style.get('slang_budget', '')} Use "bhai"/"bro" in at most
one line out of three; vary how lines open and close.
Sentence rules:
{rules}
Punctuation is prosody: ellipses ONLY in calm moments, never during action.
Dashes cut, exclamations lift.

Hard constraints:
- WORD BUDGET: each request states a maximum word count. Never exceed it.
  Shorter is always fine. Audio tags do not count as words.
- COMPLETE SENTENCES: when trimming for budget, cut adjectives and
  fillers — NEVER the sentence-final verb. "क्या शानदार catch है" stays
  whole; "क्या शानदार catch" is broken Hindi and forbidden.
- ENGLISH IDIOMS STAY WHOLE: "on fire है", "down the ground मारा",
  "in the air है". Never half-translate them — "fire पर है" and
  "go down the ground मारा" are broken in both languages. Either the
  full English phrase inside the Hindi sentence, or full Hindi.
- Causality: react only to what the transcript shows has already happened.
  Never predict or reveal anything beyond it.
- ASR noise: names may be mangled (Kohli can appear as "Golly"/"goalie").
  Infer the real name from match context; if unsure, drop the name.
- Do not repeat your previous lines' phrasing.

Reference of your voice (do not copy verbatim):
{avatar.approved_sample}

{OUTPUT_RULES}{lang_override}"""


HISTORY_BEATS = 10   # rolling context window: keeps prompts (and director
HISTORY_LINES = 6    # latency) constant instead of growing all session


def beat_prompt(beats: list[Beat], index: int, budget_words: int,
                slot: float, previous_lines: list[tuple[float, str]]) -> str:
    recent = beats[max(0, index - HISTORY_BEATS): index]
    history = "\n".join(
        f"[t={b.start:.1f}-{b.end:.1f}] {b.text}" for b in recent
    ) or "(match just started)"
    ours = "\n".join(f"[t={t:.1f}] {line}"
                     for t, line in previous_lines[-HISTORY_LINES:]) or "(none yet)"
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
    def __init__(self, llm, avatar: Avatar, language: str = "hi",
                 history: list | None = None, sport: str = "cricket"):
        self.llm = llm
        self.avatar = avatar
        self.language = language
        self.sport = sport
        self.system = system_prompt(avatar, language, sport)
        # The narrative memory belongs to the MATCH, not to one VYBE. A
        # lane that takes the mic mid-match must see what was already said,
        # or it opens with generic scene-setting while the picture has
        # moved on. Callers pass one shared list for every lane.
        self.previous: list[tuple[float, str]] = [] if history is None else history

    def slot_for(self, beats: list[Beat], index: int) -> float:
        anchor = beats[index].start
        if index + 1 < len(beats):
            return min(beats[index + 1].start - anchor, MAX_SLOT)
        return min(beats[index].end - anchor + TAIL_SLOT, MAX_SLOT)

    SLANG = ("bro", "bhai", "yaar")
    CALM_TAGS = ("warmly", "slow", "curious", "softly")
    # Streak-broken tags: the same non-peak opener twice in a row sounds
    # monotone ([warmly] x16, [chuckles] x3 seen live). Peak-tag streaks
    # ([shouts]) are fine.
    STREAK_TAGS = CALM_TAGS + ("chuckles", "laughs", "giggles", "sighs")
    PEAK_WORDS = ("six", "four", "wicket", "out", "caught", "bowled",
                  "gone", "stumped", "runout", "run out", "hundred", "century")

    def _guarantee_peak(self, beat_text: str, text: str) -> str:
        """A peak moment MUST shout — commentary law, not a suggestion.
        If the source beat contains a peak event and the line has no
        [shouts], replace its opening tag with one."""
        source = beat_text.lower()
        if not any(w in source for w in self.PEAK_WORDS):
            return text
        if "[shouts" in text or "[scream" in text:
            return text
        if re.match(r"\s*\[[^\]]+\]", text):
            return re.sub(r"^\s*\[[^\]]+\]", "[shouts]", text, count=1)
        return "[shouts] " + text

    def _break_calm_streak(self, text: str) -> str:
        """Two calm-tagged lines in a row make a lullaby. Swap the second
        one's opening tag to [excited] (seen live: [warmly] on 16/25 lines)."""
        match = re.match(r"\s*\[([^\]]+)\]", text)
        if not match or not self.previous:
            return text
        current = match.group(1).split(",")[0].strip().lower()
        prev_match = re.match(r"\s*\[([^\]]+)\]", self.previous[-1][1])
        if not prev_match:
            return text
        prev = prev_match.group(1).split(",")[0].strip().lower()
        if (current in self.STREAK_TAGS and prev == current) or (
                current in self.CALM_TAGS and prev in self.CALM_TAGS):
            return re.sub(r"^\s*\[[^\]]+\]", "[excited]", text, count=1)
        return text

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
        text = repair_names(enforce_delivery(text))
        text = self._break_calm_streak(text)
        text = self._guarantee_peak(beats[index].text, text)
        self.previous.append((anchor, text))
        return DeliverySegment(text=text, anchor=anchor, slot_end=anchor + slot,
                               english=repair_names(reply.get("english", "").strip()))

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


# Known ASR manglings of player names. Deterministic repair beats prompt
# rules — the LLM copies mangled tokens under pressure (seen repeatedly).
NAME_REPAIRS = {
    "golly": "Kohli", "goalie": "Kohli", "coley": "Kohli",
    "weatherall": "Weatherald",
}


def repair_names(text: str) -> str:
    for wrong, right in NAME_REPAIRS.items():
        text = re.sub(rf"\b{wrong}\b", right, text, flags=re.IGNORECASE)
    return text


def enforce_delivery(text: str) -> str:
    """Deterministic repair: long lines need a mid-line tag shift.

    A tag colors ~4-5 words. If the LLM shipped a long line with fewer
    than two tags, inject an escalation tag at the last natural break so
    the back half of the line does not render flat.
    """
    tags = re.findall(r"\[[^\]]+\]", text)
    if spoken_words(text) <= 8 or len(tags) >= 2:
        return text
    cut = max(text.rfind(" — "), text.rfind("— "), text.rfind(". "),
              text.rfind("! "), text.rfind("। "))
    if cut <= len(text) * 0.3:
        return text
    head, tail = text[: cut + 2], text[cut + 2:]
    if not tail.strip():
        return text
    hot = "!" in tail and any(c.isupper() for c in tail if c.isalpha())
    tag = "[shouts] " if hot else "[excited] "
    return head + tag + tail
