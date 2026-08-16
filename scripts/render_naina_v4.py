"""Naina v4 — text-as-performance iteration.

One variable changes vs round 3: the WRITING. Voice (simran) and
temperature (0.9) held constant. Two contrasting text treatments:

  A "broadcast"   — authentic Hindi TV commentary register, moderate drama
  B "theatrical"  — broken syntax, whisper-to-scream, maximal performance

2 synthesis calls. No post-processing. Rules: docs/tts-writing-guide.md
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
SPEAKER = "simran"
TEMPERATURE = 0.9

SCENE_A = """तो यहाँ से सिर्फ़ छह ball, और चाहिए बारह runs… stadium में एक अजीब सी ख़ामोशी… हर आँख bowler पर।

Bowler आया… और ball एकदम full!

उठा दिया हवा में!! बहुत बड़ा shot!! ये गया… ये बहुत दूर गया!!

Six? Six होगा?

नहीं!! Long-on पर Suryakumar!! पकड़ लिया!! अरे क्या catch पकड़ा है!!

यक़ीन नहीं होता… हाथ से निकलता हुआ six, और Suryakumar ने हवा में लपक लिया!

क्या match है… दिल थाम के बैठिए, अभी पाँच ball बाक़ी हैं!"""

SCENE_B = """धीरे से बताऊँ?… bowler की हथेली में पसीना है। छह ball… बारह runs… और एक लाख लोगों की साँसें… रुकी हुईं।

आया bowler… आया… और ball full—

मारा!! अरे पूरा bat घुमा के मारा!!

ये गई… ये गई… ये तो बहुत ऊपर… ओहो!!

रुकिए… रुकिए… boundary पर Suryakumar… उछला…

पकड़ लिया!!! क्या!!! क्या पकड़ा है!!!

उफ़्फ़… यक़ीन नहीं हो रहा। Six लिखा जा चुका था… और Suryakumar ने कहानी ही पलट दी!

हा! Cricket… इसीलिए तो देखते हैं हम!"""

VARIANTS = [
    ("naina_v4_A_broadcast.wav", SCENE_A),
    ("naina_v4_B_theatrical.wav", SCENE_B),
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


def synth(text: str, api_key: str) -> bytes:
    payload = {
        "text": text,
        "target_language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": SPEAKER,
        "pace": 1.1,
        "temperature": TEMPERATURE,
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
    for filename, scene in VARIANTS:
        wav = synth(scene, api_key)
        calls += 1
        path = os.path.join(OUT_DIR, filename)
        with open(path, "wb") as f:
            f.write(wav)
        print(f"[{filename}] speaker={SPEAKER} temp={TEMPERATURE} ({len(wav) // 1024} KB)")
    print(f"Synthesis calls made: {calls}")


if __name__ == "__main__":
    main()
