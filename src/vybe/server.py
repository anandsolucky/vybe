"""Local player server: serves the player page, session state, and media."""

import json
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
MAX_UPLOAD = 64 * 1024 * 1024   # all clips of one custom VYBE together


def parse_multipart(body: bytes, content_type: str) -> tuple[dict, list]:
    """Minimal multipart/form-data reader (the cgi module is gone in 3.13+).

    Returns (text fields, [(field, filename, bytes), ...]).
    """
    if "boundary=" not in content_type:
        raise ValueError("that upload was not multipart form data")
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    delim = b"--" + boundary.encode()
    fields, files = {}, []
    for part in body.split(delim)[1:-1]:
        part = part.lstrip(b"\r\n")
        if not part:
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        disp = ""
        for line in head.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-disposition"):
                disp = line
        name = re.search(r'name="([^"]*)"', disp)
        if not name:
            continue
        filename = re.search(r'filename="([^"]*)"', disp)
        if filename and filename.group(1):
            files.append((name.group(1), filename.group(1), data))
        else:
            fields[name.group(1)] = data.decode("utf-8", "replace")
    return fields, files


def make_handler(holder, source_path: str, session_dir: Path):
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
                "ico": "image/x-icon", "webmanifest": "application/manifest+json",
                "html": "text/html; charset=utf-8"}

        def _send_static(self, base: Path, rel: str) -> None:
            path = (base / rel).resolve()
            if not str(path).startswith(str(base.resolve())) or not path.is_file():
                self._send(404, b"not found", "text/plain")
                return
            ctype = self.MIME.get(path.suffix[1:], "application/octet-stream")
            self._send(200, path.read_bytes(), ctype)

        def _refresh_roster(self, reload_id: str | None = None) -> None:
            session = holder.get("session")
            if session is None:
                return
            if hasattr(session, "refresh_roster"):
                session.refresh_roster()
            if reload_id and hasattr(session, "reload_persona"):
                session.reload_persona(reload_id)

        def _create_vybe(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD:
                self._send(413, b"Those clips are too large together.", "text/plain")
                return
            body = self.rfile.read(length)
            try:
                fields, files = parse_multipart(
                    body, self.headers.get("Content-Type", ""))
            except ValueError as e:
                self._send(400, str(e).encode("utf-8"), "text/plain")
                return
            if fields.get("consent") != "yes":
                self._send(400, b"Confirm you have the right to use this voice.",
                           "text/plain")
                return
            try:
                from .core.vybe_maker import create_vybe
                from .providers.llm_openai import OpenAICompatibleLLM
                result = create_vybe(
                    fields.get("name", ""), fields.get("prompt", ""),
                    [(filename, data) for _, filename, data in files],
                    OpenAICompatibleLLM(),
                )
            except Exception as e:
                self._send(400, str(e).encode("utf-8"), "text/plain")
                return
            self._refresh_roster()
            self._send(200, json.dumps(result).encode(), "application/json")

        def do_DELETE(self) -> None:
            if self.path.startswith("/vybes/"):
                vybe_id = self.path.rsplit("/", 1)[-1]
                try:
                    from .core.vybe_maker import delete_vybe
                    ok = delete_vybe(vybe_id)
                except Exception as e:
                    self._send(400, str(e).encode("utf-8"), "text/plain")
                    return
                self._refresh_roster()
                self._send(200 if ok else 404, b"ok" if ok else b"not found",
                           "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def _edit_vybe(self, vybe_id: str) -> None:
            length = int(self.headers.get("Content-Length", 0))
            prompt = self.rfile.read(length).decode("utf-8", "replace")
            try:
                from .core.vybe_maker import edit_vybe
                from .providers.llm_openai import OpenAICompatibleLLM
                result = edit_vybe(vybe_id, prompt, OpenAICompatibleLLM())
            except Exception as e:
                self._send(400, str(e).encode("utf-8"), "text/plain")
                return
            self._refresh_roster(vybe_id)
            self._send(200, json.dumps(result).encode(), "application/json")

        def do_POST(self) -> None:
            if self.path == "/vybes":
                self._create_vybe()
            elif self.path.startswith("/vybes/") and self.path.endswith("/edit"):
                self._edit_vybe(self.path.split("/")[2])
            elif self.path.startswith("/vybes/") and self.path.endswith("/reset"):
                vybe_id = self.path.split("/")[2]
                from .core.vybe_maker import reset_vybe
                ok = reset_vybe(vybe_id)
                self._refresh_roster(vybe_id)
                self._send(200 if ok else 404, b"ok" if ok else b"nothing to reset",
                           "text/plain")
            elif self.path == "/reset":
                ok = bool(holder.get("reset")) and holder["reset"]()
                self._send(200 if ok else 409, b"ok" if ok else b"unsupported", "text/plain")
            elif self.path == "/language":
                length = int(self.headers.get("Content-Length", 0))
                code = self.rfile.read(length).decode("utf-8", "replace").strip()
                ok = holder["session"].switch_language(code)
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            elif self.path == "/switch":
                length = int(self.headers.get("Content-Length", 0))
                avatar_id = self.rfile.read(length).decode("utf-8", "replace").strip()
                ok = holder["session"].switch_lane(avatar_id)
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            elif self.path == "/parallel":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8", "replace").strip()
                ok = holder["session"].set_parallel(body == "on")
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            elif self.path == "/sport":
                length = int(self.headers.get("Content-Length", 0))
                sport = self.rfile.read(length).decode("utf-8", "replace").strip()
                ok = holder["session"].set_sport(sport)
                self._send(200 if ok else 409, b"ok" if ok else b"rejected", "text/plain")
            elif self.path == "/avatars":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8", "replace").strip()
                ids = [x.strip() for x in body.split(",") if x.strip()]
                ok = holder["session"].set_avatars(ids)
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
            elif self.path == "/favicon.ico":
                self._send_static(UI_DIR.parents[2] / "brand" / "assets", "favicon/favicon.ico")
            elif self.path.startswith("/brand/"):
                self._send_static(UI_DIR.parents[2] / "brand" / "assets", self.path[7:])
            elif self.path.startswith("/vybes/") and self.path != "/vybes/slots":
                try:
                    from .core.vybe_maker import describe_vybe
                    body = json.dumps(describe_vybe(self.path.split("/")[2])).encode()
                except Exception as e:
                    self._send(404, str(e).encode("utf-8"), "text/plain")
                    return
                self._send(200, body, "application/json")
            elif self.path == "/vybes/slots":
                try:
                    from .providers.voice_lab import VoiceLab
                    body = json.dumps(VoiceLab().slots()).encode()
                except Exception as e:
                    body = json.dumps({"error": str(e)}).encode()
                self._send(200, body, "application/json")
            elif self.path == "/state":
                self._send(200, json.dumps(holder["session"].state()).encode(),
                           "application/json")
            elif self.path == "/media/source":
                self._serve_file(Path(source_path))
            elif self.path.startswith("/media/"):
                self._serve_file(holder["session"].dir / Path(self.path).name)
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


def start(holder, source_path: str, session_dir: Path, port: int = 8791):
    handler = make_handler(holder, source_path, session_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
