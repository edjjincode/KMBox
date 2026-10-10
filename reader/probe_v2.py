#!/usr/bin/env python3
"""v2 화면에서 VLM 두 능력을 따로 잰다 — ① 두 그래프 '현재' 값 판독 ② 버튼 11종 grounding (실제 클릭까지)."""
import json, statistics as st, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from reader.vlm_v2 import VLM, GPC_CLIP, U_CLIP, TRUTH_JS
from reader.screen import COORDS

CASES = [("normal", 0), ("temp", 240), ("purge", 120), ("pulse", 200), ("press", 160), ("flow", 150),
         ("purge", 30), ("pulse", 300), ("temp", 400), ("flow", 400)]          # (이상, 주입 후 초)
LOAD = """(([f, sd, since]) => { sim = new SIM.Sim({seed: sd, faultType: f, injectTick: 1200}); for (let i = 0; i < 1200 + since * 2; i++) sim.tick(); render(); })"""


def main():
    from playwright.sync_api import sync_playwright
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen/qwen3.5-27b"
    style = sys.argv[2] if len(sys.argv) > 2 else "label"
    only_ground = "--ground" in sys.argv
    v = VLM(model)
    shots = []
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        pg.goto("file://" + str(ROOT / "sim/index.html") + "?ui=clean&labels=both&paused=1"); pg.wait_for_function("window.aldSim")
        for i, (f, since) in enumerate(CASES):
            pg.evaluate(LOAD, [f, i + 1, since])
            shots.append({"case": f"{f}+{since}s", "g": pg.screenshot(clip=GPC_CLIP), "u": pg.screenshot(clip=U_CLIP),
                          "full": pg.screenshot(), "truth": pg.evaluate(TRUTH_JS)})
        # ① 판독
        reads = []
        if only_ground: pass
        else:
          with ThreadPoolExecutor(8) as ex: reads = list(ex.map(lambda s: v.read(s["g"], s["u"]), shots))
        eg, eu = [0], [0]
        if reads: print(f"① 두 그래프 '현재' 판독 ({model})"); eg, eu = [], []
        for s, r in zip(shots, reads):
            t = s["truth"]; dg = None if r["gpc"] is None else r["gpc"] - t["gpc_line"]; du = None if r["u"] is None else r["u"] - t["u_line"]
            if dg is not None: eg.append(abs(dg))
            if du is not None: eu.append(abs(du))
            print(f"   {s['case']:12s} GPC {r['gpc']} / 선 {t['gpc_line']:.3f} ({'실패' if dg is None else f'{dg:+.3f}'})   "
                  f"균일도 {r['u']} / 선 {t['u_line']:.3f} ({'실패' if du is None else f'{du:+.3f}'})   {r['latency_s']}s")
        if reads: print(f"   평균 오차 GPC {st.mean(eg):.4f} (최대 {max(eg):.3f}) · 균일도 {st.mean(eu):.4f} (최대 {max(eu):.3f}) · 실패 {2 * len(shots) - len(eg) - len(eu)}")
        # ② grounding: 화면 3장 × 버튼 11종, 실제로 클릭해서 무엇이 눌렸는지 확인
        if "--read" in sys.argv: return
        print(f"② 버튼 grounding [{model} · {style}] — 화면 3장 × 버튼 11종, 실제 클릭")
        jobs = [(si, a) for si in (0, 2, 4) for a in COORDS["buttons"]]
        with ThreadPoolExecutor(8) as ex: gs = list(ex.map(lambda j: v.ground(shots[j[0]]["full"], j[1], style=style), jobs))
        per = {}
        for (si, a), g in zip(jobs, gs):
            got = None
            if g["xy"]:
                got = pg.evaluate(f"sim.hitTest({g['xy'][0]}, {g['xy'][1]})")
            per.setdefault(a, []).append((got == a, got, g))
        tot = 0
        for a, lst in per.items():
            ok = sum(x[0] for x in lst); tot += ok
            miss = ", ".join(f"{x[1] or '허공'}@{x[2]['xy']}" for x in lst if not x[0])
            print(f"   {a:14s} {ok}/3  {('빗나감: ' + miss) if miss else ''}")
        print(f"   합계 {tot}/{len(jobs)} · 평균 지연 {st.mean(g['latency_s'] for g in gs):.2f}s")
        out = ROOT / f"results/probe_v2_{model.split('/')[-1]}_{style}.json"
        out.write_text(json.dumps({"reads": [{**{k: s[k] for k in ("case", "truth")}, **r} for s, r in zip(shots, reads)],
                                   "ground": [{"screen": si, "action": a, **g} for (si, a), g in zip(jobs, gs)]}, ensure_ascii=False))


if __name__ == "__main__": main()
