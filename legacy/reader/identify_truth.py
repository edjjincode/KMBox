#!/usr/bin/env python3
"""이상을 미리 주입한 화면 한 장 → 그래프 선을 N 점으로 뽑아 → 함수 판정. VLM 없이 '함수가 몇 점이면 맞히나' 를 본다."""
import json, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; AGENT = ROOT.parent / "ald-vlm-agent"
sys.path[:0] = [str(ROOT), str(AGENT / "probe")]
import detector as D
from reader.screen import HMI, TRUTH_JS

FAULTS = ["normal", "ramp", "step", "knee", "oscil", "spike", "frozen", "diverge"]
SINCE = [30, 60, 120, 240]; SEEDS = [1, 2, 3, 4, 5]; NS = [11, 21, 31, 61, 120]

def sample(line, n):
    return [line[round(i * (len(line) - 1) / (n - 1))] for i in range(n)]

def main():
    from playwright.sync_api import sync_playwright
    res = []
    with sync_playwright() as pw:
        pg = pw.chromium.launch().new_page(viewport={"width": 1920, "height": 1080})
        pg.goto(f"file://{HMI}/index.html?ui=clean&paused=1"); pg.wait_for_function("window.aldSim")
        for f in FAULTS:
            for since in SINCE:
                for sd in SEEDS:
                    pg.evaluate(f"""(() => {{ sim = new SIM.Sim({{seed: {sd}, faultType: "{f}", injectTick: 1800}});
                        for (let i = 0; i < 1800 + {since * 2}; i++) sim.tick(); render(); }})()""")
                    tr = pg.evaluate(TRUTH_JS); ca = pg.evaluate("window.aldSim().gt().correct_action")
                    for n in NS:
                        vs = sample(tr["line"], n); ts = [i * 600 / (n - 1) for i in range(n)]
                        d = D.detect(ts, vs, ts, vs)
                        res.append({"fault": f, "since": since, "seed": sd, "n": n, "shape": d["shape"],
                                    "action": d["action"], "correct_action": ca})
    json.dump(res, open(ROOT / "results/identify_truth.json", "w"), ensure_ascii=False)
    acc = defaultdict(lambda: [0, 0])
    for r in res:
        a = acc[(r["fault"], r["n"])]; a[0] += r["action"] == r["correct_action"]; a[1] += 1
    print("행동 일치 (정답 선을 N 점으로 뽑아 함수에 넣음, 주입 후 30/60/120/240초 × 시드 5)")
    print(f"{'':8s}" + "".join(f"{'N=' + str(n):>9s}" for n in NS))
    for f in FAULTS: print(f"{f:8s}" + "".join(f"{acc[(f, n)][0]:>6d}/{acc[(f, n)][1]:<2d}" for n in NS))
    tot = {n: sum(acc[(f, n)][0] for f in FAULTS) for n in NS}
    print(f"{'전체':7s}" + "".join(f"{tot[n]:>6d}/160" for n in NS))

if __name__ == "__main__": main()
