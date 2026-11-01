#!/bin/bash
# run_test.sh — end-to-end worker test on synthetic passes, in a scratch dir.
#   worker/tests/run_test.sh [scratch-dir]
# Needs gr-satellites; uses the installed venv python if present.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
T=${1:-$(mktemp -d)}
PY=/opt/satnogs-worker/venv/bin/python; [[ -x $PY ]] || PY=python3
mkdir -p "$T"
cat > "$T/worker.yml" <<EOT
satellites:
  98492: { decoder: $HERE/TESTSAT.yml, parser: "satnogs:Ax25frames" }
  99001: { decoder: $HERE/TESTSAT.yml }
EOT
python3 "$HERE/make_test_obs.py" "$T" 1001 --snr-db 15 9 6 3
python3 "$HERE/make_test_obs.py" "$T" 1004 --flowgraph satnogs_bpsk.py --rate 76800 --true-baud 9570 --norad 99001 --snr-db 15 9 6 3 --seed 2
python3 "$HERE/make_test_obs.py" "$T" 1002 --empty --seconds 60
python3 "$HERE/make_test_obs.py" "$T" 1003 --snr-db 1 --seed 5
$PY "$HERE/../satnogs-worker" --base "$T" run
$PY "$HERE/../satnogs-worker" --base "$T" status
echo "expect: 1001 decoded (baud ~+0 ppm), 1004 decoded (baud ~9570, -3125 ppm warning), 1002 empty, 1003 no_frames; scratch: $T"
