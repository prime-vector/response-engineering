#!/usr/bin/env bash
# Agent traces are a second verdict. The driver's own checks still decide
# whether the demo succeeded, including what was filed or cited.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-all}"
if [ "$#" -gt 0 ]; then shift; fi
EXPECT=()
add_mode() {
  case "$1" in
    sandbox) EXPECT+=(--expect incident-commander:mitigate:none=violation_prevented) ;;
    contract) EXPECT+=(--expect incident-commander:assess:system=nonconformant) ;;
    attribution)
      EXPECT+=(--expect incident-commander:assess:none=conformant
               --expect incident-commander:assess:system=nonconformant) ;;
    grounding)
      EXPECT+=(--expect precedent-analyst:recall:none=conformant
               --expect precedent-analyst:recall:system=nonconformant) ;;
    refusal) EXPECT+=(--expect precedent-analyst:recall:none=conformant) ;;
  esac
}
case "$MODE" in
  investigate)
    DRIVER=demos/investigate.sh
    # Every stage an act runs is named, not only the write: with no
    # expectation the check passes any well-formed file, so a partial export
    # that kept one stage and dropped the rest would otherwise pass.
    ACT1=(--expect telemetry-analyst:detect:none=conformant
          --expect precedent-analyst:recall:none=conformant)
    ACT2=(--expect change-correlator:correlate:none=conformant
          --expect incident-commander:assess:none=conformant)
    ACT3=(--expect scribe:timeline:none=conformant --expect-write scribe:timeline)
    case "${1:-all}" in
      act1) EXPECT+=("${ACT1[@]}") ;;
      act2) EXPECT+=("${ACT2[@]}") ;;
      act3) EXPECT+=("${ACT3[@]}") ;;
      all) EXPECT+=("${ACT1[@]}" "${ACT2[@]}" "${ACT3[@]}") ;;
      *) echo "Usage: demos/traced.sh investigate [act1|act2|act3|all]" >&2; exit 2 ;;
    esac ;;
  sandbox|contract|attribution|grounding|refusal)
    DRIVER=demos/governance.sh
    add_mode "$MODE"
    set -- "$MODE" "$@" ;;
  all)
    DRIVER=demos/governance.sh
    for mode in sandbox contract attribution grounding refusal; do add_mode "$mode"; done
    set -- all "$@" ;;
  *) echo "Usage: demos/traced.sh [investigate [ACT]|sandbox|contract|attribution|grounding|refusal|all]" >&2; exit 2 ;;
esac

mkdir -p runs
# mktemp avoids collisions between starts in the same UTC second.
RUN=$(mktemp -d "runs/agent-traces-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
SINK_PID=""
cleanup() {
  if [ -n "$SINK_PID" ]; then
    kill "$SINK_PID" 2>/dev/null || true
    wait "$SINK_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 demos/agent_traces_sink.py "$RUN/spans.jsonl" --port 0 \
  --ready-file "$RUN/ready" >"$RUN/sink.log" 2>&1 &
SINK_PID=$!
for _ in $(seq 100); do
  [ -s "$RUN/ready" ] && break
  if ! kill -0 "$SINK_PID" 2>/dev/null; then
    cat "$RUN/sink.log" >&2
    exit 1
  fi
  sleep 0.1
done
if [ ! -s "$RUN/ready" ]; then
  echo "Agent traces sink did not become ready: $RUN/sink.log" >&2
  exit 1
fi
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:$(cat "$RUN/ready")"
# A signal-specific endpoint overrides the general endpoint in the exporter.
# Clear inherited remote destinations so the local sink receives these runs.
unset OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf
unset OTEL_EXPORTER_OTLP_HEADERS OTEL_EXPORTER_OTLP_TRACES_HEADERS
DRIVER_STATUS=0
bash "$DRIVER" "$@" || DRIVER_STATUS=$?
# Each oa process exits only after BatchSpanProcessor's shutdown flush. The
# sink closes its file before replying, so driver exit is the flush barrier.
cleanup
SINK_PID=""
CHECK_STATUS=0
python3 checks/agent_traces.py "$RUN/spans.jsonl" "${EXPECT[@]}" || CHECK_STATUS=$?
printf 'Agent traces: %s (driver=%s, check=%s)\n' "$RUN/spans.jsonl" "$DRIVER_STATUS" "$CHECK_STATUS"
if [ "$DRIVER_STATUS" -ne 0 ]; then exit "$DRIVER_STATUS"; fi
exit "$CHECK_STATUS"
