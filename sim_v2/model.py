#!/usr/bin/env python3
"""시뮬레이터 v2 설계안 — 피처(실효 공정값)가 GPC·균일도를 만든다.

  실효 피처 = 노브 설정값 + 숨은 교란 dᵢ(t)
  GPC      = 1.10 + Σ (피처별 GPC 항) + 잡음
  균일도    = 0.90 + Σ (피처별 균일도 항) + 잡음

이상 = 피처 하나에 교란을 넣는 것. 원본 hmi(v1)는 건드리지 않는다. 이 파일은 설계를 그려 보는 용도.

  python sim_v2/model.py      → sim_v2/design.json
"""
from __future__ import annotations

import json, math, random
from pathlib import Path

BASE = {"temp": 255.0, "press": 1.4, "pulse": 0.10, "purge": 4.5, "flow": 225.0}
STEP = {"temp": 5.0, "press": 0.1, "pulse": 0.01, "purge": 0.5, "flow": 25.0}
GPC_BAND, U_BAND = (1.05, 1.15), (0.50, 1.30)
OSC_PERIOD_S = 40

# ---- 피처 → 지표 (설계 핵심). 펄스·퍼지는 기준값 이상이면 포화(더 늘려도 효과 없음) — 실제 ALD 의 자기제한 반응
def gpc_terms(T, P_amp, pulse, purge, flow, t):
    return {"temp":  -0.006 * (T - 255.0),                       # 실효 온도 ↓ → 응축·물리흡착 → GPC ↑
            "purge":  0.08 * max(0.0, 4.5 - purge),              # 퍼지 부족 → 잔류 가스 CVD 성장 → GPC ↑
            "pulse": -4.0 * max(0.0, 0.10 - pulse),              # 전구체 부족 → 미포화 → GPC ↓
            "press":  0.25 * P_amp * math.sin(2 * math.pi * t / OSC_PERIOD_S),   # 압력 진동 → GPC 진동 (설정값 효과는 knob_terms)
            "flow":   0.0003 * (flow - 225.0) if flow < 225 else 0.0004 * (flow - 225.0)}   # 유량 ↓ → GPC 조금 ↓, 과다 → 조금 ↑

def u_terms(T, P_amp, pulse, purge, flow):
    return {"temp":  0.002 * abs(T - 255.0),                     # 온도는 웨이퍼 전체에 고르게 → 균일도 거의 그대로
            "purge": 0.30 * max(0.0, 4.5 - purge) - 0.02 * max(0.0, purge - 4.5),   # 잔류 가스 국부적 → 크게 나빠짐, 넉넉하면 조금 좋아짐
            "pulse": 3.0 * max(0.0, 0.10 - pulse) + 2.0 * max(0.0, pulse - 0.10),   # 미포화·과다 모두 가장자리부터
            "press": 1.0 * P_amp,                                # 진동은 위치마다 다르게 → 나빠짐
            "flow":  0.006 * max(0.0, 225.0 - flow) + 0.0012 * max(0.0, flow - 225.0)}   # 부족 → 크게, 과다(난류) → 조금 나빠짐

# ---- 숨은 교란 dᵢ(t) — 피처마다 시간 모양이 다르다. t = 주입 후 초
def smooth(x): x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)
DISTURB = {
    "temp":  lambda t: -min(30.0, 20.0 * t / 300.0) if t >= 0 else 0.0,        # 완만한 하강(벽 증착 누적)
    "purge": lambda t: -1.5 * (1 - math.exp(-t / 5.0)) if t >= 0 else 0.0,     # 급락(배기 밸브 고착)
    "pulse": lambda t: -0.03 * smooth((t - 30) / 120.0),                       # 30초 뒤 꺾이며 하강(버블러 고갈)
    "press": lambda t: 0.24 * (1 - math.exp(-t / 60.0)) if t >= 0 else 0.0,    # 진동 진폭 증가(배기 제어 불안정)
    "flow":  lambda t: -75.0 * (1 - math.exp(-t / 40.0)) if t >= 0 else 0.0,   # 운반 유량 감소(MFC 드리프트)
}
FIX = {"temp": ("temp", +1), "purge": ("purge", +1), "pulse": ("pulse", +1), "press": ("press", -1), "flow": ("flow", +1)}
WRONG = {"temp": ("purge", +1), "purge": ("temp", +1), "pulse": ("flow", +1), "press": ("purge", +1), "flow": ("pulse", +1)}
LABEL = {"temp": "온도", "press": "압력", "pulse": "펄스", "purge": "퍼지", "flow": "유량", "normal": "정상"}


