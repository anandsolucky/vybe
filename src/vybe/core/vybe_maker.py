"""Create and remove custom VYBES.

A VYBE is a persona spec plus a voice. The viewer gives a name, a short
description of the vibe, and 3 to 10 voice clips. The clips become an
ElevenLabs voice; the description becomes the full persona spec the
director needs, expanded by the LLM into the same shape as the shipped
personas.

Custom VYBES live in avatars/custom/ and are gitignored. Cloned voices
belong to the person who made them and never reach the public repo.
"""

import json
import re
import time
from pathlib import Path

import yaml

from ..config import ROOT
from ..providers.voice_lab import VoiceLab, VoiceLabError

CUSTOM_DIR = ROOT / "avatars" / "custom"
RESERVED = {"original"}

SPEC_SYSTEM = """You design commentator personas for VYBE, a live sports
experience. You turn a one line vibe into a full persona spec that an LLM
director can perform with.

Write the spec in English. It is an instruction sheet for the director,
so it DESCRIBES how the persona speaks rather than speaking that way.
Only "card_quote" and "approved_sample" are written in the persona's own
voice and language.

Return ONE JSON object, no prose, with exactly these keys:

"description": one line, under 20 words, in the voice of a casting note.
"register": 2 to 3 sentences. How this persona talks: energy, vocabulary,
  who they sound like they are talking to. Hinglish by default, majority
  Hindi in Devanagari with English sport terms, unless the vibe clearly
  asks otherwise.
"delivery_mix": 2 to 3 sentences on HOW they use performance tools:
  which audio tags they reach for ([excited], [shouts], [laughs],
  [gasps], [slow]), how often, and which words they stretch. Every
  persona shares the same toolbox; only the frequency and sequence differ.
"signature_words": 4 to 6 words or fillers this persona actually says,
  with a frequency note.
"slang_budget": one line on how much slang, with a cap per big moment.
"sentence_rules": 4 to 6 short imperative rules. Always include:
  complete sentences with Hindi clauses ending in है where grammar wants
  it; hard full stops; CAPS only on English peak words.
"length": one line on how long a big moment runs for them.
"audio_tags": one line on their tag baseline and their peak tag.
"vybe_label": 1 to 2 words in caps, then the word VYBE. Example: "HYPE VYBE".
"card_blurb": under 8 words, three or four punchy fragments.
"card_quote": one line this persona would shout at a big moment, in their
  own register, with Devanagari where Hindi appears.
"speaking_rate_wps": a number between 2.2 and 3.2. Faster talkers higher.
"approved_sample": 4 to 5 lines of this persona calling a big moment,
  each line starting with an audio tag, showing their range from build up
  to peak. Use Devanagari for Hindi and Latin for English. Include one
  stretched peak word.

Write the persona the vibe asks for, not a copy of any existing one."""


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "vybe"


def list_custom() -> list[str]:
    if not CUSTOM_DIR.exists():
        return []
    return sorted(p.stem for p in CUSTOM_DIR.glob("*.yaml"))


def _unique_id(name: str, taken: set[str]) -> str:
    base = slugify(name)
    if base not in taken:
        return base
    for n in range(2, 100):
        if f"{base}-{n}" not in taken:
            return f"{base}-{n}"
    raise ValueError("could not find a free id for this name")


def _spec_from_prompt(llm, name: str, prompt: str) -> dict:
    reply = llm.complete(
        SPEC_SYSTEM,
        f'Persona name: {name}\nThe vibe: {prompt}\n\nReturn the JSON object.',
    )
    match = re.search(r"\{.*\}", reply, flags=re.DOTALL)
    if not match:
        raise ValueError("the persona writer did not return JSON")
    spec = json.loads(match.group(0))

    rate = spec.get("speaking_rate_wps", 2.7)
    try:
        rate = min(3.2, max(2.2, float(rate)))
    except (TypeError, ValueError):
        rate = 2.7
    spec["speaking_rate_wps"] = rate

    rules = spec.get("sentence_rules") or []
    if isinstance(rules, str):
        rules = [r.strip() for r in rules.splitlines() if r.strip()]
    spec["sentence_rules"] = [str(r) for r in rules][:8]

    # Models sometimes answer a text field with a list of lines. The
    # director interpolates these straight into its prompt, so flatten.
    for key in ("description", "register", "signature_words", "delivery_mix",
                "slang_budget", "length", "audio_tags", "vybe_label",
                "card_blurb", "card_quote", "approved_sample"):
        value = spec.get(key)
        if isinstance(value, list):
            spec[key] = "\n".join(str(v) for v in value)
        elif value is not None and not isinstance(value, str):
            spec[key] = str(value)
    return spec


