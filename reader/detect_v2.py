"""이상 감지 함수 (시뮬레이터 v2) — GPC·균일도 시계열만 보고 원인 피처와 조치를 정한다.

화면에서 읽을 수 있는 것만 쓴다: 최근 10분 GPC 선, 균일도 선 (몇 초 간격이든 된다).
지문 (sim_v2/model.py):
  피처   GPC          균일도      모양
  온도   ↑ (+0.12)    거의 그대로  완만한 상승
  퍼지   ↑ (+0.12)    ↑↑ (+0.45)  급등
  펄스   ↓ (−0.12)    조금 ↑       꺾이며 하강
  압력   ±0.06 진동   ↑ (+0.24)   40초 주기
  유량   거의 그대로   ↑↑ (+0.45)  균일도만 상승

판정: ① 진동(20초 이동평균을 뺀 흔들림 + 25~60초 주기) → 압력
      ② (GPC 변화, 균일도 변화/3) 크기가 작으면 정상
      ③ 아니면 그 방향이 가장 가까운 지문 피처 (절대 문턱 대신 '비율'로 본다 — 변화 초기에도 방향은 같다)
"""
from __future__ import annotations

import statistics as st

ACTION = {"normal": "noop", "temp": "temp_up", "purge": "purge_up", "pulse": "pulse_up", "press": "press_down", "flow": "flow_up"}
LABEL = {"normal": "정상", "temp": "온도", "purge": "퍼지", "pulse": "펄스", "press": "압력", "flow": "유량"}
TH = {"osc": 0.006, "acf": 0.3, "mag": 0.05}
TARGET = {"gpc": 1.100, "u": 0.900}   # 화면 카드의 '목표'
U_SCALE = 3.0      # 균일도 변화는 GPC 변화의 약 3배 크기로 움직인다 → 나눠서 같은 눈금으로 본다
# 지문 방향(도): (GPC 변화, 균일도 변화/3) 평면에서 각 피처 교란이 가리키는 방향 (sim_v2/model.py 의 +300초 값)
SIG_DEG = {"temp": 6.3, "purge": 51.3, "flow": 98.3, "pulse": 166.0}


def _seg(ts, vs, a, b):
    return [v for t, v in zip(ts, vs) if a < t <= b]


def _osc(ts, gs, t_now, win=90.0, ignore=()):
    """최근 90초 GPC 에서 20초 이동평균을 뺀 흔들림 크기와, 25~60초 주기 자기상관 최댓값.
    이동평균을 빼면 노브를 눌러 생긴 계단은 남지 않고 40초 진동만 남는다."""
    pts = [(t, v) for t, v in zip(ts, gs) if t > t_now - win]
    if len(pts) < 12: return 0.0, 0.0, None
    n = len(pts); tx = [p[0] for p in pts]; vy = [p[1] for p in pts]
    dt = (tx[-1] - tx[0]) / (n - 1); h = max(1, round(10 / dt))
    r = [vy[i] - st.mean(vy[max(0, i - h):min(n, i + h + 1)]) for i in range(n)]
    r = [0.0 if any(abs((tx[i] - t_now) - t) <= 10 for t in ignore) else x for i, x in enumerate(r)]   # 내가 누른 시각 ±10초는 뺀다
    sd = (sum(x * x for x in r) / n) ** 0.5
    s0 = sum(x * x for x in r) or 1e-12
    best, best_p = 0.0, None
    for lag in range(max(1, round(25 / dt)), min(n - 2, round(60 / dt)) + 1):
        c = sum(r[i] * r[i + lag] for i in range(n - lag)) / s0
        if c > best: best, best_p = c, lag * dt
    return sd, best, best_p


def detect(ts, gpc, uni, t_now=None, ignore=()):
    """ts: 초, gpc·uni: 같은 길이. 최근 20초 평균을 화면 목표값(GPC 1.100, 균일도 0.900)과 비교한다."""
    t_now = ts[-1] if t_now is None else t_now
    now_g, now_u = _seg(ts, gpc, t_now - 20, t_now), _seg(ts, uni, t_now - 20, t_now)   # 지금 = 최근 20초
    if len(now_g) < 2:
        return {"cause": "normal", "action": "noop", "why": "그래프가 비었다", "feat": {}}
    dg = st.mean(now_g) - TARGET["gpc"]; du = st.mean(now_u) - TARGET["u"]   # 화면 카드에 적힌 목표값과 비교
    sd, acf, per = _osc(ts, gpc, t_now, ignore=ignore)
    feat = {"dgpc": round(dg, 4), "du": round(du, 4), "osc_sd": round(sd, 4), "osc_acf": round(acf, 3), "period_s": per}
    def out(c, why): return {"cause": c, "action": ACTION[c], "why": why, "feat": feat}
    import math
    mag = math.hypot(dg, du / U_SCALE); ang = math.degrees(math.atan2(du / U_SCALE, dg))
    feat.update(mag=round(mag, 4), angle=round(ang, 1))
    if sd > TH["osc"] and acf > TH["acf"]:
        return out("press", f"GPC 가 {per:.0f}초 주기로 흔들림 (폭 {sd:.3f}, 상관 {acf:.2f})")
    if mag < TH["mag"]:
        return out("normal", f"GPC {dg:+.3f}, 균일도 {du:+.2f} — 변화가 작다")
    c = min(SIG_DEG, key=lambda k: abs((ang - SIG_DEG[k] + 180) % 360 - 180))
    return out(c, f"GPC {dg:+.3f}, 균일도 {du:+.2f} → 방향 {ang:.0f}° 가 {LABEL[c]} 지문({SIG_DEG[c]:.0f}°)에 가장 가깝다")
