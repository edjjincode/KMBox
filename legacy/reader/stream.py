"""실시간 중계 — 가상 모니터 화면(MJPEG) + 판독 결과 패널. 127.0.0.1 에만 열린다(SSH 터널로 본다)."""
from __future__ import annotations

import json, subprocess, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = (Path(__file__).parent / "stream_page.html").read_text(encoding="utf-8")


class LiveStream:
    def __init__(self, display: str, state_fn, port: int = 8765, fps: int = 6):
        self.display, self.state_fn, self.port, self.fps = display, state_fn, port, fps
        self.frame, self.cond, self.viewers = b"", threading.Condition(), 0
        self._ff = self._srv = None

    def _grab(self):
        self._ff = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-framerate", str(self.fps),
             "-video_size", "1920x1080", "-i", f"{self.display}.0", "-vf", "scale=1280:720", "-q:v", "6",
             "-f", "mjpeg", "-"], stdout=subprocess.PIPE)
        buf = b""
        while True:
            chunk = self._ff.stdout.read(65536)
            if not chunk: break
            buf += chunk
            while True:
                a = buf.find(b"\xff\xd8"); z = buf.find(b"\xff\xd9", a + 2)
                if a < 0 or z < 0: break
                with self.cond:
                    self.frame = buf[a:z + 2]; self.cond.notify_all()
                buf = buf[z + 2:]

    def start(self):
        threading.Thread(target=self._grab, daemon=True).start()
        live = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                if self.path == "/stream.mjpg":
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
                    self.send_header("Cache-Control", "no-store"); self.end_headers()
                    live.viewers += 1
                    try:
                        while True:
                            with live.cond:
                                live.cond.wait(timeout=2); jpg = live.frame
                            if jpg:
                                self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    finally:
                        live.viewers -= 1
                if self.path.startswith("/state.json"):
                    body, ctype = json.dumps(live.state_fn(), ensure_ascii=False).encode(), "application/json"
                else:
                    body, ctype = PAGE.encode(), "text/html; charset=utf-8"
                self.send_response(200); self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        self._srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._srv: self._srv.shutdown()
        if self._ff: self._ff.terminate()
