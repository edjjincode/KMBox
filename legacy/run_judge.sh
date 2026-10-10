#!/bin/bash
# 이상 8종 판단 검증. A(정답 값, 몇 초) → 보드 → 누가 보드를 열면 B(VLM, 8개 동시) 시작
#   ./run_judge.sh                → http://127.0.0.1:8765 (SSH -L 8765:127.0.0.1:8765)
set -u
cd "$(dirname "$0")"
PY=../ald-vlm-agent/.venv/bin/python
D=${1:-results/judge_$(date +%m%d_%H%M)}; mkdir -p "$D"
FAULTS="normal ramp step knee oscil spike frozen diverge"
for f in $FAULTS; do for m in raw line; do
  [ -f "$D/${f}_$m/summary.json" ] || $PY -m reader.episode --fault $f --mode $m --out "$D/${f}_$m" > "$D/${f}_$m.log" 2>&1 &
done; done; wait
$PY -m reader.board "$D" --port 8765 > "$D/board.log" 2>&1 &
echo "보드: http://127.0.0.1:8765 — 열면 B 시작"
until [ -f "$D/viewer_seen" ]; do sleep 1; done
for f in $FAULTS; do
  $PY -m reader.episode --fault $f --mode vlm --out "$D/${f}_vlm" > "$D/${f}_vlm.log" 2>&1 &
done; wait
echo "B 끝. 보드는 계속 떠 있다 (board.log)"