def create_vybe(name: str, prompt: str, clips: list[tuple[str, bytes]],
                llm, lab: VoiceLab | None = None,
                language: str = "hi-IN") -> dict:
    """Clone the voice, write the persona, return a summary for the UI."""
    name = " ".join(name.split())[:40]
    if not name:
        raise ValueError("Give your VYBE a name.")
    prompt = prompt.strip()
    if len(prompt) < 12:
        raise ValueError("Describe the vibe in a sentence or two.")

    from .avatars import list_avatars
    taken = set(list_avatars("hi")) | set(list_custom()) | RESERVED
    vybe_id = _unique_id(name, taken)

    lab = lab or VoiceLab()
    spec = _spec_from_prompt(llm, name, prompt)          # LLM first: it is
    cloned = lab.clone(name, clips, description=prompt)  # cheap to retry
    voice_id = cloned.get("voice_id")
    if not voice_id:
        raise VoiceLabError("ElevenLabs did not return a voice id.")

    data = {
        "id": vybe_id,
        "name": name,
        "description": spec.get("description", prompt[:120]),
        "language": language,
        "status": "custom",
        "custom": True,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "source_prompt": prompt,
        "vybe_label": spec.get("vybe_label", "CUSTOM VYBE"),
        "card_blurb": spec.get("card_blurb", prompt[:60]),
        "card_image": "",
        "card_quote": spec.get("card_quote", ""),
        "engine": "elevenlabs",
        "engine_config": {
            "model_id": "eleven_v3",
            "voice_id": voice_id,
            "voice_settings": {"stability": 0.0, "speed": 1.1},
        },
        "speaking_rate_wps": spec["speaking_rate_wps"],
        "style": {
            "register": spec.get("register", prompt),
            "signature_words": spec.get("signature_words", ""),
            "delivery_mix": spec.get("delivery_mix", ""),
            "slang_budget": spec.get("slang_budget", ""),
            "sentence_rules": spec["sentence_rules"],
            "length": spec.get("length", ""),
            "audio_tags": spec.get("audio_tags", ""),
        },
        "approved_sample": spec.get("approved_sample", ""),
    }

    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    header = (f"# {name} — custom VYBE, created {data['created']}.\n"
              f"# Written from: {prompt}\n"
              f"# Voice cloned in ElevenLabs. Delete the VYBE to remove it there too.\n")
    path = CUSTOM_DIR / f"{vybe_id}.yaml"
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True,
                                            sort_keys=False))
    print(f"[vybe-maker] created {vybe_id} (voice {voice_id})")
    return {"id": vybe_id, "name": name, "voice_id": voice_id,
            "requires_verification": bool(cloned.get("requires_verification")),
            "label": data["vybe_label"]}


OVERRIDE_DIR = CUSTOM_DIR / "overrides"

# The persona keys an edit may rewrite. The voice, the id and the language
# are never touched: editing changes how a VYBE talks, not who it is.
EDITABLE = ("description", "vybe_label", "card_blurb", "card_quote",
            "speaking_rate_wps", "style", "approved_sample")


