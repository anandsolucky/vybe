"""ElevenLabs voice library: clone a voice, delete it, count the slots.

A custom VYBE clones a voice from the clips the viewer uploads. Every
voice we create carries VOICE_SUFFIX, so the whole set is easy to find
and remove later. Plans cap how many cloned voices an account may hold
(Creator: 10), so slots() reports the budget before an upload starts.
"""

import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid

API = "https://api.elevenlabs.io/v1"
VOICE_SUFFIX = " · VYBE sports"

MIN_CLIPS = 3
MAX_CLIPS = 10
MAX_CLIP_BYTES = 12 * 1024 * 1024      # one clip
MAX_TOTAL_BYTES = 60 * 1024 * 1024     # all clips together


class VoiceLabError(RuntimeError):
    """The API said no. The message is safe to show the viewer."""


def _guess_type(filename: str) -> str:
    kind, _ = mimetypes.guess_type(filename)
    return kind if kind and kind.startswith("audio") else "audio/mpeg"


def _multipart(fields: list[tuple[str, str]],
               files: list[tuple[str, str, bytes]]) -> tuple[str, bytes]:
    """Build a multipart/form-data body. Returns (content_type, body)."""
    boundary = "----vybe" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields:
        out += (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n").encode()
    for name, filename, data in files:
        out += (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {_guess_type(filename)}\r\n\r\n").encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)


class VoiceLab:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise VoiceLabError("ELEVENLABS_API_KEY is not set")

    def _call(self, method: str, path: str, *, body: bytes | None = None,
              ctype: str | None = None, timeout: int = 180) -> dict:
        req = urllib.request.Request(f"{API}{path}", data=body, method=method)
        req.add_header("xi-api-key", self.api_key)
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                payload = json.loads(e.read())
                err = payload.get("detail", payload)
                detail = err.get("message") if isinstance(err, dict) else str(err)
            except Exception:
                pass
            if "missing the permission" in (detail or ""):
                # Scoped keys are the usual cause. Name the exact toggles.
                detail += (" Edit this API key in the ElevenLabs dashboard and "
                           "enable: Voices (read and write), Instant Voice "
                           "Cloning, and User (read).")
            raise VoiceLabError(detail or f"ElevenLabs returned {e.code}") from e
        except urllib.error.URLError as e:
            raise VoiceLabError(f"Could not reach ElevenLabs: {e.reason}") from e

    # -- creating and removing -------------------------------------------
    def clone(self, name: str, clips: list[tuple[str, bytes]],
              description: str = "") -> dict:
        """Clone a voice from uploaded clips. Returns the API payload."""
        if not (MIN_CLIPS <= len(clips) <= MAX_CLIPS):
            raise VoiceLabError(
                f"Upload between {MIN_CLIPS} and {MAX_CLIPS} clips "
                f"(you sent {len(clips)}).")
        total = sum(len(data) for _, data in clips)
        for filename, data in clips:
            if len(data) > MAX_CLIP_BYTES:
                raise VoiceLabError(
                    f"{filename} is larger than {MAX_CLIP_BYTES // 1024 // 1024}MB.")
            if not data:
                raise VoiceLabError(f"{filename} is empty.")
        if total > MAX_TOTAL_BYTES:
            raise VoiceLabError(
                f"The clips add up to more than "
                f"{MAX_TOTAL_BYTES // 1024 // 1024}MB together.")

        ctype, body = _multipart(
            fields=[("name", name + VOICE_SUFFIX),
                    ("description", description[:480]),
                    ("remove_background_noise", "true")],
            files=[("files", filename, data) for filename, data in clips],
        )
        return self._call("POST", "/voices/add", body=body, ctype=ctype)

    def delete(self, voice_id: str) -> None:
        self._call("DELETE", f"/voices/{voice_id}", timeout=30)

    # -- what the account can still hold ---------------------------------
    def slots(self) -> dict:
        """How many cloned voices exist, and how many the plan allows.

        Reports the failure rather than a zero: a key without voices_read
        would otherwise look like an empty library.
        """
        used, limit, ours, error = 0, None, 0, None
        try:
            voices = self._call("GET", "/voices", timeout=30).get("voices", [])
            for v in voices:
                if v.get("category") in ("cloned", "professional"):
                    used += 1
                    if (v.get("name") or "").endswith(VOICE_SUFFIX):
                        ours += 1
        except VoiceLabError as e:
            error = str(e)
        try:
            sub = self._call("GET", "/user/subscription", timeout=30)
            limit = sub.get("voice_limit")
        except VoiceLabError:
            pass
        out = {"used": used, "limit": limit, "vybe_voices": ours}
        if error:
            out["error"] = error
        return out
