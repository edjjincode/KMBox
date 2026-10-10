# series-reader — 화면만 보고 ALD 이상을 잡는 에이전트 (시뮬레이터 v2)

이 폴더만으로 돈다 (ald-vlm-agent 불필요).

```bash
cd KMBOX/series-reader
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m playwright install chromium          # 처음 한 번 (이미 있으면 생략)

.venv/bin/python sim/build_index.py                      # 화면 조립: hmi_template.html + engine_v2.js → sim/index.html
.venv/bin/python -m reader.verify_v2 --undo              # 감지 함수 검증 (정답 입력, VLM 없음, 1분)
FAULTS=flow PRE=5 ./run_loop_v2.sh                       # VLM 판독 → 함수 → 조치 제출, 보드 http://127.0.0.1:8765
./run_loop_v2.sh results/loop_v2/x vlm                   # 버튼 grounding 까지 VLM
```

OpenRouter 키는 `~/.qwen27b_key`. 판독 `qwen/qwen3.5-27b`, grounding `qwen/qwen3-vl-235b-a22b-instruct` (loop_v2 옵션으로 바꾼다).

| 폴더 / 파일 | 역할 |
|---|---|
| `sim/engine_v2.js` | 시뮬레이터 엔진 — 실효 피처 = 노브 + 교란, 정상 범위(공정 창), GPC·균일도 계산 |
| `sim/hmi_template.html`, `sim/coords.js` | 화면 틀과 좌표표 (ald-vlm-agent/hmi 에서 복사) |
| `sim/build_index.py` → `sim/index.html` | kiosk 화면 (VLM 이 보는 것) |
| `sim/agent_v2.js`, `reader/detect_v2.py`, `reader/agent_v2.py` | 감지 함수 + 폐루프 에이전트 (JS·Python 같은 규칙) |
| `reader/screen.py`, `reader/vlm_v2.py` | 가상 모니터·캡처, VLM 판독·버튼 grounding |
| `reader/loop_v2.py`, `reader/board_v2.py`, `run_loop_v2.sh` | 폐루프 에피소드, 실시간 보드 |
| `reader/verify_v2.py`, `reader/eval_v2.py`, `reader/probe_v2.py` | 검증 (함수·폐루프 / 판정 / VLM 판독·grounding) |
| `sim/build_artifact.py`, `sim/build_board.py` | 브라우저 보기용 페이지 (Artifact) |
| `sim_v2/` | 처음 설계안 (정상 범위 도입 전) |
| `legacy/` | v1 시뮬레이터 시절 시험 코드 (ald-vlm-agent 가 있어야 돈다) |

---

## (이전 기록) 
`ald-vlm-agent` 와 같은 시뮬레이터(`hmi/` 그대로 복사)를 실시간으로 돌리고, VLM 에게 **그래프 상자만** 보여 줘
선의 값을 읽게 한다. 버튼은 누르지 않는다. 판독 하나만 본다.

```bash
cd KMBOX/series-reader
../ald-vlm-agent/.venv/bin/python -m reader.run --scenario step --minutes 8 --wait-viewer
# 다른 PC 에서:  ssh -p 3015 -L 8765:127.0.0.1:8765 jc@<서버>   →   http://localhost:8765
```

## 한 번 판독하는 순서

1. 시뮬레이터를 잠깐 멈추고(0.1초 남짓) 그래프 상자(40,184 / 1120×600)를 캡처한다. **위쪽 숫자 카드는 잘라 낸다** — 보이면 모델이 숫자를 베낀다.
2. 같은 순간의 정답을 뜬다: 화면 숫자 카드 값, 그리고 **그래프에 실제로 그려진 선**(5초 버킷 평균 → 15초 이동평균).
3. VLM 에게 −10분 … 현재, 11곳의 선 값을 읽게 한다 (`reader/vlm.py` 의 `PROMPT`).
4. 채점: VLM '현재' ↔ 카드 / 선 끝, 11곳 ↔ 그려진 선. 중계 화면에 VLM 점(주황)과 실제 점(파랑 고리)을 겹친다.

**카드와 선 끝은 원래 다르다.** 카드는 순간값(잡음 포함), 선은 15초 평활이라 평소에도 ±0.01~0.02 벌어진다.
그래프를 읽는 능력은 '선 끝' 대비 오차로 보고, 카드 대비 오차는 "그래프만 보고 현재값을 얼마나 맞히나" 로 본다.

## 파일

