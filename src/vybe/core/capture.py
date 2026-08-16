"""Audio capture sources (ADR-010).

Every source yields s16le mono PCM chunks at the ASR sample rate.
FileSource paces chunks at real time to simulate a live feed.
AVFoundationSource reads a macOS capture device (iPhone over USB).
"""

import subprocess
import time
from collections.abc import Iterator

CHUNK_MS = 100


class FileSource:
    def __init__(self, path: str, rate: int = 16000, realtime: bool = True):
        self.path = path
        self.rate = rate
        self.realtime = realtime

    def chunks(self) -> Iterator[bytes]:
        chunk_bytes = int(self.rate * 2 * CHUNK_MS / 1000)
        proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", self.path,
             "-f", "s16le", "-ac", "1", "-ar", str(self.rate), "pipe:1"],
            stdout=subprocess.PIPE,
        )
        start = time.monotonic()
        sent = 0.0
        try:
            while True:
                chunk = proc.stdout.read(chunk_bytes)
                if not chunk:
                    break
                if self.realtime:
                    sent += CHUNK_MS / 1000
                    ahead = sent - (time.monotonic() - start)
                    if ahead > 0:
                        time.sleep(ahead)
                yield chunk
        finally:
            proc.stdout.close()
            proc.wait()


class CaptureMux:
    """One capture process, two outputs (live phone/screen mode).

    ffmpeg opens an avfoundation video+audio pair once and fans out:
      1. HLS (event playlist) into the session dir — the player's video.
      2. s16le mono PCM on stdout — the ASR feed.

    Typical pair: video = "Capture screen 0" showing the iPhone Mirroring
    window, audio = BlackHole (system output routed there, silent live —
    the viewer hears everything 15 s later in the player).
    """

    def __init__(self, video_index: int, audio_index: int, session_dir,
                 rate: int = 16000):
        self.video_index = video_index
        self.audio_index = audio_index
        self.session_dir = session_dir
        self.rate = rate
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        playlist = str(self.session_dir / "live.m3u8")
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error",
             "-f", "avfoundation", "-framerate", "30",
             "-capture_cursor", "0", "-pixel_format", "nv12",
             "-i", f"{self.video_index}:{self.audio_index}",
             # Output 1: HLS for the delayed player.
             "-map", "0:v", "-map", "0:a",
             "-c:v", "h264_videotoolbox", "-realtime", "1", "-b:v", "4M",
             "-vf", "scale=-2:720", "-g", "60",
             "-c:a", "aac", "-b:a", "128k", "-ac", "2",
             "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "event",
             playlist,
             # Output 2: PCM for ASR.
             "-map", "0:a", "-f", "s16le", "-ac", "1", "-ar", str(self.rate),
             "pipe:1"],
            stdout=subprocess.PIPE,
        )

    def chunks(self) -> Iterator[bytes]:
        if self.proc is None:
            self.start()
        chunk_bytes = int(self.rate * 2 * CHUNK_MS / 1000)
        try:
            while True:
                chunk = self.proc.stdout.read(chunk_bytes)
                if not chunk:
                    break
                yield chunk
        finally:
            self.stop()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def list_devices() -> dict:
    """Parse `ffmpeg -list_devices` into {video: [(idx, name)], audio: [...]}"""
    out = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True,
    ).stderr
    devices = {"video": [], "audio": []}
    section = None
    for line in out.splitlines():
        if "video devices" in line:
            section = "video"
        elif "audio devices" in line:
            section = "audio"
        elif section and "] [" in line:
            idx = int(line.split("] [")[1].split("]")[0])
            name = line.rsplit("]", 1)[1].strip()
            devices[section].append((idx, name))
    return devices


class AVFoundationSource:
    """Live audio from a macOS capture device, e.g. an iPhone over USB.

    List devices: ffmpeg -f avfoundation -list_devices true -i ""
    device is the avfoundation audio index (":1" style handled here).
    """

    def __init__(self, device_index: int, rate: int = 16000):
        self.device_index = device_index
        self.rate = rate

    def chunks(self) -> Iterator[bytes]:
        chunk_bytes = int(self.rate * 2 * CHUNK_MS / 1000)
        proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-f", "avfoundation",
             "-i", f":{self.device_index}",
             "-f", "s16le", "-ac", "1", "-ar", str(self.rate), "pipe:1"],
            stdout=subprocess.PIPE,
        )
        try:
            while True:
                chunk = proc.stdout.read(chunk_bytes)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            proc.wait()
