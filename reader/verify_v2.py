#!/usr/bin/env python3
"""이상 감지 함수(detect_v2) 검증 — 시뮬레이터 v2, 정답 입력(화면 그래프에 그려진 선).

  1) parity     : Python detect_v2 와 JS agent_v2.detect 가 같은 입력에 같은 답을 내는가
  2) 판정        : 이상 6종 × 시드 30 × 주입 후 15~300초(15초 간격) — 감지 시간, 혼동 행렬
  3) 오경보      : 정상 30분 × 시드 30, 5초마다 판정
  4) 폐루프      : 함수가 직접 버튼을 누름 — 복귀, 유지, 잘못 누른 횟수 (시드 20)

  python -m reader.verify_v2   → results/verify_v2.json + 표 출력
"""
import json, statistics as st, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from reader.detect_v2 import detect

FAULTS = ["normal", "temp", "purge", "pulse", "press", "flow"]
FIX = {"temp": "temp_up", "purge": "purge_up", "pulse": "pulse_up", "press": "press_down", "flow": "flow_up"}
LINE = """(([f, sd, ticks]) => { const s = new SIM.Sim({seed: sd, faultType: f, injectTick: 1200});
  const out = []; let next = 1200 + 30;
  for (let i = 0; i < ticks; i++) { s.tick();
    if (s.t === next) { const v = s.view(), g = v.gpcPoints.map(p => p.v), u = v.uPoints.map(p => p.v);
      out.push({ since: (s.t - 1200) * 0.5, g: g, u: u, ca: s.gt().correct_action, js: AGENT.detect(g, u, 5) }); next += 30; } }
  return out; })"""
LOOP = """(([f, sd, postS, UNDO]) => { const s = new SIM.Sim({seed: sd, faultType: f, injectTick: 1200}); const ag = new AGENT.Agent({undo: UNDO});
  for (let i = 0; i < 1200 - 240; i++) s.tick();                    // 창을 채우고 주입 2분 전부터 에이전트 시작
  const rows = [];
  while ((s.t - 1200) * 0.5 < postS) { s.tick(); s.tick(); const since = (s.t - 1200) * 0.5;
    const r = ag.step(s, since, id => s.apply(id)); const g = s.gt();
    rows.push([since, g.gpc_true, g.uniformity_true, r.act, r.d.cause]); }
  return { presses: ag.presses, rows: rows, knobs: s.knobs }; })"""


def ser(t): return [600.0 - (len(t) - 1 - i) * 5.0 for i in range(len(t))]


UNDO = "--undo" in sys.argv


