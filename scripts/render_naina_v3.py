"""Naina v3 — the fair test of Bulbul v3's own emotional engine.

Changes vs v2, based on research:
  - ONE call per rendering: the full dramatic arc in a single text, so the
    LLM prosody engine has context to act the rise and fall itself.
  - Hinglish cricket vocabulary: six, bat, ball, catch, over, runs — English
    words in Latin script, never shuddh Hindi cricket terms.
  - Emotion written into the meaning of the words (that is Bulbul's only
    emotion interface). Line breaks = breathing; punctuation = drama.
  - ZERO post-processing. No gain, no pitch, no resampling.

3 synthesis calls: priya @ temp 0.9, priya @ temp 1.3, simran @ temp 0.9.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "avatars", "hi", "auditions")
API_URL = "https://api.sarvam.ai/text-to-speech"

SCENE = """आख़िरी over… छह ball, बारह runs। पूरा stadium खड़ा है… साँसें थमी हुईं…

Bowler दौड़ा… लंबा run-up… और ball एकदम full!

अरे मारा! पूरे दम से मारा! Bat घूमा और ball हवा में — ऊपर, और ऊपर, और ऊपर!

ये six होगा क्या?! ये six होगा क्या?!

पकड़ ली!! अरे पकड़ ली!! Long-on पर Suryakumar Yadav! क्या catch! क्या शानदार catch है!!

और बस… एक second में सब बदल गया। Six के सपने… fielder के हाथों में।

Cricket भी ना… एकदम फ़िल्मी है!"""

VARIANTS = [
    ("naina_v3_priya_t09.wav", "priya", 0.9),
    ("naina_v3_priya_t13.wav", "priya", 1.3),
    ("naina_v3_simran_t09.wav", "simran", 0.9),
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


def synth(speaker: str, temperature: float, api_key: str) -> bytes:
    payload = {
        "text": SCENE,
        "target_language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": speaker,
        "pace": 1.1,
        "temperature": temperature,
        "speech_sample_rate": 24000,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "api-subscription-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:800]}") from None
    return base64.b64decode(data["audios"][0])


def main() -> None:
    load_env()
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        sys.exit("SARVAM_API_KEY not set (expected in .env)")

    os.makedirs(OUT_DIR, exist_ok=True)
    calls = 0
    for filename, speaker, temperature in VARIANTS:
        try:
            wav = synth(speaker, temperature, api_key)
        except RuntimeError as err:
            print(f"[{filename}] FAILED: {err}", file=sys.stderr)
            continue
        calls += 1
        path = os.path.join(OUT_DIR, filename)
        with open(path, "wb") as f:
            f.write(wav)
        print(f"[{filename}] speaker={speaker} temp={temperature} ({len(wav) // 1024} KB)")
    print(f"Synthesis calls made: {calls}")


if __name__ == "__main__":
    main()
