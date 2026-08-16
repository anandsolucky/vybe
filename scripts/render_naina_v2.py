"""Naina v2 — dynamic delivery experiment.

Six short segments with strong pace contrast (0.95-1.5), per-segment
temperature, and local post-processing Bulbul v3 does not offer:
  - loudness contrast (calm segments attenuated, shout at full level)
  - micro pitch-lift (~3-4%) on the flight and catch segments

Budget: exactly 6 synthesis calls. Stdlib only.
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
OUT_PATH = os.path.join(ROOT, "avatars", "hi", "auditions", "naina_v2.wav")
API_URL = "https://api.sarvam.ai/text-to-speech"
SAMPLE_RATE = 24000
SPEAKER = "priya"

# (text, pace, temperature, gain, pitch_factor, gap_after_s)
# gain <= 1.0 everywhere: contrast comes from pulling the calm DOWN.
# pitch_factor > 1.0 raises pitch and speed slightly (excitement rise).
SEGMENTS = [
    ("आख़िरी over… scoreboard कह रहा है — छह गेंद, बारह रन। "
     "पूरा stadium खड़ा है… साँसें थमी हुईं…",
     0.95, 0.70, 0.72, 1.0, 0.55),

    ("Bowler दौड़ा… लंबा run-up, रफ़्तार बढ़ती हुई — और गेंद full!",
     1.15, 0.75, 0.82, 1.0, 0.2),

    ("अरे मारा! पूरे दम से मारा! बल्ला घूमा — और गेंद हवा में!",
     1.45, 0.90, 0.95, 1.0, 0.1),

    ("ऊपर, और ऊपर, और ऊपर! ये तो बहुत बड़ा लग रहा है… "
     "छक्का होगा क्या? छक्का होगा क्या?!",
     1.5, 0.90, 1.0, 1.03, 0.15),

    ("पकड़ ली!! अरे पकड़ ली!! Long-on पर Suryakumar Yadav! "
     "क्या catch! क्या catch है!!",
     1.4, 0.95, 1.0, 1.045, 0.4),

    ("और बस… एक second में सब बदल गया। छक्के के सपने… fielder की हथेली में। "
     "Cricket भी ना… एकदम फ़िल्मी है।",
     0.95, 0.70, 0.75, 1.0, 0.0),
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
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:800]}") from None
    return base64.b64decode(data["audios"][0])


def read_wav(wav_bytes: bytes) -> tuple:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getsampwidth() != 2:
            sys.exit("expected 16-bit PCM")
        return w.getparams(), array.array("h", w.readframes(w.getnframes()))


def apply_gain(samples: array.array, gain: float) -> array.array:
    if gain == 1.0:
        return samples
    out = array.array("h", bytes(len(samples) * 2))
    for i, s in enumerate(samples):
        v = int(s * gain)
        out[i] = max(-32768, min(32767, v))
    return out


def pitch_lift(samples: array.array, factor: float) -> array.array:
    """Linear resample: factor > 1.0 -> shorter, faster, higher-pitched."""
    if factor == 1.0:
        return samples
    n = len(samples)
    new_n = int(n / factor)
    out = array.array("h", bytes(new_n * 2))
    for i in range(new_n):
        pos = i * factor
        j = int(pos)
        frac = pos - j
        a = samples[j]
        b = samples[j + 1] if j + 1 < n else a
        out[i] = int(a + (b - a) * frac)
    return out


def main() -> None:
    load_env()
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        sys.exit("SARVAM_API_KEY not set (expected in .env)")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    params = None
    pieces = []
    calls = 0
    for text, pace, temp, gain, pitch, gap in SEGMENTS:
        wav_bytes = synth(text, pace, temp, api_key)
        calls += 1
        p, samples = read_wav(wav_bytes)
        params = params or p
        samples = pitch_lift(samples, pitch)
        samples = apply_gain(samples, gain)
        pieces.append((samples, gap))
        print(f"  segment {calls}: pace={pace} temp={temp} gain={gain} pitch={pitch} "
              f"({len(samples) / SAMPLE_RATE:.1f}s)")

    with wave.open(OUT_PATH, "wb") as out:
        out.setparams(params)
        for samples, gap in pieces:
            out.writeframes(samples.tobytes())
            if gap > 0:
                out.writeframes(b"\x00\x00" * int(gap * SAMPLE_RATE))

    with wave.open(OUT_PATH) as w:
        duration = w.getnframes() / w.getframerate()
    print(f"voice={SPEAKER} duration={duration:.1f}s calls={calls} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
