"""v2 화면용 VLM 두 가지 — ① 두 그래프에서 '현재' 값 읽기 ② 조작 문장 → 버튼 좌표 (grounding).

① 그림 두 장(GPC 그래프 상자, 균일도 그래프 상자)을 한 번에 보낸다. 위쪽 숫자 카드는 잘라 낸다.
② 전체 화면 + 조작 문장 → 0~1000 정규화 좌표 → 픽셀.
"""
from __future__ import annotations

import base64, json, re, time
from pathlib import Path

from reader.screen import COORDS

# ---- 버튼 grounding: 조작 문장 (labels=both 화면에 맞춘 것 — 라벨과 지시문을 같이 바꿔야 퍼지/펄스 혼동이 사라진다)
GOAL_BOTH = {
    "temp_down": "온도 설정을 한 단계 내려라", "temp_up": "온도 설정을 한 단계 올려라",
    "press_down": "압력 설정을 한 단계 내려라", "press_up": "압력 설정을 한 단계 올려라",
    "pulse_down": "펄스(Pulse) 시간을 한 단계 줄여라", "pulse_up": "펄스(Pulse) 시간을 한 단계 늘려라",
    "purge_down": "퍼지(Purge) 시간을 한 단계 줄여라", "purge_up": "퍼지(Purge) 시간을 한 단계 늘려라",
    "flow_down": "유량 설정을 한 단계 내려라", "flow_up": "유량 설정을 한 단계 올려라",
    "request_clean": "챔버 클리닝을 요청하라",
}
G_SYSTEM = "당신은 공정 감시 화면을 조작하는 에이전트다. 출력은 지정된 JSON 한 개뿐이다. 마크다운 펜스, 설명, 접두어를 붙이지 마라."


def g_prompt(goal: str) -> str:
    return ("너는 아래 도구 하나를 쓸 수 있다.\n"
            "  click(x, y) — 화면의 (x, y) 를 마우스로 클릭한다\n"
            "좌표는 화면 왼쪽 위를 (0, 0), 오른쪽 아래를 (1000, 1000) 으로 하는 값이다.\n\n"
            f"목표: {goal}\n"
            "목표를 이루려면 어디를 클릭해야 하는가.\n"
            '{"action": "click", "x": <정수>, "y": <정수>}')


def _parse_xy(t: str):
    """작은 모델이 자주 내는 깨진 JSON({"x": 366, 878})도 숫자로 건져낸다."""
    m = re.search(r"\{.*?\}", t or "", re.S) or re.search(r"\{.*", t or "", re.S)   # 닫는 } 를 빠뜨린 경우({"x": 196, 874])도
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return float(v["x"]), float(v["y"])
    except Exception:
        n = re.findall(r"-?\d+(?:\.\d+)?", re.sub(r'"[^"]*"\s*:', "", m.group(0)))
        return (float(n[0]), float(n[1])) if len(n) >= 2 else None

GPC_CLIP = {"x": 40, "y": 184, "width": 1120, "height": 600}
U_CLIP = {"x": 1200, "y": 184, "width": 680, "height": 600}
R_SYSTEM = "너는 공정 감시 그래프를 읽는 판독기다. 출력은 지정된 JSON 한 개뿐이다. 설명, 마크다운 펜스를 붙이지 마라."
R_PROMPT = ("첫 번째 그림은 GPC(Å/cycle) 최근 10분 그래프다. 세로축 0.95~1.35, 0.05 간격 눈금.\n"
            "두 번째 그림은 균일도(%) 최근 10분 그래프다. 세로축 0.40~1.80, 0.20 간격 눈금.\n"
            "각 그래프에서 선의 오른쪽 끝('현재') 값을 세로축 눈금 기준으로 읽어라. GPC 는 소수 셋째 자리, 균일도는 소수 둘째 자리까지.\n"
            '{"gpc_now": <숫자>, "u_now": <숫자>}')
