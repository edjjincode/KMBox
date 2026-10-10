"""설계 검증: 잡음 있는 그래프만 보고 간단한 규칙이 원인 피처를 맞히는가 (지문이 실제로 구분되는지)."""
import statistics as st
from collections import Counter
from model import simulate

def classify(run, t_now):
    win = [p for p in run if t_now - 600 < p["t"] <= t_now]          # 화면처럼 최근 10분
    base = [p for p in win if p["t"] <= t_now - 420]                   # 창 앞쪽 3분 = 기준
    last = [p for p in win if p["t"] > t_now - 60]                     # 최근 1분
    dg = st.mean(p["gpc"] for p in last) - st.mean(p["gpc"] for p in base)
    du = st.mean(p["u"] for p in last) - st.mean(p["u"] for p in base)
    g = [p["gpc"] for p in win[-120:]]                                   # 진동: 최근 2분에서 직선 추세를 빼고 남는 흔들림
    n = len(g); mx = (n - 1) / 2; my = st.mean(g)
    b = sum((i - mx) * (v - my) for i, v in enumerate(g)) / sum((i - mx) ** 2 for i in range(n))
    osc = st.pstdev([v - (my + b * (i - mx)) for i, v in enumerate(g)])
    if osc > 0.022: return "press"
    if du > 0.25: return "purge" if dg > 0.05 else "flow"
    if dg > 0.04: return "temp"
    if dg < -0.04: return "pulse"
    return "normal"

FAULTS = ["normal", "temp", "purge", "pulse", "press", "flow"]; TIMES = [30, 60, 120, 180, 300]
print("정답률 (시드 20개, 화면 10분 창, 잡음 포함)")
print(f"{'':7s}" + "".join(f"{'+' + str(t) + 's':>8s}" for t in TIMES) + "   틀린 답")
for f in FAULTS:
    row, wrong = [], Counter()
    for t in TIMES:
        ok = 0
        for sd in range(20):
            run = simulate(f, t0=t - 600, t1=t, seed=sd)
            c = classify(run, t); ok += c == f
            if c != f: wrong[c] += 1
        row.append(ok)
    print(f"{f:7s}" + "".join(f"{o:>5d}/20" for o in row) + "   " + ", ".join(f"{k}×{v}" for k, v in wrong.most_common()))
