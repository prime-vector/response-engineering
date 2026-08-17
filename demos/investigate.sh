#!/usr/bin/env bash
# The three-act investigation pipeline, composed as dataflow rather than
# narrated: the correlator's typed output becomes the commander's correlation
# input, and the commander's live board becomes the Scribe's timeline input.
# No agent consumes another's evidence surface, only its typed output.
#
#   demos/investigate.sh act1   # D+1: recurrence detected in the problem feed
#   demos/investigate.sh act2   # bridge: correlate, then assess on the live correlation
#   demos/investigate.sh act3   # Scribe files the timeline from the act-two board
#   demos/investigate.sh all    # default: the full pipeline, composed
#
# Acts compose within one invocation: act3 consumes the board act2 just
# produced, or an empty board when run alone. The governance blocks
# (sandbox, contract, attribution) live in demos/governance.sh.
#
# Each act is a live model run against the real specs and the mock adapters.
# Requires ANTHROPIC_API_KEY and the provider patch from patches/ (see
# README). Every stage fails closed on unparseable output: OAS 1.5.1 exits
# zero on a truncated JSON output with validation silently skipped, this
# script does not. Tool-use claims are verified from the adapter log, never
# from the output: a success flag proves nothing on its own.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-all}"
case "$MODE" in act1|act2|act3|all) ;; *)
  echo "Usage: demos/investigate.sh [act1|act2|act3|all]" >&2; exit 2 ;;
esac

: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY first; every act is a live run.}"

# The runner skips contract validation with only a warning when the
# behavioural-contracts extra is missing (a pipx upgrade drops it). Every
# stage here claims contract-valid output, so that degradation fails closed.
OA_PY="$(sed -n '1s/^#! *//p' "$(command -v oa)")"
if [ -x "$OA_PY" ]; then
  "$OA_PY" -c 'import sys; from oas_cli.runner import CONTRACTS_ENABLED; sys.exit(0 if CONTRACTS_ENABLED else 1)' || {
    echo "behavioural-contracts is missing from oa's environment: the runner" >&2
    echo "would skip contract validation with only a warning. Reinstall it:" >&2
    echo "  pipx runpip open-agent-spec install behavioural-contracts" >&2
    exit 1
  }
else
  echo "warning: cannot locate oa's interpreter; contract validation unverified." >&2
fi

OUT="$(mktemp -d "${TMPDIR:-/tmp}/investigate.XXXXXX")"
BOARD=""

