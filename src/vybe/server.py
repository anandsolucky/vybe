"""Local player server: serves the player page, session state, and media."""

import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"


def make_handler(session, source_path: str, session_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console for pipeline logs
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        MIME = {"css": "text/css", "js": "application/javascript",
                "woff2": "font/woff2", "png": "image/png", "svg": "image/svg+xml",
                "html": "text/html; charset=utf-8"}

        def _send_static(self, base: Path, rel: str) -> None:
            path = (base / rel).resolve()
            if not str(path).startswith(str(base.resolve())) or not path.is_file():
                self._send(404, b"not found", "text/plain")
                return
            ctype = self.MIME.get(path.suffix[1:], "application/octet-stream")
            self._send(200, path.read_bytes(), ctype)

        def do_POST(self) -> None:
            if self.path == "/language":
                length = int(self.headers.get("Content-Length", 0))
                code = self.rfile.read(length).decode("utf-8", "replace").strip()
                ok = session.switch_language(code)
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            elif self.path == "/switch":
                length = int(self.headers.get("Content-Length", 0))
                avatar_id = self.rfile.read(length).decode("utf-8", "replace").strip()
                ok = session.switch_lane(avatar_id)
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            elif self.path == "/avatars":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8", "replace").strip()
                ids = [x.strip() for x in body.split(",") if x.strip()]
                ok = session.set_avatars(ids)
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, (UI_DIR / "player.html").read_bytes(),
                           "text/html; charset=utf-8")
            elif self.path == "/hls.min.js":
                self._send(200, (UI_DIR / "hls.min.js").read_bytes(),
                           "application/javascript")
            elif self.path.startswith("/ui/"):
                self._send_static(UI_DIR, self.path[4:])
            elif self.path.startswith("/brand/"):
                self._send_static(UI_DIR.parents[2] / "brand" / "assets", self.path[7:])
            elif self.path == "/state":
                import json
                self._send(200, json.dumps(session.state()).encode(),
                           "application/json")
            elif self.path == "/media/source":
                self._serve_file(Path(source_path))
            elif self.path.startswith("/media/"):
                self._serve_file(session_dir / Path(self.path).name)
            else:
                self._send(404, b"not found", "text/plain")

        def _serve_file(self, path: Path) -> None:
            if not path.exists():
                self._send(404, b"missing", "text/plain")
                return
            ctype = {"mov": "video/quicktime", "mp4": "video/mp4",
                     "mp3": "audio/mpeg",
                     "m3u8": "application/vnd.apple.mpegurl",
                     "ts": "video/mp2t"}.get(path.suffix[1:], "application/octet-stream")
            data = path.read_bytes()
            # Minimal range support so <video> can seek.
            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                start_s, _, end_s = range_header[6:].partition("-")
                start = int(start_s or 0)
                end = int(end_s) if end_s else len(data) - 1
                chunk = data[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
            else:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

    return Handler


def start(session, source_path: str, session_dir: Path, port: int = 8791):
    handler = make_handler(session, source_path, session_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
