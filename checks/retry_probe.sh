#!/usr/bin/env bash
# Drive demos/retry.sh against a stub provider: does it retry the transport,
# and only the transport?
#
#   checks/retry_probe.sh
#
# Costs nothing and needs no key, which is the point. The retry exists because
# a real transport failure is rare, expensive and impossible to schedule, so
# the behaviour that matters most is the behaviour hardest to observe live: a
# retry that fires on a contract rejection would silently re-run the very
# thing three governance demos exist to demonstrate, and nothing in a passing
# demo would say so.
set -uo pipefail
cd "$(dirname "$0")/.."

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

OA_MARKS="$WORK/marks"
OA_LOG_GLOB="$WORK/adapter-*.log"
. demos/retry.sh

# The stub stands in for `oa`. It appends to a call log, writes whatever the
# scenario asked for on the attempt it is on, and pretends to be an adapter by
# growing a surface log, so the per-attempt window has something to narrow.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/oa" <<'STUB'
#!/usr/bin/env bash
attempt=$(( $(cat "$WORK/attempts" 2>/dev/null || echo 0) + 1 ))
echo "$attempt" > "$WORK/attempts"
echo "hit passage-attempt-$attempt archive://doc#$attempt" >> "$WORK/adapter-precedent_archive.log"
case "$(sed -n "${attempt}p" "$WORK/script")" in
  transport)
    echo "PROVIDER_ERROR" >&2
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic request failed: Remote end closed connection without response"}' >&2
    exit 1 ;;
  contract)
    echo '{"code": "OUTPUT_SCHEMA_ERROR", "error": "falsifying_test is a required property"}' >&2
    exit 1 ;;
  cutstream)
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic stream ended without message_stop after 3 content block(s): the generation was cut in transit and what arrived is partial"}' >&2
    exit 1 ;;
  streamerror)
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic stream error: overloaded_error: Overloaded"}' >&2
    exit 1 ;;
  badevent)
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic stream: unparseable event (Unterminated string): {\"type\": \"content_bl"}' >&2
    exit 1 ;;
  badbytes)
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic stream: undecodable bytes on the wire (invalid start byte)"}' >&2
    exit 1 ;;
  http5xx)
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic HTTP 529: {\"type\":\"overloaded_error\"}"}' >&2
    exit 1 ;;
  nokey)
    echo '{"code": "PROVIDER_ERROR", "error": "Anthropic API key not set - export ANTHROPIC_API_KEY"}' >&2
    exit 1 ;;
  adaptertimeout)
    echo '{"code": "TOOL_ERROR", "error": "precedent_search timed out after 30s"}' >&2
    exit 1 ;;
  *)
    echo "{\"ok\": true, \"attempt\": $attempt}" ;;
esac
STUB
chmod +x "$WORK/bin/oa"
export WORK
PATH="$WORK/bin:$PATH"

FAILURES=0
check() { # description expected actual
  if [ "$2" = "$3" ]; then
    echo "  ok   $1"
  else
    echo "  FAIL $1: expected [$2], got [$3]"
    FAILURES=$(( FAILURES + 1 ))
  fi
}

scenario() { # newline-separated outcomes, one per attempt
  printf '%s\n' "$1" > "$WORK/script"
  : > "$WORK/attempts"
  : > "$WORK/adapter-precedent_archive.log"
}

echo "a transport failure is retried once:"
scenario "transport
ok"
out=$(oa_run --task assess 2>"$WORK/err"); status=$?
check "the run succeeds" 0 "$status"
check "two attempts were made" 2 "$(cat "$WORK/attempts")"
check "the output is the surviving attempt's" '{"ok": true, "attempt": 2}' "$out"
check "the retry announces itself" 1 \
  "$(grep -c 'transport failure above' "$WORK/err")"
check "the abandoned attempt's error is prefixed out of the way" 0 \
  "$(grep -c '^{' "$WORK/err")"
# The window is what a grounding check reads. Attempt one's hit must not be in
# it, or a citation the discarded attempt was handed would pass as grounded.
window=$(attempt_log "$WORK/adapter-precedent_archive.log")
check "the log window holds only the surviving attempt's hits" \
  "hit passage-attempt-2 archive://doc#2" "$window"

echo
echo "every signature the streamed provider can fail with is retried:"
# One case per alternative in OA_RETRY_RE. Without these the regex could lose
# every stream-specific branch and the probe would still pass on the plain
# request failure above, leaving the shipped streaming failure path unverified.
for shape in cutstream streamerror badevent badbytes http5xx; do
  scenario "$shape
ok"
  out=$(oa_run --task assess 2>"$WORK/err"); status=$?
  check "$shape is retried and succeeds" 0 "$status"
  check "$shape made two attempts" 2 "$(cat "$WORK/attempts")"
done

echo
echo "a control firing is not retried:"
scenario "contract
ok"
out=$(oa_run --task assess 2>"$WORK/err"); status=$?
check "the run fails" 1 "$status"
check "only one attempt was made" 1 "$(cat "$WORK/attempts")"
check "the structured error reaches the caller intact" 1 \
  "$(grep -c '^{"code": "OUTPUT_SCHEMA_ERROR"' "$WORK/err")"

echo
echo "a PROVIDER_ERROR that is not the transport is not retried:"
scenario "nokey
ok"
out=$(oa_run --task assess 2>"$WORK/err"); status=$?
check "the run fails" 1 "$status"
check "only one attempt was made" 1 "$(cat "$WORK/attempts")"

echo
echo "the word timeout somewhere else on stderr is not the transport:"
scenario "adaptertimeout
ok"
out=$(oa_run --task assess 2>"$WORK/err"); status=$?
check "the run fails" 1 "$status"
check "only one attempt was made" 1 "$(cat "$WORK/attempts")"

echo
echo "the retry is one, not a loop:"
scenario "transport
transport
ok"
out=$(oa_run --task assess 2>"$WORK/err"); status=$?
check "the run fails" 1 "$status"
check "exactly two attempts were made" 2 "$(cat "$WORK/attempts")"
check "the second failure reaches the caller intact" 1 \
  "$(grep -c '^{"code": "PROVIDER_ERROR"' "$WORK/err")"

echo
echo "a stage that writes is not retried at all:"
# The retry is safe only where the stage's one effect is its output. The
# Scribe files to the incident sink with a tool call, so a generation lost
# after the write would be filed twice by a second attempt, and the log
# re-marking would hide the first call from the check that verifies what was
# filed. Same transport failure as the first case above, opposite behaviour.
scenario "transport
ok"
out=$(oa_run_once --task timeline 2>"$WORK/err"); status=$?
check "the run fails rather than filing twice" 1 "$status"
check "only one attempt was made" 1 "$(cat "$WORK/attempts")"
check "it says why it did not retry" 1 \
  "$(grep -c 'may' "$WORK/err")"

echo
echo "a clean run is unchanged:"
scenario "ok"
out=$(oa_run --task assess 2>"$WORK/err"); status=$?
check "the run succeeds" 0 "$status"
check "one attempt" 1 "$(cat "$WORK/attempts")"
check "nothing is written to stderr" 0 "$(wc -c < "$WORK/err" | tr -d ' ')"
check "the window is the whole of this run's log" \
  "hit passage-attempt-1 archive://doc#1" \
  "$(attempt_log "$WORK/adapter-precedent_archive.log")"

echo
if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES check(s) failed." >&2
  exit 1
fi
echo "The retry fires on the transport and nowhere else."
