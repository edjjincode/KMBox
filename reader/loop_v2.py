#!/usr/bin/env python3
"""v2 폐루프 에피소드 하나 — 화면 판독 → 시계열 저장 → 감지 함수 → 버튼 grounding → 클릭.

  mode truth : 그래프 선 정답값 + coords.js 좌표 (VLM 없음, 헤드리스) — 에이전트 점검용
  mode read  : VLM 이 값을 읽고(--read-model) 함수가 판단, 조치는 coords.js 좌표로 제출 (버튼 grounding 제외)
  mode vlm   : VLM 이 두 그래프 '현재' 값을 읽고(--read-model), 버튼 위치도 VLM 이 찍는다(--ground-model).
               가상 모니터(Xvfb) + kiosk 크롬이라 중계 가능, 클릭은 실제 마우스 이벤트

  python -m reader.loop_v2 --fault purge --mode vlm --out results/loop_v2/x/purge
"""
from __future__ import annotations

import argparse, io, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from reader.agent_v2 import Agent
from reader.screen import COORDS, SimScreen
from reader.vlm_v2 import GPC_CLIP, U_CLIP, TRUTH_JS

FIX = {"temp": "temp_up", "purge": "purge_up", "pulse": "pulse_up", "press": "press_down", "flow": "flow_up"}
KNOB_CLIP = {"x": 40, "y": 796, "width": 1840, "height": 112}
KNOB_PROMPT = ("이 그림은 공정 노브 줄이다. 온도, 압력, 펄스 Pulse, 퍼지 Purge, 유량 칸 왼쪽 위 이름 옆에 '설정 ○○' 이라고 적힌 설정값을 읽어라 (크게 적힌 실제값이 아니다).\n"
               '{"temp": <숫자>, "press": <숫자>, "pulse": <숫자>, "purge": <숫자>, "flow": <숫자>}')