def describe_vybe(vybe_id: str) -> dict:
    """What the edit form needs: the current vibe and what can be done."""
    custom_path = CUSTOM_DIR / f"{vybe_id}.yaml"
    is_custom = custom_path.exists()
    override_path = OVERRIDE_DIR / f"{vybe_id}.yaml"

    data = {}
    if is_custom:
        data = yaml.safe_load(custom_path.read_text()) or {}
    else:
        for lang_dir in sorted((ROOT / "avatars").glob("*")):
            shipped = lang_dir / f"{vybe_id}.yaml"
            if lang_dir.name != "custom" and shipped.exists():
                data = yaml.safe_load(shipped.read_text()) or {}
                break
        if not data:
            raise ValueError("no VYBE with that name")
        if override_path.exists():
            data.update(yaml.safe_load(override_path.read_text()) or {})

    prompt = data.get("source_prompt") or data.get("description", "")
    return {"id": vybe_id, "name": data.get("name", vybe_id),
            "custom": is_custom, "prompt": prompt,
            "edited": override_path.exists(),
            "label": data.get("vybe_label", "")}


def edit_vybe(vybe_id: str, prompt: str, llm) -> dict:
    """Rewrite how a VYBE talks. The voice behind it stays exactly as is."""
    info = describe_vybe(vybe_id)
    prompt = prompt.strip()
    if len(prompt) < 12:
        raise ValueError("Describe the vibe in a sentence or two.")

    spec = _spec_from_prompt(llm, info["name"], prompt)
    patch = {
        "source_prompt": prompt,
        "description": spec.get("description", prompt[:120]),
        "vybe_label": spec.get("vybe_label", info["label"] or "CUSTOM VYBE"),
        "card_blurb": spec.get("card_blurb", prompt[:60]),
        "card_quote": spec.get("card_quote", ""),
        "speaking_rate_wps": spec["speaking_rate_wps"],
        "style": {
            "register": spec.get("register", prompt),
            "signature_words": spec.get("signature_words", ""),
            "delivery_mix": spec.get("delivery_mix", ""),
            "slang_budget": spec.get("slang_budget", ""),
            "sentence_rules": spec["sentence_rules"],
            "length": spec.get("length", ""),
            "audio_tags": spec.get("audio_tags", ""),
        },
        "approved_sample": spec.get("approved_sample", ""),
    }

    if info["custom"]:
        path = CUSTOM_DIR / f"{vybe_id}.yaml"
        data = yaml.safe_load(path.read_text()) or {}
        data.update(patch)
        header = (f"# {info['name']} — custom VYBE, edited "
                  f"{time.strftime('%Y-%m-%d %H:%M')}.\n"
                  f"# Written from: {prompt}\n")
        path.write_text(header + yaml.safe_dump(data, allow_unicode=True,
                                                sort_keys=False))
    else:
        OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
        header = (f"# Local edit of the shipped {info['name']} persona, "
                  f"{time.strftime('%Y-%m-%d %H:%M')}.\n"
                  f"# The shipped file is untouched. Reset removes this file.\n")
        (OVERRIDE_DIR / f"{vybe_id}.yaml").write_text(
            header + yaml.safe_dump(patch, allow_unicode=True, sort_keys=False))

    print(f"[vybe-maker] edited {vybe_id}")
    return {"id": vybe_id, "name": info["name"], "custom": info["custom"]}


def reset_vybe(vybe_id: str) -> bool:
    """Drop a local edit and go back to the shipped persona."""
    path = OVERRIDE_DIR / f"{vybe_id}.yaml"
    if not path.exists():
        return False
    path.unlink()
    print(f"[vybe-maker] reset {vybe_id} to the shipped persona")
    return True


def delete_vybe(vybe_id: str, lab: VoiceLab | None = None) -> bool:
    """Remove the persona file and the cloned voice behind it."""
    path = CUSTOM_DIR / f"{vybe_id}.yaml"
    if not path.exists():
        return False
    data = yaml.safe_load(path.read_text()) or {}
    voice_id = (data.get("engine_config") or {}).get("voice_id")
    if voice_id:
        try:
            (lab or VoiceLab()).delete(voice_id)
        except VoiceLabError as e:
            # The persona still goes: a stale voice is easy to clear by
            # hand, a persona pointing at nothing is not.
            print(f"[vybe-maker] could not delete voice {voice_id}: {e}")
    path.unlink()
    print(f"[vybe-maker] deleted {vybe_id}")
    return True
