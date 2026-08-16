"""Naina POC cut — chatty Gen-Z vlogger persona, user-picked library voice.
Same anchors/slots as the Kabir cut. Output: ducked version only."""

import array
import os
import subprocess
import sys
import wave

import build_poc as bp

POC = bp.POC
RATE = bp.RATE
# User-picked library voice (3uuqz7fBxbNsCUVbBVKR) is 402-blocked on the
# Free plan via API. Try it first (a block bills nothing), then fall back
# to premade stand-ins closest to "chatty Gen-Z vlogger".
VOICE_CANDIDATES = [
    "3uuqz7fBxbNsCUVbBVKR",  # user's pick — works after plan upgrade
    "FGY2WhTYpPnrIDTdsKH5",  # Laura (premade, sassy/quirky)
    "cgSgspJ2msm6clMCkdW9",  # Jessica (premade, playful)
]
NAINA_VOICE = None  # resolved at runtime

SEGMENTS = [
    (1.2, 9.3,
     "[excited] Guys, guys — 28 चाहिए 8 ball में, MCG पूरा पागल है — "
     "और strike पर? Kohli. Literally goosebumps, yaar!"),
    (10.32, 14.2,
     "[shouts] Oh my god मारा! सीधा straight — ये गई!"),
    (14.3, 18.9,
     "[shouts] SIX! Stadium के बाहर! Literally बाहर, guys! क्या hit है!"),
    (19.1, 27.0,
     "[excited] Kohli 68 off 49 — on fire है yaar! ये वही Kohli है — "
     "form वापस, vibe वापस. Iconic innings, guys!"),
    (27.3, 29.4,
     "[laughs] What a shot, yaar!"),
]


def resolve_voice(api_key: str) -> str:
    for vid in VOICE_CANDIDATES:
        try:
            bp.VOICE_ID = vid
            bp.synth("[excited] Test है!", 1.1, api_key)
            return vid
        except RuntimeError as err:
            print(f"voice {vid} unavailable: {err}", file=sys.stderr)
    sys.exit("no usable voice")


def synth(text: str, speed: float, api_key: str) -> bytes:
    bp.VOICE_ID = NAINA_VOICE
    return bp.synth(text, speed, api_key)


def main() -> None:
    global NAINA_VOICE
    bp.load_env()
    api_key = os.environ["ELEVENLABS_API_KEY"]
    NAINA_VOICE = resolve_voice(api_key)
    print(f"using voice: {NAINA_VOICE}")

    track = array.array("h", bytes(2 * int(bp.VIDEO_DUR * RATE)))
    report = []
    calls = 0

    for i, (anchor, slot_end, text) in enumerate(SEGMENTS, 1):
        slot = slot_end - anchor
        speed = 1.1
        samples = bp.mp3_to_mono44k(synth(text, speed, api_key), f"n{i}")
        calls += 1
        if len(samples) / RATE > slot:
            speed = 1.2
            samples = bp.mp3_to_mono44k(synth(text, speed, api_key), f"n{i}r")
            calls += 1
        dur = len(samples) / RATE
        report.append((i, anchor, slot, dur, speed, "OK" if dur <= slot else "OVERFLOW"))

        start = int(anchor * RATE)
        end = min(start + len(samples), len(track))
        track[start:end] = samples[: end - start]

    naina_wav = os.path.join(POC, "naina_track.wav")
    with wave.open(naina_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(track.tobytes())

    src = os.path.join(POC, "source.mov")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, "-i", naina_wav,
         "-filter_complex",
         "[0:a]volume=0.15[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
         os.path.join(POC, "kohli_six_naina_ducked.mp4")],
        check=True,
    )

    print(f"{'seg':>3} {'anchor':>7} {'slot':>6} {'audio':>6} {'speed':>5}  fit")
    for i, anchor, slot, dur, speed, fit in report:
        print(f"{i:>3} {anchor:>6.2f}s {slot:>5.2f}s {dur:>5.2f}s {speed:>5.2f}  {fit}")
    print(f"API calls: {calls}")


if __name__ == "__main__":
    main()
