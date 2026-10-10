"""VLM 에게 GPC 그래프(선)만 보여 주고 시계열 값을 읽게 한다.

화면 위쪽 숫자 카드는 잘라 내고 보낸다. 카드가 보이면 모델이 그래프 대신 숫자를 베껴 쓴다.
카드 숫자는 채점에만 쓴다.
"""
from __future__ import annotations

import base64, json, re, time
from pathlib import Path

from .screen import COORDS

# 그래프 상자(화면 좌표) — 카드(y 90~170)는 들어가지 않는다
CHART = COORDS["charts_clean"]["gpc"]                       # x 40, y 184, w 1120, h 600, ymin 0.95, ymax 1.35
CLIP = {"x": CHART["x"], "y": CHART["y"], "width": CHART["w"], "height": CHART["h"]}
PAD = {"l": 96, "r": 22, "t": 32, "b": 28}                  # index.html PAD_G
PLOT = {"x0": CHART["x"] + PAD["l"], "x1": CHART["x"] + CHART["w"] - PAD["r"],
        "y0": CHART["y"] + PAD["t"], "y1": CHART["y"] + CHART["h"] - PAD["b"]}
MINUTES = list(range(-10, 1))                               # -10분 … 현재, 11곳

SYSTEM = "너는 공정 감시 그래프를 읽는 판독기다. 출력은 지정된 JSON 한 개뿐이다. 설명, 마크다운 펜스를 붙이지 마라."
PROMPT = (
    "이 그래프는 ALD 공정의 GPC(사이클당 성장률, Å/cycle) 최근 10분 추세다.\n"
    "가로축은 왼쪽 끝이 −10분, 오른쪽 끝이 '현재'이고 1분 간격으로 눈금이 있다.\n"
    "세로축 눈금(0.95 ~ 1.35, 0.05 간격)을 기준으로 파란 선의 높이를 읽어라.\n"
    "−10분, −9분, …, −1분, 현재 — 이 11곳에서 선의 값을 소수 셋째 자리까지 읽어라.\n"
    "마지막 값(현재)은 선의 오른쪽 끝 값이다.\n"
    '{"series": [<−10분>, <−9분>, <−8분>, <−7분>, <−6분>, <−5분>, <−4분>, <−3분>, <−2분>, <−1분>, <현재>]}'
)


def truth_at_minutes(line: list[float]) -> list[float]:
    """그려진 선(120점, 오른쪽 정렬)에서 -10분…현재 위치의 값. index.html timeAxis 와 같은 배치."""
    n_full = 120
    off = n_full - len(line)
    out = []
    for m in MINUTES:
        pos = (m + 10) / 10 * (n_full - 1) - off           # 선 배열 안의 위치
        if pos < 0: out.append(None); continue
        i = min(int(pos), len(line) - 1); j = min(i + 1, len(line) - 1); f = pos - i
        out.append(line[i] * (1 - f) + line[j] * f)
    return out


def to_screen(minute: int, v: float):
    """(분, 값) → 화면 픽셀. 실시간 화면에 VLM 이 읽은 점을 겹쳐 그릴 때 쓴다."""
    x = PLOT["x0"] + (PLOT["x1"] - PLOT["x0"]) * (minute + 10) / 10
    c = min(CHART["ymax"], max(CHART["ymin"], v))
    y = PLOT["y1"] - (PLOT["y1"] - PLOT["y0"]) * (c - CHART["ymin"]) / (CHART["ymax"] - CHART["ymin"])
    return round(x, 1), round(y, 1)


def parse_series(text: str):
    m = re.search(r'"series"\s*:\s*\[([^\]]*)\]', text or "")
    if not m: return None
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(1))]
    return nums if len(nums) == len(MINUTES) else None


class SeriesReader:
    def __init__(self, base: str, model: str, key_file: str | None, fast_provider: bool = True, no_think: bool = True):
        from openai import OpenAI
        key = Path(key_file).expanduser().read_text().strip() if key_file else "x"
        self.cli, self.model = OpenAI(base_url=base, api_key=key), model
        self.extra = {}
        if no_think: self.extra["reasoning"] = {"enabled": False}
        if fast_provider: self.extra["provider"] = {"sort": "latency"}

    def read(self, png: bytes) -> dict:
        t0 = time.time()
        r = self.cli.chat.completions.create(
            model=self.model, temperature=0, max_tokens=200, extra_body=self.extra,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": [
                          {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
                          {"type": "text", "text": PROMPT}]}])
        raw = r.choices[0].message.content or ""
        prov = (r.model_extra or {}).get("provider")
        return {"raw": raw, "series": parse_series(raw), "latency_s": round(time.time() - t0, 2), "provider": prov}
