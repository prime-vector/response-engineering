#!/usr/bin/env bash
# The baseline across traced runs, held to checks/agent_traces_slo.yaml, as
# runs/baseline.json and runs/baseline.html. Pass run directories to choose
# which runs count; the default is every traced run under runs/, which
# includes experiments, so a baseline meant as evidence names its runs.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -gt 0 ]; then
  DIRS=("$@")
else
  DIRS=(runs/agent-traces-*/)
fi
FILES=()
for d in "${DIRS[@]}"; do
  d="${d%/}"
  if [ -f "$d/sli.json" ]; then
    FILES+=("$d/sli.json")
  else
    echo "skipping $d: no sli.json (an older run, or one the wrapper never finished)" >&2
  fi
done
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "No runs with sli.json; run demos/traced.sh first." >&2
  exit 1
fi
mkdir -p runs
python3 checks/agent_traces_sli.py --aggregate "${FILES[@]}" --slo checks/agent_traces_slo.yaml -o runs/baseline.json
python3 demos/agent_traces_report.py --baseline runs/baseline.json -o runs/baseline.html
python3 - <<'PY'
import json
s = json.load(open("runs/baseline.json"))["slo"]
print(f"runs/baseline.html: {json.load(open('runs/baseline.json'))['runs']} runs, objectives "
      f"{'all met' if s['met'] else 'not all met'}, {s['unmeasured']} not measurable")
PY
