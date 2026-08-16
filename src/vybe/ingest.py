"""WebSocket ingest: the player streams tab-audio PCM here for ASR.

The browser captures a Chrome tab (getDisplayMedia), downsamples its audio
to 16 kHz mono s16le, and sends binary frames. chunks() feeds them to the
live pipeline exactly like a file or device source.
"""

import queue
import threading

from websockets.sync.server import serve


class TabIngest:
    def __init__(self, port: int = 8790):
        self.port = port
        self.queue: queue.Queue = queue.Queue(maxsize=1024)
        self.connected = threading.Event()

    def _handler(self, ws) -> None:
        self.connected.set()
        try:
            for message in ws:
                if isinstance(message, bytes):
                    try:
                        self.queue.put(message, timeout=1)
                    except queue.Full:
                        pass  # ASR fell behind; drop rather than stall capture
        finally:
            self.queue.put(None)

    def start(self) -> None:
        server = serve(self._handler, "127.0.0.1", self.port)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def chunks(self):
        while True:
            item = self.queue.get()
            if item is None:
                break
            yield item