STEP_JS = "(() => { for (let i = 0; i < 2; i++) sim.tick(); render(); })()"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fault", required=True); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mode", choices=["truth", "read", "vlm"], default="read")
    ap.add_argument("--pre", type=int, default=120, help="주입 전 초 (그래프 10분 창은 미리 채운다)")
    ap.add_argument("--no-dose", action="store_true", help="주입량 계산 없이 한 칸씩 (이전 방식)")
    ap.add_argument("--post", type=int, default=360, help="주입 후 초")
    ap.add_argument("--read-model", default="qwen/qwen3.5-27b"); ap.add_argument("--ground-model", default="qwen/qwen3-vl-235b-a22b-instruct")
    ap.add_argument("--ground-style", choices=["goal", "label"], default="goal", help="goal = 하려는 일 문장, label = 화면 라벨을 짚는 문장")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    inject = 1200 + a.pre * 2
    q = f"ui=clean&labels=both&fault={a.fault}&seed={a.seed}&inject={inject}&adv={1200 - inject + 120}&paused=1"   # 페이지는 inject-120+adv = 1200 tick 까지 미리 돈다
    (out / "meta.json").write_text(json.dumps({**vars(a), "started": time.strftime("%H:%M:%S")}, ensure_ascii=False))

    def run(page):
        page.evaluate("paused = true")
        if a.mode != "truth":
            from reader.vlm_v2 import VLM
            R = VLM(a.read_model)
            G = VLM(a.ground_model) if a.mode == "vlm" else None
        ag = Agent(use_dose=not a.no_dose); f = open(out / "steps.jsonl", "w", encoding="utf-8"); clicks = []
        for i in range(a.pre + a.post):
            tr = page.evaluate(TRUTH_JS); now = tr["since"]
            if a.mode == "truth":
                rd = {"gpc": tr["gpc_line"], "u": tr["u_line"], "raw": None, "latency_s": 0}
            else:
                rd = R.read(page.screenshot(clip=GPC_CLIP), page.screenshot(clip=U_CLIP))
            ag.observe(now, rd["gpc"], rd["u"])

            def knobs_fn():
                if a.mode == "truth": return tr["knobs"]
                raw, _ = R._ask("출력은 JSON 한 개뿐이다.", [page.screenshot(clip=KNOB_CLIP)], KNOB_PROMPT)
                import re
                kv = {k: float(m.group(1)) for k in ("temp", "press", "pulse", "purge", "flow")
                      if (m := re.search(rf'"{k}"\s*:\s*"?(-?\d+(?:\.\d+)?)', raw))}
                return kv

            def press(act, n=1):
                before = page.evaluate("sim.actionLog.length")
                if a.mode != "vlm":                                 # 함수가 고른 조치를 좌표표 위치로 제출
                    b = COORDS["buttons"][act]; xy, g = (b["x"], b["y"]), None
                else:
                    g = G.ground(page.screenshot(), act, style=a.ground_style); xy = g["xy"]
                for k in range(n if xy else 0):                     # 위치는 한 번만 찾고 같은 자리를 n번 누른다
                    page.mouse.click(*xy); page.wait_for_timeout(120)
                log = page.evaluate("sim.actionLog")
                hit = log[-1]["id"] if len(log) > before else None
                c = {"t": now, "intent": act, "n": n, "n_hit": sum(1 for x in log[before:] if x["id"] == act), "xy": xy, "hit": hit, "ok": hit == act, "goal": g and g["goal"], "img": f"{len(clicks) + 1:02d}.jpg" if a.mode == "vlm" else None,
                     "raw": g and g["raw"], "norm": g and g["norm"], "latency_s": g and g["latency_s"]}
                clicks.append(c)
                if a.mode == "vlm":
                    from PIL import Image, ImageDraw
                    im = Image.open(io.BytesIO(page.screenshot())).convert("RGB"); d = ImageDraw.Draw(im)
                    b = COORDS["buttons"][act]; d.rectangle((b["x"] - b["w"] / 2, b["y"] - b["h"] / 2, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2), outline=(30, 170, 90), width=5)
                    if xy: d.ellipse((xy[0] - 22, xy[1] - 22, xy[0] + 22, xy[1] + 22), outline=(220, 40, 40), width=5)
                    (out / "clicks").mkdir(exist_ok=True); im.crop((0, 760, 1920, 1080)).resize((1280, 213)).save(out / "clicks" / f"{len(clicks):02d}.jpg", quality=80)

            r = ag.step(now, knobs_fn, press)
            row = {"i": i, "since": now, "read_g": rd["gpc"], "read_u": rd["u"], "line_g": tr["gpc_line"], "line_u": tr["u_line"],
                   "knobs": tr["knobs"], "cause": r["d"]["cause"], "act": r["act"], "n": r.get("n", 1), "why": r["why"], "correct": tr["correct_action"],
                   "click": clicks[-1] if r["act"] != "noop" and clicks else None, "read_raw": rd["raw"], "latency_s": rd["latency_s"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
            if i % 2 == 0 and a.mode != "truth":              # 보드용 화면 (CDP 캡처라 가상 모니터와 상관없다)
                from PIL import Image
                Image.open(io.BytesIO(page.screenshot())).convert("RGB").save(out / "frame.tmp.jpg", quality=78)
                (out / "frame.tmp.jpg").replace(out / "frame.jpg")
            page.evaluate(STEP_JS)
        f.close()
        last = page.evaluate(TRUTH_JS)
        g_ok = 1.05 <= last["gpc_line"] <= 1.15 and last["u_line"] <= 1.30
        summ = {"fault": a.fault, "mode": a.mode, "presses": ag.presses, "clicks": clicks, "eval": ag.log,
                "click_ok": sum(c["ok"] for c in clicks), "click_n": len(clicks),
                "fix_presses": sum(1 for c in clicks if c["hit"] == FIX.get(a.fault)),
                "end": {"gpc": last["gpc_line"], "u": last["u_line"], "in_band": g_ok, "knobs": last["knobs"]}}
        (out / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))
        print(json.dumps({k: summ[k] for k in ("fault", "mode", "click_ok", "click_n", "fix_presses", "end")}, ensure_ascii=False))

    html = ROOT / "sim/index.html"
    if a.mode != "truth":
        with SimScreen(q, html=html) as scr:
            (out / "display").write_text(scr.display)
            try: run(scr.page)
            finally: (out / "display").unlink(missing_ok=True)
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            pg = p.chromium.launch().new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            pg.goto(f"file://{html}?{q}"); pg.wait_for_function("window.aldSim && window.aldSim().t > 0")
            run(pg)


if __name__ == "__main__":
    main()
