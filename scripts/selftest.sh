#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

# Pre-flight: a stale hub makes the gate silently lie — either /health answers
# from a hub of unknown state already bound to 8123, or pre-existing LSL
# outlets with the e2e source_ids let e2e readers bind the wrong feed once the
# gate's own hub boots. Nothing should own those streams yet. Abort loudly.
if (exec 3<>/dev/tcp/127.0.0.1/8123) 2>/dev/null; then
  echo "SELFTEST ABORTED — 127.0.0.1:8123 already has a listener (stale hub?)."
  echo "Kill it first, e.g.: pkill -f 'main.py --config tests/e2e_config.yaml'"
  exit 2
fi
"$PY" - <<'EOF' || { echo "SELFTEST ABORTED — pre-existing LSL outlets for the e2e streams (stale hub?)."; exit 2; }
import sys, time
from pylsl import ContinuousResolver
WANTED = {"SimMuse-operator_alpha_01", "SimMuse-operator_bravo_02"}
res = ContinuousResolver()
time.sleep(1.0)
found = sorted({i.source_id() for i in res.results() if i.source_id() in WANTED})
if found:
    sys.exit(f"outlets already live: {found}")
EOF

echo "== IronMind selftest =="
rc=0
"$PY" -m pytest -q "$@" || rc=$?   # trap, don't die: set -e would skip the verdict
if [ $rc -eq 0 ]; then echo "ALL GREEN — demo cannot fail for software reasons."; else echo "SELFTEST FAILED — fix before demo."; fi
exit $rc