# 화면에 그려진 선의 오른쪽 끝 (index.html drawChart 와 같은 15초 이동평균) — 채점용
TRUTH_JS = """(() => { const s = window.aldSim(), v = s.view(), sm = a => { const r = a.map(p => p.v), n = r.length;
  return r.map((_, i) => { const lo = Math.max(0, i - 1), hi = Math.min(n, i + 2); let t = 0; for (let j = lo; j < hi; j++) t += r[j]; return t / (hi - lo); }); };
  const g = s.gt(); return { t: s.t, gpc_line: sm(v.gpcPoints).slice(-1)[0], u_line: sm(v.uPoints).slice(-1)[0],
  gpc_card: +v.gpc.toFixed(3), u_card: +v.uniformity.toFixed(2), knobs: Object.assign({}, s.knobs), fault: g.fault_type,
  since: (g.t - g.inject_tick) * 0.5, correct_action: g.correct_action }; })()"""


# 화면 버튼 줄에 적힌 이름 그대로 (sim/index.html labels=both)
ROW_LABEL = {"temp": "온도 (°C)", "press": "압력 (Torr)", "pulse": "펄스 Pulse (s)", "purge": "퍼지 Purge (s)", "flow": "유량 (sccm)"}


def label_goal(action_id):
    if action_id == "request_clean": return "화면 맨 아래 조작 버튼 영역의 '클리닝 요청' 버튼을 눌러라"
    knob, d = action_id.rsplit("_", 1)
    return (f"화면 맨 아래 조작 버튼 영역에서 '{ROW_LABEL[knob]}' 라고 적힌 이름 바로 오른쪽에 있는 두 버튼 중 "
            f"{'왼쪽 − (빼기)' if d == 'down' else '오른쪽 + (더하기)'} 버튼을 한 번 눌러라")


def _uri(png): return "data:image/png;base64," + base64.b64encode(png).decode()


class VLM:
    def __init__(self, model="qwen/qwen3.5-27b", key_file="~/.qwen27b_key", base="https://openrouter.ai/api/v1"):
        from openai import OpenAI
        self.cli = OpenAI(base_url=base, api_key=Path(key_file).expanduser().read_text().strip())
        self.model = model
        self.extra = {"reasoning": {"enabled": False}, "provider": {"sort": "latency"}}

    def _ask(self, system, images, text, max_tokens=80):
        t0 = time.time()
        r = self.cli.chat.completions.create(model=self.model, temperature=0, max_tokens=max_tokens, extra_body=self.extra,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": [*({"type": "image_url", "image_url": {"url": _uri(p)}} for p in images),
                                                   {"type": "text", "text": text}]}])
        return r.choices[0].message.content or "", round(time.time() - t0, 2)

    def read(self, gpc_png, u_png) -> dict:
        raw, lat = self._ask(R_SYSTEM, [gpc_png, u_png], R_PROMPT)
        num = lambda k: (lambda m: float(m.group(1)) if m else None)(re.search(rf'"{k}"\s*:\s*"?(-?\d+(?:\.\d+)?)', raw))
        return {"gpc": num("gpc_now"), "u": num("u_now"), "raw": raw, "latency_s": lat}

    def ground(self, screen_png, action_id, W=1920, H=1080, style="label") -> dict:
        """조작 문장 → 픽셀 좌표. 좌표를 못 건지면 xy=None (누르지 않는다).
        style: "goal" = 하려는 일만 말한다 / "label" = 화면에 적힌 이름과 −/+ 를 직접 짚는다"""
        goal = GOAL_BOTH[action_id] if style == "goal" else label_goal(action_id)
        raw, lat = self._ask(G_SYSTEM, [screen_png], g_prompt(goal), max_tokens=60)
        xy = _parse_xy(raw)
        px = None if xy is None else (max(0, min(W - 1, round(xy[0] * W / 1000))), max(0, min(H - 1, round(xy[1] * H / 1000))))
        b = COORDS["buttons"][action_id]
        hit = px is not None and abs(px[0] - b["x"]) <= b["w"] / 2 and abs(px[1] - b["y"]) <= b["h"] / 2
        return {"goal": goal, "raw": raw, "norm": xy, "xy": px, "latency_s": lat, "in_box": hit,
                "err_px": None if px is None else max(abs(px[0] - b["x"]), abs(px[1] - b["y"]))}
