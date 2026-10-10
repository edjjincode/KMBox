#!/usr/bin/env python3
"""v2 VLM 폐루프 보드 — 이상 6종 에피소드의 가상 모니터 MJPEG + 판독·판단·grounding 상태.

  python -m reader.board_v2 results/loop_v2/vlm_XXXX --port 8765   → http://127.0.0.1:8765 (SSH 터널)
"""
from __future__ import annotations

import json, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FAULTS = ["normal", "temp", "purge", "pulse", "press", "flow"]
PAGE = (Path(__file__).parent / "board_v2_page.html").read_text(encoding="utf-8")


class Grab:
    """디스플레이 하나를 ffmpeg 로 계속 떠서 마지막 JPEG 를 들고 있다."""

    def __init__(self, display):
        self.frame, self.cond = b"", threading.Condition()
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "quiet", "-f", "x11grab", "-draw_mouse", "0", "-framerate", "3",
                                   "-video_size", "1920x1080", "-i", f"{display}.0", "-vf", "scale=960:540", "-q:v", "7",
                                   "-f", "mjpeg", "-"], stdout=subprocess.PIPE)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        buf = b""
        while True:
            c = self.p.stdout.read(65536)
            if not c: break
            buf += c
            while True:
                a = buf.find(b"\xff\xd8"); z = buf.find(b"\xff\xd9", a + 2)
                if a < 0 or z < 0: break
                with self.cond: self.frame = buf[a:z + 2]; self.cond.notify_all()
                buf = buf[z + 2:]


def main():
    D = Path(sys.argv[1]); port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
    grabs: dict[str, Grab] = {}

    def grab(f):
        dfile = D / f / "display"
        if f not in grabs and dfile.exists(): grabs[f] = Grab(dfile.read_text().strip())
        return grabs.get(f)

    def state():
        fs = [f for f in FAULTS if (D / f).is_dir()]
        out = {"faults": fs, "B": {}}
        for f in fs:
            ep = D / f; rows = []
            try: rows = [json.loads(l) for l in (ep / "steps.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception: pass
            clicks = [r["click"] for r in rows if r.get("click")]
            errs_g = [abs(r["read_g"] - r["line_g"]) for r in rows if r["read_g"] is not None]
            errs_u = [abs(r["read_u"] - r["line_u"]) for r in rows if r["read_u"] is not None]
            summ = json.loads((ep / "summary.json").read_text()) if (ep / "summary.json").exists() else None
            out["B"][f] = {"n": len(rows), "last": rows[-1] if rows else None, "clicks": clicks, "summary": summ,
                           "live": (ep / "display").exists(), "mae_g": sum(errs_g) / len(errs_g) if errs_g else None,
                           "mae_u": sum(errs_u) / len(errs_u) if errs_u else None,
                           "fails": sum(1 for r in rows if r["read_g"] is None or r["read_u"] is None),
                           "series": [[r["since"], r["read_g"], r["line_g"], r["read_u"], r["line_u"]] for r in rows[::3]]}
        return out

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            if self.path.startswith("/c/"):            # 클릭 순간 캡처 (빨강 = VLM 이 찍은 곳, 초록 = 눌러야 할 버튼)
                parts = self.path.split("?")[0].split("/")
                fp = D / parts[2] / "clicks" / parts[3]
                if parts[3].endswith(".jpg") and fp.is_file():
                    jpg = fp.read_bytes(); self.send_response(200); self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(jpg))); self.end_headers(); self.wfile.write(jpg); return
                self.send_error(404); return
            if self.path.startswith("/s/"):            # 마지막 프레임 한 장 — 브라우저 연결 수(호스트당 6개)를 붙잡지 않는다
                name = self.path.split("/")[2].split(".")[0]
                fp = D / name / "frame.jpg"
                if fp.exists(): jpg = fp.read_bytes()
                else: g = grab(name); jpg = g.frame if g else b""
                if not jpg: self.send_error(404); return
                self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(jpg))); self.end_headers(); self.wfile.write(jpg); return
            if self.path.startswith("/v/"):
                g = grab(self.path.split("/")[2].split(".")[0])
                if not g: self.send_error(404); return
                self.send_response(200); self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
                self.send_header("Cache-Control", "no-store"); self.end_headers()
                try:
                    while True:
                        with g.cond: g.cond.wait(timeout=3); jpg = g.frame
                        if jpg:
                            self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode()
                                             + b"\r\n\r\n" + jpg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
            (D / "viewer_seen").touch()
            if self.path.startswith("/state.json"):
                body, ct = json.dumps(state(), ensure_ascii=False).encode(), "application/json"
            else:
                body, ct = PAGE.encode(), "text/html; charset=utf-8"
            self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

    print(f"보드: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()
