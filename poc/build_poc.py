"""POC: Kohli six clip -> Kabir Hindi commentary, timed and muxed.

Pipeline (offline mirror of the live design):
  1. Segments anchored to source-commentary reaction times (ADR-012):
     never start before the anchor; each must fit its slot.
  2. Render each segment via ElevenLabs v3 with Kabir's spec
     (avatars/hi/kabir.yaml): voice Chris, stability 0.0, speed 1.1.
     If a segment overflows its slot, retry once at speed 1.2.
  3. Assemble a clean 44.1kHz track, placing segments at their anchors.
  4. Mux two outputs: full replace, and ducked (original at 15%).
"""

import array
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import wave

POC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(POC)
RATE = 44100
VIDEO_DUR = 29.53

VOICE_ID = "iP95p4xoKVk53GoZ742B"  # Chris — Kabir's finalized voice

# (anchor_s, slot_end_s, text)
SEGMENTS = [
    (1.2, 9.3,
     "[excited] MCG भाई, 28 चाहिए 8 ball में — Kohli strike पर है, "
     "और पूरा stadium खड़ा है! Pressure? Full pressure!"),
    (10.32, 14.2,
     "[shouts] और मारा! सीधा, straight — ये गई! ये गई!"),
    (14.3, 18.9,
     "[shouts] SIX! Ground के बाहर! MCG के बाहर bhai! क्या hit है!"),
    (19.1, 27.0,
     "[excited] Kohli 68 off 49 — on fire है bhai! ये वही Kohli है — "
     "form वापस, swagger वापस, sab वापस!"),
    (27.3, 29.4,
     "[laughs] Scenes, bro. Scenes!"),
]


def load_env() -> None:
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def synth(text: str, speed: float, api_key: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=mp3_44100_128"
    payload = {
        "text": text,
        "model_id": "eleven_v3",
        "voice_settings": {"stability": 0.0, "speed": speed},
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
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}") from None


def mp3_to_mono44k(mp3_bytes: bytes, tag: str) -> array.array:
    mp3_path = os.path.join(POC, f"seg_{tag}.mp3")
    wav_path = os.path.join(POC, f"seg_{tag}.wav")
    with open(mp3_path, "wb") as f:
        f.write(mp3_bytes)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", mp3_path,
         "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", wav_path],
        check=True,
    )
    with wave.open(wav_path) as w:
        return array.array("h", w.readframes(w.getnframes()))


def main() -> None:
    load_env()
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY not set")

    track = array.array("h", bytes(2 * int(VIDEO_DUR * RATE)))
    report = []
    calls = 0

    for i, (anchor, slot_end, text) in enumerate(SEGMENTS, 1):
        slot = slot_end - anchor
        speed = 1.1
        samples = mp3_to_mono44k(synth(text, speed, api_key), f"{i}")
        calls += 1
        dur = len(samples) / RATE
        if dur > slot:
            speed = 1.2
            samples = mp3_to_mono44k(synth(text, speed, api_key), f"{i}r")
            calls += 1
            dur = len(samples) / RATE
        fit = "OK" if dur <= slot else "OVERFLOW"
        report.append((i, anchor, slot, dur, speed, fit))

        start = int(anchor * RATE)
        end = min(start + len(samples), len(track))
        track[start:end] = samples[: end - start]

    kabir_wav = os.path.join(POC, "kabir_track.wav")
    with wave.open(kabir_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(track.tobytes())

    src = os.path.join(POC, "source.mov")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, "-i", kabir_wav,
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-shortest", os.path.join(POC, "kohli_six_kabir_replace.mp4")],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, "-i", kabir_wav,
         "-filter_complex",
         "[0:a]volume=0.15[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
         os.path.join(POC, "kohli_six_kabir_ducked.mp4")],
        check=True,
    )

    print(f"{'seg':>3} {'anchor':>7} {'slot':>6} {'audio':>6} {'speed':>5}  fit")
    for i, anchor, slot, dur, speed, fit in report:
        print(f"{i:>3} {anchor:>6.2f}s {slot:>5.2f}s {dur:>5.2f}s {speed:>5.2f}  {fit}")
    print(f"API calls: {calls}")
    print("outputs: kohli_six_kabir_replace.mp4, kohli_six_kabir_ducked.mp4")


if __name__ == "__main__":
    main()
