/* ---------------------------------------------------------------------------
 * 좌표 단일 소스. 렌더링(index.html)과 드라이버가 이 파일 하나만 참조한다.
 * 값 부분은 순수 JSON 이라 파이썬도 그대로 json.loads 로 읽는다.
 *
 * 버튼 y: 사양서 7절의 1010/1080 은 R4(920~1050) 안에 들어가지 않아
 *         952/1018 로 옮겼다. x 는 7절 그대로다.
 * ------------------------------------------------------------------------- */
const COORDS =
{
  "canvas": { "w": 1920, "h": 1080 },

  "regions": {
    "R1": { "x": 40,   "y": 90,  "w": 1840, "h": 80,  "role": "현재값 카드 2개" },
    "R2": { "x": 40,   "y": 184, "w": 1840, "h": 600, "role": "결과 그래프 2개 — 주 정보원. GPC 를 세로로 크게(패치 17개)" },
    "R3": { "x": 40,   "y": 796, "w": 1840, "h": 112, "role": "노브 스파크라인 5개" },
    "R4": { "x": 40,   "y": 920, "w": 1200, "h": 130, "role": "제어 버튼" },
    "R5": { "x": 1260, "y": 920, "w": 620,  "h": 130, "role": "조치 이력" }
  },

  "crops": {
    "R2_PLUS_R5": { "x": 40, "y": 184, "w": 1840, "h": 866 },
    "R2_ONLY":    { "x": 40, "y": 184, "w": 1840, "h": 600 },
    "GPC_ONLY":   { "x": 40, "y": 184, "w": 1120, "h": 600 }
  },

  "value_cards": [
    { "key": "gpc",        "x": 40,  "y": 90, "w": 910, "h": 80 },
    { "key": "uniformity", "x": 970, "y": 90, "w": 910, "h": 80 }
  ],

  "charts": {
    "gpc":        { "x": 40, "y": 188, "w": 1840, "h": 468, "ymin": 0.80, "ymax": 1.50 },
    "uniformity": { "x": 40, "y": 658, "w": 1840, "h": 124, "ymin": 0.40, "ymax": 1.80 }
  },

  "_charts_clean_note": "ui=clean: 선만 남긴 차트. GPC 는 ChartQA 비율로 크게, 균일도는 떨어진 별도 상자. 좌표는 R2 안.",
  "charts_clean": {
    "gpc":        { "x": 40,   "y": 184, "w": 1120, "h": 600, "ymin": 0.95, "ymax": 1.35 },
    "uniformity": { "x": 1200, "y": 184, "w": 680,  "h": 600, "ymin": 0.40, "ymax": 1.80 }
  },

  "sparklines": [
    { "key": "temp", "x": 40, "y": 796, "w": 352, "h": 112 },
    { "key": "press", "x": 412, "y": 796, "w": 352, "h": 112 },
    { "key": "pulse", "x": 784, "y": 796, "w": 352, "h": 112 },
    { "key": "purge", "x": 1156, "y": 796, "w": 352, "h": 112 },
    { "key": "flow", "x": 1528, "y": 796, "w": 352, "h": 112 }
  ],

  "buttons": {
    "temp_down":     { "x": 310,  "y": 952,  "w": 56,  "h": 56, "label": "−", "knob": "temp",  "dir": -1 },
    "temp_up":       { "x": 380,  "y": 952,  "w": 56,  "h": 56, "label": "+",      "knob": "temp",  "dir":  1 },
    "press_down":    { "x": 710,  "y": 952,  "w": 56,  "h": 56, "label": "−", "knob": "press", "dir": -1 },
    "press_up":      { "x": 780,  "y": 952,  "w": 56,  "h": 56, "label": "+",      "knob": "press", "dir":  1 },
    "pulse_down":    { "x": 1110, "y": 952,  "w": 56,  "h": 56, "label": "−", "knob": "pulse", "dir": -1 },
    "pulse_up":      { "x": 1180, "y": 952,  "w": 56,  "h": 56, "label": "+",      "knob": "pulse", "dir":  1 },
    "purge_down":    { "x": 310,  "y": 1018, "w": 56,  "h": 56, "label": "−", "knob": "purge", "dir": -1 },
    "purge_up":      { "x": 380,  "y": 1018, "w": 56,  "h": 56, "label": "+",      "knob": "purge", "dir":  1 },
    "flow_down":     { "x": 710,  "y": 1018, "w": 56,  "h": 56, "label": "−", "knob": "flow",  "dir": -1 },
    "flow_up":       { "x": 780,  "y": 1018, "w": 56,  "h": 56, "label": "+",      "knob": "flow",  "dir":  1 },
    "request_clean": { "x": 1080, "y": 1018, "w": 200, "h": 56, "label": "클리닝 요청", "knob": null, "dir": 0 }
  },

  "button_groups": [
    { "knob": "temp",  "x": 80,  "y": 952  },
    { "knob": "press", "x": 480, "y": 952  },
    { "knob": "pulse", "x": 880, "y": 952  },
    { "knob": "purge", "x": 80,  "y": 1018 },
    { "knob": "flow",  "x": 480, "y": 1018 }
  ],

  "actions": [
    "temp_down", "temp_up", "press_down", "press_up", "pulse_down", "pulse_up",
    "purge_down", "purge_up", "flow_down", "flow_up", "request_clean", "noop"
  ]
}
;
if (typeof module !== "undefined") module.exports = COORDS;
if (typeof window !== "undefined") window.COORDS = COORDS;
