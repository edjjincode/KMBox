#!/usr/bin/env python3
"""시뮬레이터 데이터를 계속 바꿔 가며 VLM 이 GPC 그래프(선)에서 시계열 값을 읽는지 본다.

  1) 가상 모니터에 kiosk 크롬으로 ald-vlm-agent/hmi 시뮬레이터를 띄운다 (버튼은 누르지 않는다)
     --switch 초마다 시나리오·시드·주입 위치를 무작위로 바꾸고, 그 사이에도 시뮬레이터는 계속 돈다
  2) 매 판독마다 시뮬레이터를 잠깐 멈추고 그래프 상자만 캡처 + 정답(카드 숫자·그려진 선)을 함께 뜬다
  3) VLM 에게 그래프만 보내 −10분 … 현재 11곳의 값을 읽게 한다
  4) VLM '현재' ↔ 화면 숫자 카드, 11곳 ↔ 그려진 선 으로 채점하고 실시간 중계 화면에 겹쳐 그린다

  python -m reader.run --minutes 8 --wait-viewer
  python -m reader.run --scenarios step,ramp --switch 30
"""
from __future__ import annotations

import argparse, io, json, random, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reader.screen import SimScreen
from reader.vlm import CLIP, MINUTES, SeriesReader, to_screen, truth_at_minutes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="normal,ramp,step,knee,oscil,spike,frozen,diverge")
    ap.add_argument("--switch", type=float, default=20, help="몇 초마다 데이터셋을 바꿀지 (0 이면 안 바꿈)")
    ap.add_argument("--rng", type=int, default=0, help="데이터셋 순서 난수 시드 (재현용)")
    ap.add_argument("--minutes", type=float, default=6.0, help="실제 시간 기준 실행 길이")
    ap.add_argument("--speed", type=int, default=4, help="0.5초마다 tick 수. 1 = 실시간, 4 = 4배속(HMI 기본)")
    ap.add_argument("--base", default="https://openrouter.ai/api/v1")
    ap.add_argument("--model", default="qwen/qwen3.5-27b")
    ap.add_argument("--key-file", default="~/.qwen27b_key")
    ap.add_argument("--stream", type=int, default=8765, help="중계 포트(0 이면 끔)")
    ap.add_argument("--wait-viewer", action="store_true", help="중계 화면을 누가 열 때까지 시작을 기다린다")
    ap.add_argument("--keep", type=float, default=600, help="끝난 뒤 중계를 띄워 두는 초")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    scen = a.scenarios.split(","); rng = random.Random(a.rng)
    def pick():          # 주입 3분 전 ~ 9분 후 사이 어딘가. 시드도 매번 다르게
        return {"fault": rng.choice(scen), "seed": rng.randint(1, 9999), "adv": rng.randint(-360, 1080)}
    query = "ui=clean&labels=both&fault=normal&seed=1&inject=1700&adv=0"
    out = ROOT / (a.out or f"results/{time.strftime('%m%d_%H%M')}_mix_{a.model.split('/')[-1]}")
    (out / "crops").mkdir(parents=True, exist_ok=True)
    meta = {"model": a.model, "scenarios": scen, "switch_s": a.switch, "speed": a.speed, "rng": a.rng,
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))

    vlm = SeriesReader(a.base, a.model, a.key_file)
    rows, lock, done, ep = [], threading.Lock(), [False], [None]

    def state():
        with lock:
            ok = [r for r in rows if r["series_vlm"]]
            mean = lambda xs: sum(xs) / len(xs) if xs else None
            by = {}
            for r in ok: by.setdefault(r["fault"], []).append(r)
            per = {f: {"n": len(v), "now_vs_line": mean([abs(r["err_line"]) for r in v]),
                       "series": mean([r["series_mae"] for r in v if r["series_mae"] is not None])} for f, v in by.items()}
            return {"meta": meta, "n": len(rows), "done": done[0], "last": rows[-1] if rows else None,
                    "episode": ep[0], "per_scenario": per,
                    "recent": [{k: r[k] for k in ("k", "fault", "since_inject_s", "series_vlm", "series_truth", "series_mae")} for r in rows[-8:]],
                    "hist": [{k: r[k] for k in ("wall_s", "card", "line_end", "vlm_now", "episode")} for r in rows],
                    "summary": {"reads": len(rows), "fails": len(rows) - len(ok),
                                "mae_card": mean([abs(r["err_card"]) for r in ok]),
                                "mae_line": mean([abs(r["err_line"]) for r in ok]),
                                "mae_series": mean([r["series_mae"] for r in ok if r["series_mae"] is not None]),
                                "lat": mean([r["latency_s"] for r in rows])}}

    with SimScreen(query, speed=a.speed) as scr:
        stream = None
        if a.stream:
            from reader.stream import LiveStream
            stream = LiveStream(scr.display, state, a.stream).start()
            print(f"실시간 중계: http://127.0.0.1:{a.stream}  (SSH -L {a.stream}:127.0.0.1:{a.stream})", flush=True)
            if a.wait_viewer:
                print("브라우저가 열릴 때까지 대기…", flush=True)
                while stream.viewers == 0: time.sleep(0.5)
        f = open(out / "reads.jsonl", "w", encoding="utf-8")
        ep[0] = {**pick(), "no": 0}; scr.load(ep[0]["fault"], ep[0]["seed"], ep[0]["adv"]); ep_t0 = time.time()
        t_start = time.time(); k = 0
        while time.time() - t_start < a.minutes * 60:
            png, tr = scr.capture(CLIP)
            res = vlm.read(png)
            truth = truth_at_minutes(tr["line"])
            sv = res["series"]
            errs = [abs(v - t) for v, t in zip(sv, truth) if t is not None] if sv else []
            r = {"k": k, "wall_s": round(time.time() - t_start, 1), "t": tr["t"], "episode": ep[0]["no"],
                 "fault": ep[0]["fault"], "seed": ep[0]["seed"],
                 "since_inject_s": (tr["t"] - tr["inject_tick"]) * 0.5,
                 "card": tr["card"], "gpc_display": tr["gpc_display"], "line_end": tr["line"][-1],
                 "vlm_now": sv[-1] if sv else None,
                 "err_card": (sv[-1] - tr["card"]) if sv else None, "err_line": (sv[-1] - tr["line"][-1]) if sv else None,
                 "series_vlm": sv, "series_truth": truth, "series_mae": sum(errs) / len(errs) if errs else None,
                 "pts_vlm": [to_screen(m, v) for m, v in zip(MINUTES, sv)] if sv else [],
                 "pts_truth": [to_screen(m, t) if t is not None else None for m, t in zip(MINUTES, truth)],
                 "raw": res["raw"], "latency_s": res["latency_s"], "provider": res["provider"]}
            from PIL import Image
            Image.open(io.BytesIO(png)).convert("RGB").save(out / "crops" / f"{k:04d}.jpg", quality=80)
            with lock: rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
            print(f"#{k:3d} [{r['episode']:2d} {r['fault']:7s}] {r['since_inject_s']:+5.0f}s 카드 {r['card']:.3f} 선끝 {r['line_end']:.3f} "
                  f"VLM {r['vlm_now'] if r['vlm_now'] is not None else '실패'} · 11곳 오차 "
                  f"{r['series_mae'] if r['series_mae'] is None else round(r['series_mae'], 4)} · {r['latency_s']}s", flush=True)
            k += 1
            if a.switch and time.time() - ep_t0 >= a.switch:
                ep[0] = {**pick(), "no": ep[0]["no"] + 1}; scr.load(ep[0]["fault"], ep[0]["seed"], ep[0]["adv"]); ep_t0 = time.time()
        f.close(); done[0] = True
        st_ = state(); s = {**st_["summary"], "per_scenario": st_["per_scenario"]}
        (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
        print("요약", json.dumps(s, ensure_ascii=False), flush=True)
        if stream:
            time.sleep(a.keep); stream.stop()


if __name__ == "__main__":
    main()