declare -A ADAPTER_PID=()
cleanup() { for p in ${ADAPTER_PID[@]+"${ADAPTER_PID[@]}"}; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

start_adapter() { # surface port [extra adapter args...]
  local surface="$1" port="$2"; shift 2
  if port_in_use "$port"; then
    echo "Port $port is already in use. Stop whatever serves it first: this" >&2
    echo "script must control which fixture view the $surface adapter serves." >&2
    exit 1
  fi
  # Unbuffered, because the adapter log is the audit trail this script
  # checks tool-use claims against; a buffered line dies with the process.
  python3 -u mock/adapter.py --surface "$surface" "$@" \
    > "$OUT/adapter-$surface.log" 2>&1 &
  ADAPTER_PID[$surface]=$!
  for _ in $(seq 40); do
    if port_in_use "$port"; then return 0; fi
    sleep 0.25
  done
  echo "Mock $surface adapter did not come up on port $port." >&2
  exit 1
}

stop_adapter() { # surface port
  local pid="${ADAPTER_PID[$1]:-}"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  unset "ADAPTER_PID[$1]"
  for _ in $(seq 40); do
    if ! port_in_use "$2"; then return 0; fi
    sleep 0.25
  done
  echo "Port $2 did not free after stopping the $1 adapter." >&2
  exit 1
}

require_json() { # stage_name json_text [required_top_level_key...]
  STAGE="$1" TEXT="$2" python3 - "${@:3}" <<'PY'
import json, os, sys
stage, text = os.environ["STAGE"], os.environ["TEXT"]
try:
    obj = json.loads(text)
except json.JSONDecodeError as exc:
    # The fail-closed check the runner does not do: a truncated json-task
    # output exits 0 upstream with schema and contract validation skipped.
    sys.exit(f"FAIL: {stage} returned unparseable output ({exc}); likely "
             f"max_tokens truncation. First 300 chars:\n{text[:300]}")
missing = [k for k in sys.argv[1:] if k not in obj]
if missing:
    sys.exit(f"FAIL: {stage} output is missing required keys: {missing}")
PY
}

act1() {
  echo "== Act one: D+1. Recurrence in a feed nobody reads =="
  start_adapter telemetry 8422 --fixture fixtures/composite-incident.d1.json
  local out
  out=$(oa run --spec .agents/telemetry-analyst.yaml --task detect \
    --input "$(cat fixtures/composite-incident.d1.json)" --quiet)
  require_json "detect" "$out" recurrence_detected recurrences findings
  printf '%s' "$out" > "$OUT/act1-detect.json"
  OUTJSON="$out" python3 - <<'PY'
import json, os
r = json.loads(os.environ["OUTJSON"])
print(f"  recurrence_detected: {r['recurrence_detected']}")
for rec in r["recurrences"]:
    print(f"  {rec['signature']}: {rec['occurrence_count']} occurrences, "
          f"{rec['acknowledged_count']} acknowledged")
for f in r.get("findings", []):
    print(f"  [{f['confidence']}] {f['statement']}")
PY
  stop_adapter telemetry 8422
  echo
}

act2() {
  echo "== Act two: the bridge. Correlation first, then the board =="
  start_adapter telemetry 8422
  start_adapter change_registry 8423
  local cor
  cor=$(oa run --spec .agents/change-correlator.yaml --task correlate \
    --input "$(cat fixtures/composite-incident.json)" --quiet)
  require_json "correlate" "$cor" onset_at correlation_found correlations registry_caveats
  printf '%s' "$cor" > "$OUT/act2-correlate.json"
  OUTJSON="$cor" python3 - <<'PY'
import json, os
c = json.loads(os.environ["OUTJSON"])
print(f"  onset: {c['onset_at']}, correlations: {len(c['correlations'])}")
for x in c["correlations"]:
    print(f"  [{x['confidence']}] {x.get('offset_from_onset', '?')}: "
          f"{x['statement']}")
print(f"  registry caveats: {len(c['registry_caveats'])}")
PY
  # The handoff itself: the correlator's typed output replaces the fixture's
  # scripted stand-in before the commander runs. The rows in `changes` never
  # reach it.
  local composed
  composed=$(COR="$cor" python3 -c '
import json, os
view = json.load(open("fixtures/composite-incident.json"))
view["correlation"] = json.loads(os.environ["COR"])
print(json.dumps(view))')
  BOARD=$(oa run --spec .agents/incident-commander.yaml --task assess \
    --input "$composed" --quiet)
  require_json "assess" "$BOARD" incident_state hypotheses blocking_evidence convergence_allowed
  printf '%s' "$BOARD" > "$OUT/act2-board.json"
  OUTJSON="$BOARD" python3 - <<'PY'
import json, os
b = json.loads(os.environ["OUTJSON"])
print(f"  incident_state: {b['incident_state']}")
for h in b["hypotheses"]:
    flag = " [third party]" if h.get("third_party_named") else ""
    print(f"  [{h['confidence']}]{flag} {h['statement']}")
guard = b.get("attribution_guard") or {}
if guard.get("triggered"):
    print(f"  attribution guard: fired on {guard.get('party')}")
print(f"  convergence_allowed: {b['convergence_allowed']}"
      + (f" ({b.get('convergence_block_reason')})"
         if not b["convergence_allowed"] else ""))
for e in b["blocking_evidence"]:
    if e.get("still_outstanding", True):
        print(f"  outstanding: {e['description']}")
PY
  stop_adapter change_registry 8423
  echo
}

act3() {
  echo "== Act three: the Scribe files the timeline from the live board =="
  if [ -z "$BOARD" ]; then
    echo "   (no act-two board in this invocation; filing with an empty board)"
  fi
  start_adapter incident_record 8425
  local board_json="$BOARD" input out
  [ -z "$board_json" ] && board_json="{}"
  input=$(BOARD_JSON="$board_json" python3 -c '
import json, os
view = json.load(open("fixtures/composite-incident.json"))
view.update(board=json.loads(os.environ["BOARD_JSON"]), mitigation_attempts=[])
print(json.dumps(view))')
  out=$(oa run --spec .agents/scribe.yaml --task timeline --input "$input" --quiet)
  require_json "timeline" "$out" entries gaps record_updated
  printf '%s' "$out" > "$OUT/act3-timeline.json"
  # Self-attestation check: the output's record_updated claim counts for
  # nothing unless the adapter actually logged the sink call.
  if ! grep -q "tools/call record_" "$OUT/adapter-incident_record.log"; then
    echo "FAIL: the timeline claims filing but the record sink logged no" >&2
    echo "tools/call. Output self-attestation; see $OUT/adapter-incident_record.log" >&2
    return 1
  fi
  OUTJSON="$out" python3 - <<'PY'
import json, os
t = json.loads(os.environ["OUTJSON"])
print(f"  entries: {len(t['entries'])}, gaps: {len(t['gaps'])}")
print(f"  record_updated: {t['record_updated']} "
      "(verified against the adapter log, not the output)")
PY
  stop_adapter incident_record 8425
  echo
}

case "$MODE" in
  act1) act1 ;;
  act2) act2 ;;
  act3) act3 ;;
  all)  act1; act2; act3 ;;
esac

echo "Pipeline outputs and adapter logs: $OUT"