def simulate(fault, presses=(), t0=-180, t1=420, seed=7):
    """presses: [(t, knob, dir)]. 반환: 1초 간격 t, gpc, u, 노브, 실효 피처."""
    rng = random.Random(seed); knobs = dict(BASE); out = []
    wob_g = wob_u = 0.0
    for t in range(t0, t1 + 1):
        for (tp, k, d) in presses:
            if tp == t: knobs[k] = round(knobs[k] + d * STEP[k], 4)
        d = DISTURB[fault](t) if fault in DISTURB else 0.0
        eff = dict(knobs)
        if fault in ("temp", "purge", "pulse", "flow"): eff[fault] += d
        amp = (d if fault == "press" else 0.0) * min(1.0, max(0.0, (knobs["press"] - 1.2) / 0.2))   # 압력 설정을 2칸 낮추면 진동이 멎는다
        wob_g = 0.97 * wob_g + rng.gauss(0, 0.0025); wob_u = 0.97 * wob_u + rng.gauss(0, 0.008)
        g = gpc_terms(eff["temp"], amp, eff["pulse"], eff["purge"], eff["flow"], t); g["press"] += 0.10 * (knobs["press"] - 1.4)
        u = u_terms(eff["temp"], amp, eff["pulse"], eff["purge"], eff["flow"]); u["press"] += 0.3 * abs(knobs["press"] - 1.4)
        out.append({"t": t, "gpc": round(1.10 + sum(g.values()) + wob_g + rng.gauss(0, 0.006), 4),
                    "u": round(0.90 + sum(u.values()) + wob_u + rng.gauss(0, 0.02), 4),
                    "knobs": dict(knobs), "terms_g": {k: round(v, 4) for k, v in g.items()}})
    return out


def signature(fault):
    """노이즈 없는 지문: 주입 후 60/120/300초의 ΔGPC, Δ균일도, 대역 이탈 시각."""
    rows = []
    for t in (60, 120, 300):
        d = DISTURB[fault](t); eff = dict(BASE)
        if fault != "press": eff[fault] += d
        amp = d if fault == "press" else 0.0
        g = sum(gpc_terms(eff["temp"], amp, eff["pulse"], eff["purge"], eff["flow"], OSC_PERIOD_S / 4).values())
        u = sum(u_terms(eff["temp"], amp, eff["pulse"], eff["purge"], eff["flow"]).values())
        rows.append({"t": t, "dgpc": round(g, 3), "du": round(u, 3)})
    exit_g = next((t for t in range(0, 600) if abs(_g(fault, t)) > 0.05), None)
    exit_u = next((t for t in range(0, 600) if _u(fault, t) > 0.40), None)
    return {"at": rows, "gpc_exit_s": exit_g, "u_exit_s": exit_u}


def _g(f, t):
    d = DISTURB[f](t); eff = dict(BASE)
    if f != "press": eff[f] += d
    amp = d if f == "press" else 0.0
    return sum(gpc_terms(eff["temp"], amp, eff["pulse"], eff["purge"], eff["flow"], OSC_PERIOD_S / 4).values())


def _u(f, t):
    d = DISTURB[f](t); eff = dict(BASE)
    if f != "press": eff[f] += d
    amp = d if f == "press" else 0.0
    return sum(u_terms(eff["temp"], amp, eff["pulse"], eff["purge"], eff["flow"]).values())


def main():
    press_t = (120, 150, 180)
    cases = []
    for f in ["normal", "temp", "purge", "pulse", "press", "flow"]:
        c = {"fault": f, "label": LABEL[f], "runs": {"none": simulate(f)}}
        if f in FIX:
            k, d = FIX[f]; w, wd = WRONG[f]
            c["fix"] = {"knob": k, "dir": d, "times": press_t}; c["wrong"] = {"knob": w, "dir": wd, "times": press_t}
            pt = press_t[:2] if f == "press" else press_t            # 압력은 2칸이면 진동이 멎는다
            c["fix"]["times"] = c["wrong"]["times"] = pt
            c["runs"]["fix"] = simulate(f, [(t, k, d) for t in pt])
            c["runs"]["wrong"] = simulate(f, [(t, w, wd) for t in pt])
            c["signature"] = signature(f)
        for key, r in c["runs"].items():      # 그리기용으로 줄인다: [t, gpc, u]
            c["runs"][key] = [[p["t"], p["gpc"], p["u"]] for p in r]
        cases.append(c)
    out = Path(__file__).parent / "design.json"
    out.write_text(json.dumps({"band_gpc": GPC_BAND, "band_u": U_BAND, "cases": cases}, ensure_ascii=False))
    for c in cases:
        if "signature" in c:
            s = c["signature"]
            print(f"{c['label']:3s} " + "  ".join(f"+{r['t']}s ΔGPC {r['dgpc']:+.3f} ΔU {r['du']:+.3f}" for r in s["at"])
                  + f" | GPC ±0.05 넘는 시각 {s['gpc_exit_s']}s, 균일도 +0.40 넘는 시각 {s['u_exit_s']}s")


if __name__ == "__main__":
    main()
