#!/usr/bin/env python3
"""v2 시뮬레이터에서 이상 감지 함수 채점. 입력 두 가지:
  raw  : 시뮬레이터가 매 tick 내는 값(2 Hz)
  line : 화면 그래프에 그려진 선(5초 평균 120점) — VLM 이 읽을 수 있는 것
정답 = 시뮬레이터 correct_action (교란 영향이 화면에 보일 만큼일 때만 조치, 아니면 noop)
"""
import json, os, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from reader.detect_v2 import detect, ACTION

FAULTS = ["normal", "temp", "purge", "pulse", "press", "flow"]; SINCE = [30, 60, 120, 180, 300]; SEEDS = range(1, 11)
JS = """(([f, sd, since]) => { const s = new SIM.Sim({seed: sd, faultType: f, injectTick: 1200});
  for (let i = 0; i < 1200 + since * 2; i++) s.tick();
  const W = 1200, a = s.gpcSeries.length - W, v = s.view();
  return { g: s.gpcSeries.slice(a), u: s.uSeries.slice(a), lg: v.gpcPoints.map(p => p.v), lu: v.uPoints.map(p => p.v),
           ca: s.gt().correct_action }; })"""

def main():
    from playwright.sync_api import sync_playwright
    rows = []
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        pg.goto("file://" + str(ROOT / "sim/index.html") + "?ui=clean&paused=1"); pg.wait_for_function("window.SIM")
        for f in FAULTS:
            for since in SINCE:
                for sd in SEEDS:
                    d = pg.evaluate(JS, [f, sd, since])
                    t_now = 600.0
                    for mode, g, u, dt in (("raw", d["g"], d["u"], 0.5), ("line", d["lg"], d["lu"], 5.0)):
                        ts = [t_now - (len(g) - 1 - i) * dt for i in range(len(g))]
                        r = detect(ts, g, u, t_now)
                        rows.append({"fault": f, "since": since, "seed": sd, "mode": mode, "cause": r["cause"],
                                     "action": r["action"], "correct": d["ca"], "why": r["why"], "feat": r["feat"]})
    (ROOT / "results").mkdir(exist_ok=True)
    json.dump(rows, open(ROOT / "results/eval_v2.json", "w"), ensure_ascii=False)
    for mode in ("raw", "line"):
        print(f"\n[{mode}] 조치 정답 (시드 10개) — 정답이 noop 인 칸은 '아직 화면에 안 보이는 시점'")
        print(f"{'':7s}" + "".join(f"{'+' + str(s) + 's':>9s}" for s in SINCE) + "   원인 맞힘(조치가 필요한 칸만)")
        for f in FAULTS:
            cells, hit, need = [], 0, 0
            for s in SINCE:
                rr = [r for r in rows if r["mode"] == mode and r["fault"] == f and r["since"] == s]
                ok = sum(r["action"] == r["correct"] for r in rr)
                cells.append(f"{ok:>3d}/{len(rr):<2d}" + ("*" if all(r["correct"] == "noop" for r in rr) and f != "normal" else " "))
                for r in rr:
                    if r["correct"] != "noop": need += 1; hit += r["cause"] == f
            print(f"{f:7s}" + "".join(f"{c:>9s}" for c in cells) + (f"   {hit}/{need}" if need else ""))

if __name__ == "__main__": main()
