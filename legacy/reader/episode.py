#!/usr/bin/env python3
"""이상 하나를 주입한 에피소드 — 값 → 시계열 저장 → 함수 판단 → 버튼 → 결과.

판단 함수는 ald-vlm-agent 의 것을 그대로 부른다(probe/detector.py + agent/runner.py 의 Agent).
값을 어디서 가져오느냐만 바꾼다:
  raw  : 시뮬레이터 순간값(gpc_display) — 함수를 튜닝한 원래 입력 (참고용)
  line : 그래프에 그려진 선의 오른쪽 끝 — 화면에 보이는 값의 정답 (A)
  vlm  : VLM 이 화면에서 읽은 선 끝 + 노브 (B)
raw/line 은 노브도 시뮬레이터 내부값, vlm 은 노브도 화면에서 읽는다.

  python -m reader.episode --fault step --mode line --out results/x/step_line
"""
from __future__ import annotations

import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT.parent / "ald-vlm-agent"
sys.path[:0] = [str(ROOT), str(AGENT), str(AGENT / "probe")]
from agent.runner import Agent, GPC_BAND, PRIMARY          # 검증 대상 함수
from reader.screen import COORDS, HMI, TRUTH_JS, SimScreen

EXPECT = {**PRIMARY, "normal": "noop", "spike": "noop", "frozen": "request_clean", "diverge": "request_clean"}
STEP_JS = "(() => { const s = window.aldSim(); for (let i = 0; i < 2; i++) s.tick(); render(); })()"


def run(page, fault, mode, pre, post, out: Path, sense=None, log=print):
    ag = Agent(); rows = []; f = open(out / "steps.jsonl", "w", encoding="utf-8")
    last_knobs = None
    for i in range(pre + post):
        tr = page.evaluate(TRUTH_JS); g = page.evaluate("window.aldSim().gt()")
        t_s = g["t"] * 0.5; since = (g["t"] - g["inject_tick"]) * 0.5
        rd = None
        if mode == "raw": value, knobs = g["gpc_display"], g["knobs"]
        elif mode == "line": value, knobs = tr["line"][-1], g["knobs"]
        else:
            rd = sense()
            value = rd["gpc"]; knobs = rd["knobs"] or last_knobs or g["knobs"]
            last_knobs = knobs
        if value is not None: ag.observe(t_s, value)
        act, why, det = ag.decide(t_s, knobs) if ag.vs else ("noop", "이력 없음", {"shape": "normal"})
        hit = None
        if act != "noop":
            b = COORDS["buttons"][act]
            before = page.evaluate("window.aldSim().actionLog.length")
            page.mouse.click(b["x"], b["y"])
            log_ = page.evaluate("window.aldSim().actionLog")
            hit = log_[-1]["id"] if len(log_) > before else None
            ag.note_press(t_s, act, value)
        r = {"i": i, "since_inject_s": since, "value": value, "line_end": tr["line"][-1], "gpc_display": g["gpc_display"],
             "gpc_true": g["gpc_true"], "knobs_used": knobs, "knobs_true": g["knobs"], "det_shape": det["shape"],
             "agent_shape": ag.shape, "action": act, "hit": hit, "why": why, "correct_action": g["correct_action"],
             "in_band": GPC_BAND[0] <= g["gpc_true"] <= GPC_BAND[1],
             "read_raw": rd["raw"] if rd else None, "latency_s": rd["latency_s"] if rd else None}
        rows.append(r); f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
        if act != "noop": log(f"  [{fault}/{mode}] +{since:.0f}s {act} ({why[:60]})")
        page.evaluate(STEP_JS)
    f.close()
    s = summarize(fault, mode, rows)
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
    return s


def summarize(fault, mode, rows):
    post = [r for r in rows if r["since_inject_s"] >= 0]
    pre = [r for r in rows if r["since_inject_s"] < 0]
    presses = [r for r in rows if r["action"] != "noop"]
    first = next((r for r in post if r["action"] != "noop"), None)
    shape = next((r["agent_shape"] for r in reversed(rows) if r["agent_shape"]), None)
    back = next((r["since_inject_s"] for r in post if r["in_band"] and r["since_inject_s"] > 60), None)
    exp = EXPECT[fault]
    return {"fault": fault, "mode": mode, "expected_action": exp, "shape": shape, "shape_ok": shape == fault if fault not in ("normal", "spike") else shape in (None, "normal", "spike"),
            "false_pre": sum(1 for r in pre if r["action"] != "noop"),
            "first_action": first["action"] if first else "noop", "first_at": first["since_inject_s"] if first else None,
            "first_ok": (first["action"] if first else "noop") == exp,
            "presses": [[r["since_inject_s"], r["action"]] for r in presses],
            "match_pct": round(100 * sum(r["action"] == r["correct_action"] for r in post) / max(1, len(post)), 1),
            "end_gpc": rows[-1]["gpc_true"], "end_in_band": rows[-1]["in_band"], "back_s": back}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fault", required=True); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mode", choices=["raw", "line", "vlm"], required=True)
    ap.add_argument("--pre", type=int, default=200, help="주입 전 시뮬레이터 초 (함수는 180초 이력이 있어야 판단)")
    ap.add_argument("--post", type=int, default=300, help="주입 후 시뮬레이터 초")
    ap.add_argument("--model", default="qwen/qwen3.5-27b"); ap.add_argument("--key-file", default="~/.qwen27b_key")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    inject = 1800
    q = f"ui=clean&labels=both&fault={a.fault}&seed={a.seed}&inject={inject}&adv={120 - a.pre * 2}&paused=1"   # 페이지는 inject-120+adv 까지 미리 돈다 → 주입 pre 초 전에서 시작
    if a.mode == "vlm":                       # 화면이 필요하다: 가상 모니터 + kiosk (중계 가능)
        from reader.vlm import CLIP, SeriesReader
        from reader import sensor
        R = SeriesReader("https://openrouter.ai/api/v1", a.model, a.key_file)
        with SimScreen(q) as scr:
            scr.page.evaluate("paused = true")
            (out / "display").write_text(scr.display)
            def sense():
                g = scr.page.screenshot(clip=CLIP); k = scr.page.screenshot(clip=sensor.KNOB_CLIP)
                return sensor.read(R.cli, R.model, R.extra, g, k)
            s = run(scr.page, a.fault, a.mode, a.pre, a.post, out, sense)
        (out / "display").unlink(missing_ok=True)
    else:                                     # 정답 입력은 화면이 필요 없다: 헤드리스로 빠르게
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            pg.goto(f"file://{HMI}/index.html?{q}"); pg.wait_for_function("window.aldSim && window.aldSim().t > 0")
            pg.evaluate("paused = true")
            s = run(pg, a.fault, a.mode, a.pre, a.post, out)
            br.close()
    print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
