"""VLM 센서 — 매 초 화면에서 GPC '현재'(그래프 선 오른쪽 끝)와 노브 설정값 5개를 읽는다.

그림 두 장을 한 번에 보낸다: ① GPC 그래프 상자(숫자 카드 제외) ② 노브 줄. 61점처럼 많이 읽히면 선을 지어내므로
매 초 '현재' 하나만 읽고 시계열은 에이전트가 쌓는다.
"""
from __future__ import annotations

import base64, json, re, time

from .vlm import CLIP

KNOB_CLIP = {"x": 40, "y": 796, "width": 1840, "height": 112}
SYSTEM = "너는 공정 감시 화면을 읽는 판독기다. 출력은 지정된 JSON 한 개뿐이다. 설명, 마크다운 펜스를 붙이지 마라."
PROMPT = ("첫 번째 그림은 GPC(Å/cycle) 최근 10분 그래프다. 세로축 0.95~1.35, 0.05 간격 눈금.\n"
          "파란 선의 오른쪽 끝('현재') 값을 세로축 눈금 기준으로 소수 셋째 자리까지 읽어라.\n"
          "두 번째 그림은 노브 설정값 줄이다. 온도, 압력, 펄스 Pulse, 퍼지 Purge, 유량 칸 오른쪽 위에 크게 적힌 숫자를 읽어라.\n"
          '{"gpc_now": <숫자>, "knobs": {"temp": <숫자>, "press": <숫자>, "pulse": <숫자>, "purge": <숫자>, "flow": <숫자>}}')
KEYS = ("temp", "press", "pulse", "purge", "flow")


def _uri(png): return "data:image/png;base64," + base64.b64encode(png).decode()


def parse(raw: str):
    m = re.search(r'"gpc_now"\s*:\s*"?(-?\d+(?:\.\d+)?)', raw or "")
    gpc = float(m.group(1)) if m else None
    knobs = {}
    for k in KEYS:
        mk = re.search(rf'"{k}"\s*:\s*"?(-?\d+(?:\.\d+)?)', raw or "")
        if mk: knobs[k] = float(mk.group(1))
    return gpc, (knobs if len(knobs) == len(KEYS) else None)


def read(cli, model, extra, graph_png, knob_png) -> dict:
    t0 = time.time()
    r = cli.chat.completions.create(model=model, temperature=0, max_tokens=120, extra_body=extra, messages=[
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": _uri(graph_png)}},
                                     {"type": "image_url", "image_url": {"url": _uri(knob_png)}},
                                     {"type": "text", "text": PROMPT}]}])
    raw = r.choices[0].message.content or ""
    gpc, knobs = parse(raw)
    return {"raw": raw, "gpc": gpc, "knobs": knobs, "latency_s": round(time.time() - t0, 2)}
