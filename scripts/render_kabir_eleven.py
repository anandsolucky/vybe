"""Kabir via ElevenLabs v3 — fast bro-casual take.

User feedback applied:
  - 15-20 second target: text halved, no whisper beats, speed 1.1
  - bro language, casual and real, not overdone
  - Hinglish leaning English; complete sentences; है endings kept
  - famous long-standing premade voice (library voices need a paid plan):
    Chris (casual male), fallbacks Charlie / Liam / Adam

1 API call.
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "avatars", "hi", "auditions", "elevenlabs")

SCENE = """[excited] Last over, twelve runs चाहिए bro — पूरा stadium पागल हो रहा है!
Bowler आया — ball full है —
[shouts] और मारा! Bhai उसने पूरा bat घुमा दिया है! Ball हवा में है — long-on के ऊपर!
[shouts] ये SIX है? ये SIX है?!
Suryakumar boundary पर — jump —
[shouts] CAUGHT! पकड़ लिया bhai! What a CATCH!
[laughs] Scenes, bro. Full scenes. एक second में match पलट गया है!"""

VOICES = [
    ("Chris", "iP95p4xoKVk53GoZ742B"),
    ("Charlie", "IKne3meq5aSn9XLyUdCD"),
    ("Liam", "TX3LPaxmHKxFdv7VOQHJ"),
    ("Adam", "pNInz6obpgDQGcFmaJgB"),
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


def synth(text: str, api_key: str, voice_id: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    payload = {
        "text": text,
        "model_id": "eleven_v3",
        "voice_settings": {"stability": 0.0, "speed": 1.1},
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


def main() -> None:
    load_env()
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY not set in .env")

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, vid in VOICES:
        try:
            audio = synth(SCENE, api_key, vid)
        except RuntimeError as err:
            print(f"voice {name} unavailable: {err}", file=sys.stderr)
            continue
        path = os.path.join(OUT_DIR, "kabir_eleven_take1.mp3")
        with open(path, "wb") as f:
            f.write(audio)
        print(f"[kabir_eleven_take1.mp3] voice={name} ({len(audio) // 1024} KB)")
        return
    sys.exit("no usable voice found")


if __name__ == "__main__":
    main()
