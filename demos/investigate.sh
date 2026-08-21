#!/usr/bin/env bash
# The three-act investigation pipeline, composed as dataflow rather than
# narrated: the correlator's typed output becomes the commander's correlation
# input, the analyst's typed recall becomes its precedent input, and the
# commander's live board becomes the Scribe's timeline input. No agent
# consumes another's evidence surface, only its typed output.
#
# Precedent enters the board as supporting evidence and cannot leave it as
# deciding evidence: the commander's contract closes blocking_evidence
# against a citation and blocks convergence while any item is outstanding, so
# act two asserts what the precedent did rather than that it arrived.
#
#   demos/investigate.sh act1   # D+1: recurrence detected in the problem feed
#   demos/investigate.sh act2   # bridge: correlate and recall, then assess on both
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
  echo "== Act two: the bridge. Correlation and recall first, then the board =="
  # The two collecting agents' surfaces, one at a time. The commander binds no
  # tools: it works from the view it is handed and the typed outputs composed
  # into it, so an adapter on 8422 here would only be a surface it is not
  # permitted to reach, and 8426 is the archive the analyst owns rather than
  # something the board may go and query for itself.
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
  stop_adapter change_registry 8423
  # Recall, at the same bound as the view the board will reason over, because
  # what act two has to demonstrate is a property of the board. Recall at the
  # D+1 bound works and is covered by eval case a02; it would have the board
  # cite the archive as it stood a fortnight earlier, and it drops DRAFT-2601,
  # whose being returned and not cited is the archive's strongest live moment
  # and exists at this bound only.
  start_adapter precedent_archive 8426
  local pre
  pre=$(oa run --spec .agents/precedent-analyst.yaml --task recall \
    --input "$(cat fixtures/composite-incident.json)" --quiet)
  require_json "recall" "$pre" no_applicable_precedent search_coverage precedents
  printf '%s' "$pre" > "$OUT/act2-recall.json"
  # Tool-use claims are verified from the adapter log, never from the output:
  # the runner cannot bind tool results into outputs, so a passage id in a
  # citation is a string the model wrote either way.
  for tool in coverage_describe precedent_search; do
    if ! grep -q "tools/call $tool" "$OUT/adapter-precedent_archive.log"; then
      echo "FAIL: recall reported without calling $tool. Output" >&2
      echo "self-attestation; see $OUT/adapter-precedent_archive.log" >&2
      return 1
    fi
  done
  OUTJSON="$pre" python3 - <<'RECALL'
import json, os
p = json.loads(os.environ["OUTJSON"])
cov = p.get("search_coverage") or {}
print(f"  queries: {len(cov.get('queries_issued') or [])}, archive at this "
      f"bound: {cov.get('date_range')}")
if p["no_applicable_precedent"]:
    print("  no applicable precedent, with its coverage. The board gets no "
          "precedent column and blocks on the same evidence either way.")
for x in p["precedents"]:
    ref = x.get("incident_ref") or {}
    print(f"  [{x['confidence']}] {ref.get('source_uri')}, "
          f"{x['applicability']}, grounded in "
          f"{len(x.get('grounded_in') or [])} passages")
    print(f"    divergence: {(x.get('divergence') or '')[:130]}")
RECALL
  stop_adapter precedent_archive 8426
  # The handoff itself: the correlator's typed output replaces the fixture's
  # scripted stand-in, and the analyst's replaces the empty precedent object,
  # before the commander runs. The rows in `changes` never reach it and the
  # archive is not on its input at all. What reaches it is one typed recall,
  # citations and divergences intact.
  local composed
  composed=$(COR="$cor" PRE="$pre" python3 -c '
import json, os
view = json.load(open("fixtures/composite-incident.json"))
view["correlation"] = json.loads(os.environ["COR"])
view["precedent"] = json.loads(os.environ["PRE"])
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
    if e["still_outstanding"]:
        print(f"  outstanding: {e['description']}")
PY
  # What the composition is for, checked rather than narrated. A cited
  # passage id has to be one the analyst handed over and one the archive
  # actually returned, and the board has to still be blocked on the evidence
  # nobody has collected. Precedent cannot appear anywhere else on the board:
  # blocking_evidence is closed against it in the contract, so this checks
  # what precedent did, not where it went.
  BOARD_JSON="$BOARD" RECALL_JSON="$pre" \
    LOG="$(cat "$OUT/adapter-precedent_archive.log")" python3 - <<'CITE'
import json, os, re, sys

board = json.loads(os.environ["BOARD_JSON"])
recall = json.loads(os.environ["RECALL_JSON"])
log = os.environ["LOG"]

# Ids the archive put on the wire this run, and ids the analyst handed the
# commander. The board may cite from the second; the second is only real if
# it is a subset of the first.
returned = dict(re.findall(r"^\[mock-precedent_archive\] hit (\S+) (\S+)$", log, re.M))
handed = {i for x in recall["precedents"]
          for i in list(x.get("grounded_in") or [])
                 + [(x.get("incident_ref") or {}).get("passage_id")] if i}

cited = {i for h in board["hypotheses"] for i in (h.get("precedent_cited") or [])}
invented = sorted(cited - handed)
if invented:
    sys.exit("FAIL: the board cites passage ids the analyst never handed it: "
             + ", ".join(invented))
unreturned = sorted(cited - set(returned))
if unreturned:
    sys.exit("FAIL: the board cites passage ids the archive never returned: "
             + ", ".join(unreturned))

# A cited id proves the archive returned it. It does not prove the hypothesis
# is about the document that id belongs to: a claim naming one record while
# citing a passage of another passes a membership check, which is a mismatch
# the judgement scorer has already been caught by. Resolve every id to its
# document through the adapter log, never through a uri the model wrote, and
# hold the prose to it.
record = re.compile(r"\b(?:INC|DRAFT)-\d{4}\b")
for h in board["hypotheses"]:
    ids = h.get("precedent_cited") or []
    if not ids:
        continue
    docs = {returned[i].split("#")[0] for i in ids}
    named = set(record.findall(json.dumps(h)))
    astray = sorted(n for n in named if not any(u.endswith(n) for u in docs))
    if astray:
        sys.exit(f"FAIL: a hypothesis names {', '.join(astray)} and cites "
                 f"passages of {', '.join(sorted(docs))}:\n"
                 + json.dumps(h, indent=2))

if recall["precedents"] and not cited:
    sys.exit("FAIL: precedent was handed over and no hypothesis rests on it. "
             "Either every precedent was judged not to bear on any hypothesis, "
             "which the board should say in a hypothesis it argues against, or "
             "the citation was dropped in the handoff:\n"
             + json.dumps(board["hypotheses"], indent=2))

outstanding = [e for e in board["blocking_evidence"] if e["still_outstanding"]]
if outstanding and board["convergence_allowed"]:
    sys.exit("FAIL: convergence allowed with deciding evidence outstanding.")
for h in board["hypotheses"]:
    if h.get("precedent_cited") and h["confidence"] == "confirmed":
        sys.exit("FAIL: a hypothesis resting on precedent reached confirmed.")

for h in board["hypotheses"]:
    for i in h.get("precedent_cited") or []:
        print(f"  {h['confidence']}: cites {i}, which the archive returned "
              f"this run from {returned[i]}")
print(f"  precedent supports {sum(1 for h in board['hypotheses'] if h.get('precedent_cited'))} "
      f"of {len(board['hypotheses'])} hypotheses and settles none of them: "
      f"{len(outstanding)} item(s) still outstanding, convergence "
      f"{'blocked' if not board['convergence_allowed'] else 'ALLOWED'}.")
CITE
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