def main():
    from playwright.sync_api import sync_playwright
    R = {}
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        pg.goto("file://" + str(ROOT / "sim/index.html") + "?ui=clean&paused=1"); pg.wait_for_function("window.SIM")
        pg.add_script_tag(path=str(ROOT / "sim/agent_v2.js"))

        # 1·2) 판정 + parity
        samples = []
        for f in FAULTS:
            for sd in range(1, 31):
                for x in pg.evaluate(LINE, [f, sd, 1200 + 600]):
                    py = detect(ser(x["g"]), x["g"], x["u"], 600.0)
                    samples.append({"fault": f, "seed": sd, "since": x["since"], "ca": x["ca"], "py": py["cause"], "js": x["js"]["cause"]})
        mism = [s for s in samples if s["py"] != s["js"]]
        print(f"[1] parity: Python ↔ JS {len(samples) - len(mism)}/{len(samples)} 일치")
        R["parity"] = {"n": len(samples), "mismatch": len(mism)}

        print("\n[2] 원인 맞힘률 (시드 30, 정답이 '조치 필요'인 경우만) — 주입 후 시각별")
        times = sorted({s["since"] for s in samples})
        print(f"{'':7s}" + "".join(f"{int(t):>5d}" for t in times))
        conf = defaultdict(Counter); latency = {}
        for f in FAULTS:
            row = []
            for t in times:
                ss = [s for s in samples if s["fault"] == f and s["since"] == t]
                need = [s for s in ss if s["ca"] != "noop"] if f != "normal" else ss
                if not need: row.append("    ·"); continue
                ok = sum(s["py"] == f for s in need); row.append(f"{100 * ok // len(need):>4d}%")
                for s in need: conf[f][s["py"]] += 1
            print(f"{f:7s}" + "".join(f"{c:>5s}" for c in row))
            if f != "normal":                                  # 감지 시간: 이후로 계속 맞히기 시작한 첫 시각
                lat = []
                for sd in range(1, 31):
                    seq = sorted((s["since"], s["py"] == f) for s in samples if s["fault"] == f and s["seed"] == sd)
                    first = next((t for i, (t, _) in enumerate(seq) if all(ok for _, ok in seq[i:])), None)
                    lat.append(first)
                got = [x for x in lat if x is not None]
                latency[f] = {"median_s": st.median(got) if got else None, "max_s": max(got) if got else None, "never": len(lat) - len(got)}
        print("\n    혼동 행렬 (행 = 넣은 이상, 열 = 함수 판정, '조치 필요' 시점 전부)")
        print(f"{'':8s}" + "".join(f"{c:>8s}" for c in FAULTS))
        for f in FAULTS: print(f"{f:8s}" + "".join(f"{conf[f][c]:>8d}" for c in FAULTS))
        print("\n    감지 시간 (이후로 계속 맞히기 시작한 시각, 시드 30)")
        for f, v in latency.items(): print(f"    {f:6s} 중앙값 +{v['median_s']:.0f}초 · 최대 +{v['max_s']:.0f}초 · 끝까지 못 잡음 {v['never']}")
        R["confusion"] = {f: dict(c) for f, c in conf.items()}; R["latency"] = latency

        # 3) 정상 장시간 오경보
        fa = pg.evaluate("""(() => { let n = 0, bad = 0, ex = [];
          for (let sd = 1; sd <= 30; sd++) { const s = new SIM.Sim({seed: sd, faultType: "normal", injectTick: 1e9});
            for (let i = 0; i < 1200 + 3600; i++) { s.tick();
              if (s.t > 1200 && s.t % 10 === 0) { const v = s.view(), d = AGENT.detect(v.gpcPoints.map(p => p.v), v.uPoints.map(p => p.v), 5);
                n++; if (d.cause !== "normal") { bad++; if (ex.length < 5) ex.push(sd + ":" + d.why); } } } }
          return { n, bad, ex }; })()""")
        print(f"\n[3] 정상 30분 × 시드 30, 5초마다 판정 {fa['n']}회 중 오경보 {fa['bad']}회 {fa['ex']}")
        R["false_alarm"] = fa

        # 4) 폐루프
        print(f"\n[4] 폐루프 — 함수가 직접 누름 (주입 2분 전 ~ 주입 후 10분, 시드 20, 되돌리기 {'켬' if UNDO else '끔'})")
        print(f"    {'이상':6s} {'첫 조치':>8s} {'맞는 버튼':>9s} {'잘못 누름':>8s} {'되돌림':>6s} {'클리닝':>6s} {'끝 대역 안':>9s} {'+3분 뒤 대역 안 비율':>16s}")
        loop = {}
        for f in FAULTS:
            res = []
            for sd in range(1, 21):
                r = pg.evaluate(LOOP, [f, sd, 600, UNDO])
                pr = r["presses"]; post = [x for x in pr if x["t"] >= 0]
                good = [x for x in pr if f != "normal" and x["act"] == FIX[f]]
                wrong = [x for x in pr if x["act"] not in (FIX.get(f), "request_clean") and x["cause"] != "되돌림"]
                undo = [x for x in pr if x["cause"] == "되돌림"]
                rows = r["rows"]; late = [x for x in rows if x[0] >= 180]
                inb = [1.05 <= x[1] <= 1.15 and x[2] <= 1.30 for x in late]
                res.append({"first": post[0]["t"] if post else None, "good": len(good), "wrong": len(wrong),
                            "clean": sum(x["act"] == "request_clean" for x in pr), "undo": len(undo), "end_ok": inb[-1], "frac": sum(inb) / len(inb),
                            "presses": pr})
            firsts = [x["first"] for x in res if x["first"] is not None]
            loop[f] = res
            print(f"    {f:6s} {('+%.0f초' % st.median(firsts)) if firsts else '없음':>8s} {st.mean(x['good'] for x in res):>9.1f} "
                  f"{sum(x['wrong'] for x in res):>8d} {sum(x['undo'] for x in res):>6d} {sum(x['clean'] for x in res):>6d} {sum(x['end_ok'] for x in res):>6d}/20 "
                  f"{100 * st.mean(x['frac'] for x in res):>14.0f}%")
            bad = [x for x in res if x["wrong"]][:2]
            for x in bad: print(f"           잘못 누른 예: {[(round(p['t']), p['act'], p['cause']) for p in x['presses']]}")
        R["loop"] = {f: [{k: v for k, v in x.items() if k != "presses"} | {"presses": x["presses"]} for x in res] for f, res in loop.items()}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/verify_v2.json").write_text(json.dumps(R, ensure_ascii=False))


if __name__ == "__main__":
    main()
