"""Render the Kabir and Naina audition scenes through Sarvam Bulbul v3.

Budget: exactly 6 synthesis calls (3 segments per avatar).
Zero dependencies — stdlib only. Reads SARVAM_API_KEY from ../.env.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "avatars", "hi", "auditions")
API_URL = "https://api.sarvam.ai/text-to-speech"
SAMPLE_RATE = 24000


def load_env() -> None:
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def synth(text: str, speaker: str, pace: float, temperature: float, api_key: str) -> bytes:
    """One Bulbul v3 call. Returns WAV bytes."""
    payload = {
        "text": text,
        "target_language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": speaker,
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
        body = e.read().decode(errors="replace")[:800]
        raise RuntimeError(f"HTTP {e.code} for speaker={speaker}: {body}") from None
    return base64.b64decode(data["audios"][0])


def wav_frames(wav_bytes: bytes) -> tuple:
    import io

    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getparams(), w.readframes(w.getnframes())


def stitch(clips: list, gaps: list, out_path: str) -> float:
    """Join WAV clips with silence gaps (seconds). Returns total duration."""
    params, _ = wav_frames(clips[0])
    silence_frame = b"\x00" * params.sampwidth * params.nchannels
    with wave.open(out_path, "wb") as out:
        out.setparams(params)
        for i, clip in enumerate(clips):
            _, frames = wav_frames(clip)
            out.writeframes(frames)
            if i < len(gaps) and gaps[i] > 0:
                out.writeframes(silence_frame * int(gaps[i] * params.framerate))
    with wave.open(out_path) as w:
        return w.getnframes() / w.getframerate()


# ---- Scenes: 3 segments each = 6 calls total (hard budget) ----
# Segment = (text, pace, gap_after_seconds)
# Punctuation is the prosody: , short pause · । / . medium · ! emphasis · … held breath.
# Kabir segment 2 embeds the vowel-elongation experiment ("गईईई").

SCENES = {
    "kabir": {
        "speaker": "aditya",
        "temperature": 0.85,
        "segments": [
            ("Last over चल रहा है भाई, और stadium में पूरा पागलपन! "
             "Bowler अपने mark पर… लंबा run-up… गहरी साँस…", 1.05, 0.55),
            ("गेंद full — और batsman ने खोल दिए कंधे! "
             "ये गई, ये गई, ये गईईई… हवा में, बहुत ऊँची!", 1.35, 0.3),
            ("अरे रुको रुको — long-on पर Suryakumar! नज़रें गेंद पर… और… पकड़ ली! "
             "Catch पकड़ ली भाई! Batsman एकदम cooked, सर झुकाए वापस। "
             "क्या scene था यार… क्या scene था।", 1.3, 0.0),
        ],
    },
    "naina": {
        "speaker": "priya",
        "temperature": 0.75,
        "segments": [
            ("तो आ गया वो moment… आख़िरी over, और साँसें थमी हुईं। "
             "Bowler दौड़ता हुआ आया — गेंद रखी ज़रा full, पूरे इरादे के साथ।", 1.0, 0.45),
            ("और बल्लेबाज़ की आँखों में वही चमक! पूरा दम, शॉट दिल से — "
             "गेंद ऊँची… बहुत ऊँची… stadium की रोशनी में बस एक सफ़ेद सी point…", 1.2, 0.35),
            ("लेकिन long-on पर Suryakumar Yadav! एक क़दम दाएँ, नज़र गेंद पर… और — वाह! "
             "क्या catch है! एक second पहले छक्के के सपने… और अब इतनी लंबी ख़ामोशी। "
             "Cricket भी ना — एकदम फ़िल्मी है!", 1.15, 0.0),
        ],
    },
}

# Fallback voices if a speaker name is rejected (a 400 synthesizes nothing).
FALLBACK_SPEAKERS = {
    "kabir": ["shubh", "abhilash", "karun", "hitesh"],
    "naina": ["anushka", "manisha", "vidya", "arya"],
}


def main() -> None:
    load_env()
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        sys.exit("SARVAM_API_KEY not set (expected in .env)")

    os.makedirs(OUT_DIR, exist_ok=True)
    calls_made = 0

    for avatar, scene in SCENES.items():
        candidates = [scene["speaker"]] + FALLBACK_SPEAKERS[avatar]
        clips, gaps, used_speaker = [], [], None

        for speaker in candidates:
            try:
                clips = []
                gaps = []
                for text, pace, gap in scene["segments"]:
                    clips.append(synth(text, speaker, pace, scene["temperature"], api_key))
                    calls_made += 1
                    gaps.append(gap)
                used_speaker = speaker
                break
            except RuntimeError as err:
                msg = str(err)
                print(f"[{avatar}] speaker '{speaker}' failed: {msg}", file=sys.stderr)
                if "HTTP 4" in msg and not clips:
                    continue  # invalid speaker rejected up front; try next voice
                raise

        if used_speaker is None:
            sys.exit(f"[{avatar}] no speaker candidate worked")

        out_path = os.path.join(OUT_DIR, f"{avatar}.wav")
        duration = stitch(clips, gaps, out_path)
        print(f"[{avatar}] voice={used_speaker} duration={duration:.1f}s -> {out_path}")

    print(f"Synthesis calls made: {calls_made}")


if __name__ == "__main__":
    main()
