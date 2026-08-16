"""Naina v5 — fixing the flat middle (strike + ball-in-air suspense).

Root cause found in Sarvam's docs: ellipsis = hesitation/trailing-off.
The v4 flight section was scored with ellipses, so the model trailed off
at the peak. Fix, using both levers:

  TEXT  - flight beat has ZERO ellipses: stacked short exclamations,
          urgent present tense, escalating repetition, shouted questions.
  MODEL - split at the three natural beats (docs sanction splitting at
          pause points); the middle beat gets pace 1.3-1.35 and temp 1.0,
          while build-up and aftermath keep their calmer settings.

4 calls: beat1, beat2 variant A, beat2 variant B, beat3.
Stitched into two files that share beats 1 and 3:
  naina_v5_A.wav = beat1 + beat2A + beat3
  naina_v5_B.wav = beat1 + beat2B + beat3
"""

import array
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "avatars", "hi", "auditions")
API_URL = "https://api.sarvam.ai/text-to-speech"
SPEAKER = "simran"
SAMPLE_RATE = 24000

# Beat 1 — hush (user-approved from v4 theatrical; ellipses correct here)
BEAT1 = (
    "धीरे से बताऊँ?… bowler की हथेली में पसीना है। "
    "छह ball… बारह runs… और एक लाख लोगों की साँसें… रुकी हुईं।\n\n"
    "आया bowler… आया… और ball एकदम full—"
)

# Beat 2A — strike + flight: pure urgency, no ellipses anywhere
BEAT2_A = (
    "मारा!! अरे क्या मारा है!! पूरा bat घूमा, पूरी ताक़त, सीधा long-on के ऊपर!!\n\n"
    "Ball हवा में है!! लंबी है, बहुत लंबी है!! जाएगी! जाएगी!! Six जाएगी क्या?!\n\n"
    "रुको — Suryakumar भाग रहा है!! Boundary पर!! नज़र ऊपर, हाथ तैयार!!"
)

# Beat 2B — hotter: crowd pulled in, even shorter bursts
BEAT2_B = (
    "मारा!! ग़ज़ब का shot!! Bat की आवाज़ बता रही है — ये बहुत बड़ा है!!\n\n"
    "Ball आसमान में!! सुनिए stadium को — सब चिल्ला रहे हैं!! "
    "लंबी है!! बहुत लंबी है!! Six!? Six!?\n\n"
    "नहीं अभी नहीं — boundary पर Suryakumar!! भागा!! कूदा!!"
)

# Beat 3 — catch + aftermath (user-approved; ellipses return for the exhale)
BEAT3 = (
    "पकड़ लिया!!! क्या!!! क्या पकड़ा है!!!\n\n"
    "उफ़्फ़… यक़ीन नहीं हो रहा। Six लिखा जा चुका था… "
    "और Suryakumar ने कहानी ही पलट दी!\n\n"
    "हा! Cricket… इसीलिए तो देखते हैं हम!"
)

# (name, text, pace, temperature)
BEATS = {
    "beat1": (BEAT1, 1.0, 0.85),
    "beat2a": (BEAT2_A, 1.3, 1.0),
    "beat2b": (BEAT2_B, 1.35, 1.0),
    "beat3": (BEAT3, 1.15, 0.95),
}

FILES = {
    "naina_v5_A.wav": [("beat1", 0.2), ("beat2a", 0.15), ("beat3", 0.0)],
    "naina_v5_B.wav": [("beat1", 0.2), ("beat2b", 0.15), ("beat3", 0.0)],
}


def load_env() -> None:
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def synth(text: str, pace: float, temperature: float, api_key: str) -> bytes:
    payload = {
        "text": text,
        "target_language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": SPEAKER,
        "pace": pace,
        "temperature": temperature,
        "speech_sample_rate": SAMPLE_RATE,
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


def read_wav(wav_bytes: bytes) -> tuple:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getparams(), w.readframes(w.getnframes())


def main() -> None:
    load_env()
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        sys.exit("SARVAM_API_KEY not set (expected in .env)")

    os.makedirs(OUT_DIR, exist_ok=True)

    rendered = {}
    calls = 0
    for name, (text, pace, temp) in BEATS.items():
        rendered[name] = read_wav(synth(text, pace, temp, api_key))
        calls += 1
        print(f"  [{name}] pace={pace} temp={temp}")

    for filename, sequence in FILES.items():
        params = rendered[sequence[0][0]][0]
        out_path = os.path.join(OUT_DIR, filename)
        with wave.open(out_path, "wb") as out:
            out.setparams(params)
            for beat_name, gap in sequence:
                _, frames = rendered[beat_name]
                out.writeframes(frames)
                if gap > 0:
                    out.writeframes(b"\x00\x00" * int(gap * SAMPLE_RATE))
        with wave.open(out_path) as w:
            duration = w.getnframes() / w.getframerate()
        print(f"[{filename}] {duration:.1f}s")

    print(f"Synthesis calls made: {calls}")


if __name__ == "__main__":
    main()
