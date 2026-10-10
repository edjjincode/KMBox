#!/usr/bin/env python3
"""판단 검증 보드 — 이상 8종 에피소드를 한 화면에. 각 가상 모니터 MJPEG + 판단 상태 + A(정답 입력) 결과표.

  python -m reader.board results/judge_XXXX --port 8765     → http://127.0.0.1:8765 (SSH 터널)
"""
from __future__ import annotations

import json, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FAULTS = ["normal", "ramp", "step", "knee", "oscil", "spike", "frozen", "diverge"]
PAGE = (Path(__file__).parent / "board_page.html").read_text(encoding="utf-8")


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
        dfile = D / f"{f}_vlm" / "display"
        if f not in grabs and dfile.exists(): grabs[f] = Grab(dfile.read_text().strip())
        return grabs.get(f)

    def tail(p: Path, n=1):
        try: lines = p.read_text(encoding="utf-8").splitlines()
        except Exception: return [], 0
        return [json.loads(l) for l in lines[-n:] if l.strip()], len(lines)

    def state():
        out = {"faults": FAULTS, "A": {}, "B": {}}
        for f in FAULTS:
            for m in ("line", "raw"):
                p = D / f"{f}_{m}" / "summary.json"
                if p.exists(): out["A"].setdefault(f, {})[m] = json.loads(p.read_text())
            ep = D / f"{f}_vlm"
            last, n = tail(ep / "steps.jsonl", 1)
            presses = []
            try:
                for l in (ep / "steps.jsonl").read_text(encoding="utf-8").splitlines():
                    r = json.loads(l)
                    if r["action"] != "noop": presses.append([r["since_inject_s"], r["action"], r["hit"]])
            except Exception: pass
            summ = json.loads((ep / "summary.json").read_text()) if (ep / "summary.json").exists() else None
            out["B"][f] = {"n": n, "last": last[0] if last else None, "presses": presses, "summary": summ,
                           "live": (ep / "display").exists()}
        return out

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
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
            (D / "viewer_seen").touch()              # 누가 보드를 열었다 → 실행 스크립트가 시작한다
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
