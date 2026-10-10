"""폐루프 에이전트 (Python) — sim/agent_v2.js 의 Agent 와 같은 규칙. 입력은 VLM 이 매 초 읽은 값을 쌓은 시계열.

  - 매 초: 쌓인 GPC·균일도 시계열 → detect_v2 → 같은 판정이 15초 이어지면 버튼을 누른다
  - 누른 뒤 기다림(압력 90초, 나머지 30초) → 누른 직후 그래프가 이상 반대 방향으로 움직였나 확인
  - 같은 버튼이 두 번 연속 듣지 않으면 누른 만큼 되돌리고 5분 금지
  - 노브가 끝까지 가 있으면 더 누르지 않고 클리닝 요청 (노브 값은 화면에서 읽어 넘겨준다)
"""
from __future__ import annotations

import math

from reader.detect_v2 import SIG_DEG, U_SCALE, detect

REVERSE = {"temp_up": "temp_down", "temp_down": "temp_up", "press_up": "press_down", "press_down": "press_up",
           "pulse_up": "pulse_down", "pulse_down": "pulse_up", "purge_up": "purge_down", "purge_down": "purge_up",
           "flow_up": "flow_down", "flow_down": "flow_up"}
KNOB_RANGE = {"temp": (230, 280), "press": (0.8, 2.2), "pulse": (0.04, 0.20), "purge": (2.0, 9.0), "flow": (100, 400)}
WAIT_S = {"press_down": 90}
HOLD_S = 15


class Agent:
    def __init__(self):
        self.ts, self.gs, self.us = [], [], []
        self.wait_until = float("-inf"); self.banned = {}; self.presses = []; self.streak = None; self.pending = None
        self.hist = []; self.log = []; self.last_act = None; self.last = None

    def observe(self, t, g, u):
        if g is None or u is None: return
        self.ts.append(t); self.gs.append(g); self.us.append(u)
        while self.ts and self.ts[0] < t - 600: self.ts.pop(0); self.gs.pop(0); self.us.pop(0)

    def step(self, now, knobs_fn, press_fn):
        """knobs_fn(): 화면에서 읽은 노브 값 dict (누르기 직전에만 부른다). press_fn(action_id): 버튼을 누른다."""
        mine = [p["t"] - now for p in self.presses if now - p["t"] < 90]
        d = detect(self.ts, self.gs, self.us, now, ignore=mine) if len(self.ts) >= 2 else {"cause": "normal", "action": "noop", "why": "값 없음", "feat": {}}
        def note(a, why): self.last = {"d": d, "act": a, "why": why}; return self.last
        def do(a, cause): press_fn(a); self.presses.append({"t": now, "act": a, "cause": cause}); self.last_act = a
        if now < self.wait_until:
            return note("noop", f"대기 {math.ceil(self.wait_until - now)}초 ({self.last_act} 효과 확인 중)")
        if self.pending:
            p, self.pending = self.pending, None
            f = d["feat"]
            if p["cause"] == "press":
                good = p["osc"] - f.get("osc_sd", 0) > 0.002; how = f"흔들림 {p['osc']:.3f}→{f.get('osc_sd', 0):.3f}"
            else:
                r = math.radians(SIG_DEG[p["cause"]])
                proj = -((f.get("dgpc", 0) - p["x"]) * math.cos(r) + (f.get("du", 0) / U_SCALE - p["y"]) * math.sin(r))
                good = proj > 0.005; how = f"이상 반대 방향으로 {proj:+.3f}"
            sk = self.streak
            if sk and sk["act"] == p["act"]: sk["bad"] = 0 if good else sk["bad"] + 1
            self.log.append({"t": now, "act": p["act"], "good": good, "how": how})
            if sk and sk["bad"] >= 2:
                for _ in range(sk["n"]): do(REVERSE[sk["act"]], "되돌림")
                self.banned[sk["act"]] = now + 300; self.streak = None; self.wait_until = now + 30; self.hist = []
                return note(REVERSE[sk["act"]], f"{sk['act']} 가 두 번 연속 듣지 않았다 ({how}) → {sk['n']}번 되돌리고 5분 금지")
        act, why = d["action"], d["why"]
        self.hist = [h for h in self.hist if now - h[0] < HOLD_S - 1e-9] + [(now, d["cause"])]
        if act == "noop":
            if d["cause"] == "normal": self.streak = None
            return note("noop", why)
        if not (len(self.hist) >= HOLD_S and all(h[1] == d["cause"] for h in self.hist)):
            return note("noop", f"{why} — 판정이 {HOLD_S}초 이어지면 누른다")
        if self.banned.get(act, -1) > now:
            return note("noop", f"{why} — 그런데 {act} 는 방금 듣지 않아 보류")
        knob, dr = act.rsplit("_", 1)
        if knob in KNOB_RANGE:
            kv = knobs_fn() or {}
            lo, hi = KNOB_RANGE[knob]
            if knob in kv and ((dr == "up" and kv[knob] >= hi - 1e-9) or (dr == "down" and kv[knob] <= lo + 1e-9)):
                act, why = "request_clean", f"{knob} 노브가 끝({kv[knob]})인데 {why} → 클리닝 요청"
        if act in REVERSE:
            sk = self.streak
            self.streak = dict(sk, n=sk["n"] + 1) if sk and sk["act"] == act else {"act": act, "n": 1, "bad": 0}
            f = d["feat"]; self.pending = {"act": act, "cause": d["cause"], "x": f.get("dgpc", 0), "y": f.get("du", 0) / U_SCALE, "osc": f.get("osc_sd", 0)}
        do(act, d["cause"]); self.hist = []
        self.wait_until = now + WAIT_S.get(act, 30)
        return note(act, why)
