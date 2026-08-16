"""Deepgram Nova-3 adapters: prerecorded file mode and live streaming."""

import json
import os
import threading
import urllib.request

from .base import Word

API_URL = "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&punctuate=true"
WS_URL = ("wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16"
          "&sample_rate={rate}&channels=1&smart_format=true&punctuate=true"
          "&interim_results=false")


class DeepgramASR:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")

    def transcribe_file(self, path: str) -> list[Word]:
        with open(path, "rb") as f:
            audio = f.read()
        req = urllib.request.Request(
            API_URL,
            data=audio,
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "audio/wav",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        words = data["results"]["channels"][0]["alternatives"][0]["words"]
        return [
            Word(w.get("punctuated_word", w["word"]), w["start"], w["end"])
            for w in words
        ]


class DeepgramStreamingASR:
    """Live WebSocket transcription. Word timestamps are on the source
    clock (seconds since the stream started)."""

    def __init__(self, rate: int = 16000, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        self.rate = rate

    def stream(self, chunk_iter, on_words) -> None:
        """Send PCM chunks; call on_words(list[Word]) for each final result."""
        from websockets.sync.client import connect

        url = WS_URL.format(rate=self.rate)
        with connect(url, additional_headers={"Authorization": f"Token {self.api_key}"}) as ws:

            def sender() -> None:
                try:
                    for chunk in chunk_iter:
                        ws.send(chunk)
                    ws.send(json.dumps({"type": "CloseStream"}))
                except Exception as err:  # socket closed mid-stream
                    print(f"[asr] stream ended: {type(err).__name__}")

            thread = threading.Thread(target=sender, daemon=True)
            thread.start()

            while True:
                try:
                    message = ws.recv()
                except Exception:
                    break
                if isinstance(message, bytes):
                    continue
                data = json.loads(message)
                if data.get("type") == "Metadata":
                    break
                if data.get("type") != "Results":
                    continue
                words = data["channel"]["alternatives"][0].get("words", [])
                if words:
                    on_words([
                        Word(w.get("punctuated_word", w["word"]), w["start"], w["end"])
                        for w in words
                    ])
                if data.get("from_finalize") or data.get("speech_final") is None:
                    continue
            thread.join(timeout=5)
