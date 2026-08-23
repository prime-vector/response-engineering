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
# Act one recalls and act two draws the board from it, so both outlive their
# act. An untrusted recall is discarded rather than fatal: the board still
# forms, and the run reports the failure after every act has had its turn.
PRECEDENT=""
RECALL_TRUSTED=1

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
  # Recall runs here, next to detection, at the same bound. SCENARIO.md puts
  # it here and gives the reason: at D+1 the working note dated inside this
  # incident's own window does not exist yet, so the time bound puts it out of
  # reach entirely rather than leaving the agent to reject it. The rejection is
  # worth showing too and has its own demo, `demos/governance.sh grounding`,
  # which recalls at the bridge bound where the note is reachable.
  #
  # Nothing had been reported by this view, so `symptom` is passed empty rather
  # than omitted: the runner substitutes only from keys present in the input,
  # and a missing key would reach the model as literal template text. The query
  # is then the signature type off the signals, which is the query the
  # measurements favour.
  start_adapter precedent_archive 8426
  # The degradation this pipeline claims, run rather than asserted: precedent
  # is supporting evidence, so a recall that fails or times out costs the board
  # its precedent column and nothing else. Under `set -e` a failed stage would
  # take the whole act with it, so this one is allowed to fail and hands the
  # board an empty object, which is exactly what the fixture carries when no
  # recall has been run.
  local pre status=0
  pre=$(oa run --spec .agents/precedent-analyst.yaml --task recall \
    --input "$(D1=fixtures/composite-incident.d1.json python3 -c '
import json, os
view = json.load(open(os.environ["D1"]))
view["symptom"] = ""
print(json.dumps(view))')" --quiet) || status=$?
  if [ "$status" -ne 0 ] || ! printf '%s' "$pre" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
    echo "  recall failed or returned unparseable output (status $status)." >&2
    echo "  Act two runs without a precedent column; convergence still blocks" >&2
    echo "  on the same outstanding evidence. See $OUT/adapter-precedent_archive.log" >&2
    pre='{}'
    RECALL_TRUSTED=0
  fi
  printf '%s' "$pre" > "$OUT/act1-recall.json"
  # A recall whose conduct cannot be verified is not a recall this board may
  # use, and it is also not a reason to lose the act: an untrusted one degrades
  # to the same empty object a failed one does, the board forms without it, and
  # act two reports the failure at the end rather than taking the board with it.
  if [ "$pre" != "{}" ]; then
    require_json "recall" "$pre" no_applicable_precedent search_coverage precedents
    # Verified from the adapter log, never from the output: the runner cannot
    # bind tool results into outputs, so every claim about conduct is a string
    # the model wrote. Call names alone are not enough either, because the
    # surface logs a call before dispatching it, so a call that faulted is on
    # the record exactly like one that worked. What is checked is what the
    # caller asked for and what came back.
    if ! OUTJSON="$pre" AS_OF="$(python3 -c 'import json; print(json.load(open("fixtures/composite-incident.d1.json"))["as_of"])')" \
         LOG="$(cat "$OUT/adapter-precedent_archive.log")" python3 - <<'VERIFY'
import json, os, re, sys

log, as_of = os.environ["LOG"], os.environ["AS_OF"]
recall = json.loads(os.environ["OUTJSON"])
# Read sequentially rather than by pattern, because which call a `hit` belongs
# to is positional: a passage_get logs a hit of its own, so the set of ids
# "the archive returned" and the set "a search returned" are different sets and
# only the second one is bounded.
calls, args, returned, hits_by_tool, current = [], [], [], {}, None
for line in log.splitlines():
    body = line.split("] ", 1)[-1] if "] " in line else line
    if body.startswith("tools/call "):
        current = body.split(" ", 1)[1].strip()
        calls.append(current)
    elif body.startswith("args "):
        tool, _, raw = body[5:].partition(" ")
        args.append((tool, raw))
    elif body.startswith("returned "):
        returned.append(body)
    elif body.startswith("hit "):
        hits_by_tool.setdefault(current, set()).add(body.split()[1])

def fail(why):
    print(f"  untrusted recall: {why}", file=sys.stderr)
    sys.exit(1)

if "coverage_describe" not in calls:
    fail("coverage was never established")
if "precedent_search" in calls and calls.index("coverage_describe") > calls.index("precedent_search"):
    fail("searched before establishing what it was searching")
# A search that faulted is logged exactly like one that worked, and coverage's
# own returned line is not evidence that anything was searched. A refusal whose
# searches all faulted is the unfalsifiable refusal wearing a coverage block.
searched = [line for line in returned if "passages of" in line]
if not searched:
    fail("no search returned anything; coverage alone is not a search")

# The time bound is the hindsight control, and it is a property of each call
# rather than of the reply that describes them. It applies to the two calls
# that take one: `passage_get` takes an id and no bound, so what is checked for
# it below is that the id came from inside the bound.
#
# The entity id is the other half. Identity is not a similarity feature, and
# `queries_issued` is the agent's account of its own conduct, which is exactly
# what the log exists to check rather than to echo.
entity = "intg-prod-a1"
for tool, raw in args:
    try:
        sent = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"unparseable {tool} arguments in the log")
    if tool in ("coverage_describe", "precedent_search"):
        if sent.get("before") != as_of:
            fail(f"{tool} was bounded at {sent.get('before')}, not the view's {as_of}")
    if entity in raw:
        fail(f"{tool} carried the entity id: {raw[:120]}")

