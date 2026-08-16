"""Naina via ElevenLabs v3 — first API render.

Per the official v3 prompting guide:
  - audio tags immediately before the words they modify (~4-5 word scope)
  - CAPS = loudness (Latin script only, so English cricket words carry it)
  - ellipses add weight/pauses — quiet beats only
  - stability: Creative (0.0) is most tag-responsive; Natural (0.5) balanced
  - generations vary -> render two takes and pick by ear

2 API calls: same text, take1 stability=0.0 (Creative), take2 0.5 (Natural).
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "avatars", "hi", "auditions")

SCENE = """[whispers] सुनिए… पूरा stadium ख़ामोश है। छह ball… बारह runs… सब कुछ दाँव पर।

[whispers] Bowler दौड़ रहा है… लंबा run-up… ball एकदम full—

[excited] मारा! बल्ले की आवाज़ बता रही है — ये बहुत दूर गया!

[shouts] Ball हवा में है! Long-on के ऊपर! अभी भी उठ रही है! [shouts] ये SIX जा रही है? जा रही है?!

[gasps] Boundary पर Suryakumar… कूदा—

[shouts] पकड़ लिया! क्या CATCH! क्या CATCH है!!

[amazed] हवा में… boundary से दो क़दम अंदर… दो हाथों से, पूरे यक़ीन के साथ।

[sighs] और batsman… वहीं खड़ा है, bat पर टिका हुआ। उसे अब भी लग रहा है — वो six था।

[warmly] एक second… बस एक second में पूरी कहानी पलट गई। Cricket इसीलिए तो देखते हैं हम!"""

TAKES = [
    ("naina_eleven_take1_creative.mp3", 0.0),
    ("naina_eleven_take2_natural.mp3", 0.5),
]


def load_env() -> None:
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def synth(text: str, stability: float, api_key: str, voice_id: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    payload = {
        "text": text,
        "model_id": "eleven_v3",
        "voice_settings": {"stability": stability},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "xi-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:800]}") from None



# The user's chosen library voice needs a paid plan for API use (402).
# Premade voices work on the Free API — try these expressive female voices
# in order. A 402/404 synthesizes nothing and bills nothing.
VOICE_CANDIDATES = [
    ("user-choice", None),  # filled from .env; skipped automatically on 402
    ("Jessica", "cgSgspJ2msm6clMCkdW9"),
    ("Rachel", "21m00Tcm4TlvDq8ikWAM"),
    ("Sarah", "EXAVITQu4vr4xnSDxMaL"),
]


def main() -> None:
    load_env()
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY not set in .env")

    candidates = [
        (name, vid or os.environ.get("ELEVENLABS_VOICE_ID"))
        for name, vid in VOICE_CANDIDATES
    ]
    os.makedirs(OUT_DIR, exist_ok=True)

    chosen = None
    for name, vid in candidates:
        if not vid:
            continue
        try:
            filename, stability = TAKES[0]
            audio = synth(SCENE, stability, api_key, vid)
            chosen = (name, vid)
            with open(os.path.join(OUT_DIR, filename), "wb") as f:
                f.write(audio)
            print(f"[{filename}] voice={name} stability={stability} ({len(audio) // 1024} KB)")
            break
        except RuntimeError as err:
            print(f"voice {name} ({vid}) unavailable: {err}", file=sys.stderr)

    if not chosen:
        sys.exit("no usable voice found")

    name, vid = chosen
    filename, stability = TAKES[1]
    audio = synth(SCENE, stability, api_key, vid)
    with open(os.path.join(OUT_DIR, filename), "wb") as f:
        f.write(audio)
    print(f"[{filename}] voice={name} stability={stability} ({len(audio) // 1024} KB)")
    print("Done.")


if __name__ == "__main__":
    main()
