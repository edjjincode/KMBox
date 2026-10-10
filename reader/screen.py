"""시뮬레이터 화면 — Xvfb 가상 모니터 위에 kiosk 크롬으로 sim/index.html 을 띄우고 CDP 로 붙는다.

Playwright 로 launch 하면 탭바·툴바가 남아 화면 좌표와 페이지 좌표가 어긋난다. 그래서 크롬을 직접 띄운다.
시뮬레이터는 브라우저 안에서 실시간으로 돈다(1 tick = 0.5초). 캡처 순간만 잠깐 멈춰 화면과 정답을 맞춘다.
"""
from __future__ import annotations

import json, os, shutil, socket, subprocess, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = ROOT / "sim"                                # 시뮬레이터 화면(index.html)과 좌표표(coords.js)
W, H = 1920, 1080
CHROME = Path.home() / ".cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
_body = (SIM_DIR / "coords.js").read_text(encoding="utf-8").split("const COORDS =", 1)[1]
COORDS = json.loads(_body[_body.index("{"):_body.rindex("}") + 1])

# 정답: 카드 숫자 + 그래프에 실제로 그려진 선(5초 버킷 평균 → 15초 이동평균, index.html drawChart 와 같은 계산)
TRUTH_JS = """(() => {
  const s = window.aldSim(), v = s.view(), g = s.gt();
  const raw = v.gpcPoints.map(p => p.v), h = 1;
  const line = raw.map((_, i) => { const a = Math.max(0, i - h), b = Math.min(raw.length, i + h + 1);
    let t = 0; for (let j = a; j < b; j++) t += raw[j]; return t / (b - a); });
  return { t: s.t, card: +v.gpc.toFixed(3), gpc_display: g.gpc_display, gpc_true: g.gpc_true,
           line: line, fault: g.fault_type, inject_tick: g.inject_tick };
})()"""


def _free_display() -> str:
    for n in range(90, 130):
        if not Path(f"/tmp/.X11-unix/X{n}").exists():
            return f":{n}"
    raise RuntimeError("빈 디스플레이 번호가 없다")


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class SimScreen:
    """with SimScreen(query) as scr: png, truth = scr.capture()"""

    def __init__(self, query: str, speed: int = 1, html: Path | None = None):
        self.url = f"file://{html or SIM_DIR / 'index.html'}?{query}"
        self.speed = speed                     # 0.5초마다 tick 몇 번. 1 = 실시간
        self.display = None
        self._xvfb = self._chrome = self._pw = self._profile = self.browser = self.page = None

    def __enter__(self):
        port = _free_port()
        # 동시에 여러 개를 띄우면 '첫 빈 번호' 를 같이 집는다 → Xvfb 가 직접 고르고 번호를 파이프로 알려 준다
        r, w = os.pipe()
        self._xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(w), "-screen", "0", f"{W}x{H}x24", "-nolisten", "tcp"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(w,))
        os.close(w)
        with os.fdopen(r) as fr: self.display = ":" + fr.readline().strip()
        time.sleep(0.2)
        self._profile = tempfile.mkdtemp(prefix="series-reader-")
        self._chrome = subprocess.Popen(
            [str(CHROME), "--kiosk", f"--window-size={W},{H}", "--window-position=0,0",
             "--force-device-scale-factor=1", f"--user-data-dir={self._profile}", f"--remote-debugging-port={port}",
             "--no-first-run", "--no-default-browser-check", "--disable-infobars", "--noerrdialogs",
             "--disable-session-crashed-bubble", "--hide-scrollbars", "--disable-features=Translate,TranslateUI",
             "--lang=ko", "--test-type", self.url],
            env={**os.environ, "DISPLAY": self.display}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        for _ in range(80):
            try:
                self.browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}"); break
            except Exception:
                time.sleep(0.25)
        if self.browser is None:
            self.__exit__(); raise RuntimeError("CDP 연결 실패")
        self.page = self.browser.contexts[0].pages[0]
        self.page.wait_for_function("window.aldSim && window.aldSim().t > 0")
        self.page.evaluate(f"speed = {int(self.speed)}; paused = false")
        return self

    def load(self, fault: str, seed: int, adv: int, inject: int = 1700):
        """새 데이터셋으로 갈아 끼운다. 창(10분)이 꽉 차도록 미리 돌리고, adv 는 주입 기준 위치(tick)."""
        warm = max(1200, inject - 120 + adv)
        self.page.evaluate(f"""(() => {{ sim = new SIM.Sim({{seed: {seed}, faultType: "{fault}", injectTick: {inject}}});
            for (let i = 0; i < {warm}; i++) sim.tick(); render(); }})()""")

    def capture(self, clip: dict | None = None):
        """시뮬레이터를 잠깐 멈추고 화면과 정답을 같은 순간으로 뜬다."""
        self.page.evaluate("paused = true; render()")
        try:
            png = self.page.screenshot(clip=clip) if clip else self.page.screenshot()
            truth = self.page.evaluate(TRUTH_JS)
        finally:
            self.page.evaluate("paused = false")
        return png, truth

    def __exit__(self, *exc):
        for f in (lambda: self.browser and self.browser.close(), lambda: self._pw and self._pw.stop()):
            try: f()
            except Exception: pass
        for p in (self._chrome, self._xvfb):
            if p: p.terminate()
        if self._profile: shutil.rmtree(self._profile, ignore_errors=True)
