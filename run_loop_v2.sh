#!/bin/bash
# v2 VLM 폐루프: 보드를 띄우고, 누가 열면 이상 6종을 가상 모니터 6개에서 동시에 돌린다
#   ./run_loop_v2.sh [결과폴더] [read|vlm]   read = VLM 판독 + 좌표표로 조치 제출, vlm = 버튼 grounding 까지 VLM   → http://127.0.0.1:8765 (SSH -L 8765:127.0.0.1:8765)
set -u
cd "$(dirname "$0")"
PY=.venv/bin/python
MODE=${2:-read}
D=${1:-results/loop_v2/${MODE}_$(date +%m%d_%H%M)}; mkdir -p "$D"
FAULTS=${FAULTS:-normal temp purge pulse press flow}
for f in $FAULTS; do mkdir -p "$D/$f"; done          # 보드는 폴더가 있는 이상만 보여 준다
$PY -m reader.board_v2 "$D" --port 8765 > "$D/board.log" 2>&1 &
echo "보드: http://127.0.0.1:8765 — 열면 시작 ($D)"
until [ -f "$D/viewer_seen" ]; do sleep 1; done
for f in $FAULTS; do
  $PY -m reader.loop_v2 --fault $f --mode $MODE --pre ${PRE:-10} --out "$D/$f" > "$D/$f.log" 2>&1 &
done; wait
echo "폐루프 끝. 보드는 계속 떠 있다."
