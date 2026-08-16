"""FFmpeg helpers: decode, crowd bed (ADR-009), and mux."""

import array
import subprocess
import wave


def mp3_to_mono(mp3_bytes: bytes, rate: int) -> array.array:
    """Decode mp3 bytes to 16-bit mono PCM at the given rate."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0",
         "-f", "s16le", "-ac", "1", "-ar", str(rate), "pipe:1"],
        input=mp3_bytes, capture_output=True, check=True,
    )
    return array.array("h", proc.stdout)


def write_wav(samples: array.array, rate: int, path: str) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def side_rms_db(src: str) -> float:
    """RMS level of the L-R side signal. Near -inf means mono source."""
    proc = subprocess.run(
        ["ffmpeg", "-i", src,
         "-af", "pan=mono|c0=0.5*c0+-0.5*c1,astats", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in proc.stderr.splitlines():
        if "RMS level dB" in line:
            value = line.rsplit(":", 1)[1].strip()
            try:
                return float(value)
            except ValueError:
                return float("-inf")
    return float("-inf")


def bed_filter(src: str, cfg: dict) -> str:
    """Pick the crowd-bed filter: center-cancel, or duck for mono sources."""
    floor = cfg.get("side_energy_floor_db", -45)
    gain = cfg.get("bed_gain", 2.0)
    duck = cfg.get("duck_level", 0.15)
    if cfg.get("bed") == "center_cancel" and side_rms_db(src) > floor:
        return f"pan=stereo|c0=c0-c1|c1=c1-c0,volume={gain}"
    return f"volume={duck}"


def mux(video_src: str, commentary_wav: str, out_path: str, bed: str | None) -> None:
    """Mux commentary onto the video. bed=None replaces the audio track."""
    if bed is None:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_src, "-i", commentary_wav,
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
               "-shortest", out_path]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_src, "-i", commentary_wav,
               "-filter_complex",
               f"[0:a]{bed}[bg];[1:a]aformat=channel_layouts=stereo[k];"
               f"[bg][k]amix=inputs=2:duration=first:normalize=0[a]",
               "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out_path]
    subprocess.run(cmd, check=True)
