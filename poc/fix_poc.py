"""Re-render only the overflowing segments (2,3,4) with tightened text,
reuse the good cached takes for 1 and 5, rebuild the track, re-mux."""

import array
import os
import subprocess
import sys
import wave

import build_poc as bp

POC = bp.POC
RATE = bp.RATE

NEW_TEXTS = {
    2: (10.32, 14.2, "[shouts] और मारा! सीधा straight — ये गई!"),
    3: (14.3, 18.9, "[shouts] SIX! Stadium के बाहर bhai! क्या hit है!"),
    4: (19.1, 27.0,
        "[excited] Kohli 68 off 49 — on fire है bhai! "
        "ये वही Kohli है — form वापस, swagger वापस!"),
}
KEEP = {1: 1.2, 5: 27.3}  # segment -> anchor, reuse cached seg_N.mp3


def main() -> None:
    bp.load_env()
    api_key = os.environ["ELEVENLABS_API_KEY"]

    track = array.array("h", bytes(2 * int(bp.VIDEO_DUR * RATE)))
    report = []
    calls = 0

    pieces = {}
    for i, anchor in KEEP.items():
        with open(os.path.join(POC, f"seg_{i}.mp3"), "rb") as f:
            pieces[i] = (anchor, None, bp.mp3_to_mono44k(f.read(), f"{i}k"))

    for i, (anchor, slot_end, text) in NEW_TEXTS.items():
        slot = slot_end - anchor
        speed = 1.1
        samples = bp.mp3_to_mono44k(bp.synth(text, speed, api_key), f"{i}f")
        calls += 1
        if len(samples) / RATE > slot:
            speed = 1.2
            samples = bp.mp3_to_mono44k(bp.synth(text, speed, api_key), f"{i}f2")
            calls += 1
        dur = len(samples) / RATE
        report.append((i, anchor, slot, dur, speed, "OK" if dur <= slot else "OVERFLOW"))
        pieces[i] = (anchor, slot_end, samples)

    for i in sorted(pieces):
        anchor, _, samples = pieces[i]
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
    for i, anchor, slot, dur, speed, fit in sorted(report):
        print(f"{i:>3} {anchor:>6.2f}s {slot:>5.2f}s {dur:>5.2f}s {speed:>5.2f}  {fit}")
    print(f"API calls this fix: {calls}")


if __name__ == "__main__":
    main()