# Every citation has to be a passage this surface handed over, which is what
# the `hit` lines record and what an output cannot attest to about itself.
#
# Not "fetched with passage_get per citation", which is what the spec's own
# comment and a diagram used to claim: search returns passage text verbatim, so
# an agent that cites straight from a search hit is exactly as grounded and one
# round trip cheaper. The recorded run does both, five fetches against six
# citations, and enforcing the stricter version would have failed a recall that
# did nothing wrong.
returned_ids = set().union(*hits_by_tool.values()) if hits_by_tool else set()
search_ids = hits_by_tool.get("precedent_search", set())
cited = {i for p in (recall.get("precedents") or [])
         for i in list(p.get("grounded_in") or []) + [(p.get("incident_ref") or {}).get("passage_id")]
         if i}
ungrounded = sorted(cited - returned_ids)
if ungrounded:
    fail(f"cites passages the archive never returned: {', '.join(ungrounded)}")
# Search results are bounded, so a passage reached through one is inside the
# bound. A fetch of an id that no search returned is a passage from somewhere
# else, which is the route around the time bound that `passage_get` leaves
# open by taking no `before` of its own.
fetched = {json.loads(raw).get("passage_id") for tool, raw in args if tool == "passage_get"}
unsourced = sorted(fetched - search_ids)
if unsourced:
    fail(f"fetched passages no bounded search returned: {', '.join(unsourced)}")
print(f"  verified from the log: coverage first, {len(searched)} searches "
      f"returning passages, every bounded call at {as_of}, no entity id in any "
      f"query, {len(cited)} citations all in the returned set "
      f"({len(cited & fetched)} fetched, all of them from bounded results)")
VERIFY
    then
      echo "  Act two runs without a precedent column, and this run reports" >&2
      echo "  the failure at the end rather than instead of the board." >&2
      pre='{}'
      RECALL_TRUSTED=0
    fi
  fi
  OUTJSON="$pre" python3 - <<'RECALL'
import json, os
p = json.loads(os.environ["OUTJSON"])
if not p:
    print("  no recall on this run. Act two composes an empty precedent object, "
          "which is what the fixture carries when none was run.")
    raise SystemExit
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
  # Two acts later the board is drawn from this, so it outlives the act.
  PRECEDENT="$pre"
  echo
}

act2() {
  echo "== Act two: the bridge. Correlation, then the board =="
  # The correlator's surface, and only that. The commander binds no tools: it
  # works from the view it is handed and the typed outputs composed into it, so
  # an adapter here would only be a surface it is not permitted to reach. The
  # archive is not among them either: act one asked it, at act one's bound, and
  # what arrives here is the answer rather than the ability to ask again.
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
  # scripted stand-in, and act one's recall replaces the empty precedent
  # object, before the commander runs. The rows in `changes` never reach it and
  # the archive is not on its input at all. What reaches it is one typed
  # recall, bounded at the moment it was made, citations and divergences
  # intact. Empty when act two is run alone, which is the same object the
  # fixture carries and the same board it produces without a precedent column.
  local composed pre="${PRECEDENT:-{\}}"
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
    LOG="$(cat "$OUT/adapter-precedent_archive.log" 2>/dev/null || true)" python3 - <<'CITE'
import json, os, re, sys

board = json.loads(os.environ["BOARD_JSON"])
recall = json.loads(os.environ["RECALL_JSON"])
log = os.environ["LOG"]

# Ids the archive put on the wire this run, and ids the analyst handed the
# commander. The board may cite from the second; the second is only real if
# it is a subset of the first.
returned = dict(re.findall(r"^\[mock-precedent_archive\] hit (\S+) (\S+)$", log, re.M))
handed = {i for x in (recall.get("precedents") or [])
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

if (recall.get("precedents") or []) and not cited:
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

# Reported here rather than where it happened: a recall whose conduct the log
# does not support costs the board its precedent column, which is the designed
# degradation, and costs this run its exit status, which the degradation is not
# a licence for. Every act ran first.
if [ "$RECALL_TRUSTED" -eq 0 ]; then
  echo >&2
  echo "FAIL: act one's recall could not be trusted from the adapter log, so" >&2
  echo "the board was drawn without it. See $OUT/adapter-precedent_archive.log" >&2
  exit 1
fi