| 파일 | 역할 |
|---|---|
| (시뮬레이터) | `../ald-vlm-agent/hmi` 원본을 그대로 연다 (복사하지 않음) |
| `reader/screen.py` | Xvfb + kiosk 크롬 + CDP. 캡처 순간 정지 + 정답 추출 |
| `reader/vlm.py` | 프롬프트, 응답 파싱, 정답 위치 계산, 화면 좌표 변환 |
| `reader/stream.py`, `stream_page.html` | 실시간 중계 (MJPEG + 판독 패널) |
| `reader/run.py` | 루프. 결과는 `results/<날짜>_<시나리오>_<모델>/` (`reads.jsonl`, `crops/`, `summary.json`) |

모델 기본값은 OpenRouter `qwen/qwen3.5-27b`, 키는 `~/.qwen27b_key`. 빠른 공급자 고정(`provider.sort=latency`)과
생각 모드 끄기가 기본으로 켜져 있다. `--model qwen/qwen3-vl-8b-instruct` 처럼 바꿔 끼운다.

## 시뮬레이터 v2 — 피처 교란 모델 (`sim/`, `sim_v2/`)

원본(`ald-vlm-agent/hmi`, v1)은 이상을 '곡선 모양'으로 GPC 에 직접 더한다. v2 는 피처 하나의 실효값을 틀어지게 하고
GPC·균일도가 수식으로 따라 움직인다 (`실효 피처 = 노브 + 교란 d(t)`). 화면·좌표·버튼은 v1 과 같다.

| 파일 | 역할 |
|---|---|
| `sim_v2/model.py`, `sim_v2/design.html` | 설계안(가중치·교란 모양)과 지문 그래프 |
| `sim/engine_v2.js` → `sim/index.html` | v2 엔진을 v1 화면에 끼운 kiosk 화면 (이상: normal temp purge pulse press flow) |
| `sim/build_artifact.py` → `sim/view.html` | 브라우저 보기용 (화면 축소 + 감지 함수 실시간 결과) |
| `reader/detect_v2.py`, `sim/agent_v2.js` | 감지 함수(같은 규칙, parity 시험) + 폐루프 에이전트(JS) |
| `reader/verify_v2.py` | 검증: parity · 판정(시드 30) · 정상 오경보 · 폐루프(시드 20). `--undo` 로 되돌리기 규칙 켬 |
| `sim/build_index.py`, `sim/build_board.py` | kiosk 화면 조립, 폐루프 보드(`sim/board.html`) |

감지 함수: 진동(20초 이동평균을 뺀 흔들림 + 25~60초 주기) → 압력. 아니면 (GPC−1.100, (균일도−0.900)/3) 의 크기가 0.05 미만이면 정상,
넘으면 방향이 가장 가까운 지문(온도 6° · 퍼지 51° · 유량 98° · 펄스 166°). 비교 기준은 화면 카드의 '목표' 값.
에이전트: 같은 판정 15초 유지 후 누름 → 30초(압력 90초) 대기 → 누른 직후 그래프가 이상 반대로 움직였나 확인 → 두 번 연속 아니면 되돌림.

| 결과 (verify_v2 --undo) | 정상 | 온도 | 퍼지 | 펄스 | 압력 | 유량 |
|---|---|---|---|---|---|---|
| 감지 시간 중앙값 | – | +150초 | +15초 | +105초 | +75초 | +30초 |
| 폐루프 끝 대역 안 (/20) | 20 | 19 | 20 | 20 | 20 | 20 |
| 잘못 누름 (20회 합) | 0 | 2 | 0 | 0 | 4 | 0 |

정상 30분 × 30시드 오경보 0/10800.

### 정상 범위(공정 창) 모델 — 2026-10-11

| 피처 | 정상 범위 | 이상 (실제값이 향하는 곳) | 범위 밖 효과 | 조치 |
|---|---|---|---|---|
| 온도 | 245–265 °C | 서서히 하강 (100초에 하한, 최대 −30) | 하한 아래 GPC↑ | 온도 + |
| 압력 | 1.2–1.6 Torr | ±0.24 진동 (양쪽 한계를 오감) | GPC 진동, 균일도↑ | 압력 − (2번) |
| 펄스 | 0.08–0.14 s | 30초 뒤 꺾여 0.06 까지 | 하한 아래 GPC↓ | 펄스 + |
| 퍼지 | 3.5–6.0 s | 급락 2.5 | 하한 아래 GPC·균일도↑↑ | 퍼지 + |
| 유량 | 175–300 sccm | 125 까지 감소 | 하한 아래 균일도↑↑ | 유량 + |

창 안에서는 지표가 완만하게(버튼 효과가 보일 정도), 창 밖에서는 가파르게 움직인다. 노브 칸: 큰 숫자·선 = 실제값(파랑 = 창 안,
주황 = 한계 15% 안쪽, 빨강 = 창 밖), 회색 점선 = 설정값, 초록 띠 = 정상 범위. 감지 함수는 그대로 통과(오경보 0, 폐루프 120/120).
`sim_v2/model.py`·`design.html` 은 창 도입 전 설계안이다.
