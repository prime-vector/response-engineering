# One retry, and only on the transport. Sourced by both demo drivers.
#
# The provider can lose a long generation in transit: a connection closed
# mid-response, a read timeout, a 5xx, minutes into a request that completed an
# hour earlier, and at the exit status it is indistinguishable from a real
# failure. Streaming in the provider is the fix,
# patches/oas-1.6.0-anthropic-streaming.diff; this covers an unpatched install
# and the connection that drops regardless.
#
# What is never retried is everything the demos exist to show: a contract
# rejection, a schema error, a sandbox block, an output that does not parse.
# Those are the controls working, and three of the governance demos expect a
# run to fail, so a retry there would be retrying the point. The match is
# therefore the transport signature on stderr and nothing else.
#
# The caller sets two variables before sourcing:
#   OA_MARKS     file to record log positions in
#   OA_LOG_GLOB  glob matching the adapter logs, quoted
#
# checks/retry_probe.sh exercises all of this against a stub provider, which
# costs nothing and needs no key.

# Anchored on the provider's own prefixes rather than on the words inside the
# exception. `Anthropic request failed:` is what the provider wraps every
# transport exception in, so it covers a closed connection, a reset, a read
# timeout and an incomplete read without matching the bare word "timeout"
# wherever else it appears on stderr: an adapter that timed out, or a model
# that wrote the word, is not the transport losing a generation. A key that is
# not set raises a ProviderError without that prefix and stays fatal, which is
# right, because retrying it would only spend the wait twice.
OA_RETRY_RE='Anthropic request failed:|Anthropic HTTP 5[0-9][0-9]|Anthropic stream error:|Anthropic stream ended|Anthropic stream: unparseable event'

# Where each adapter log stood before the attempt now running. Tool-use claims
# are checked against the log, and two attempts concatenated are not one
# stage's record: a passage the abandoned attempt was handed would satisfy a
# grounding check about the attempt that actually produced the output.
# Recorded before every attempt, so a stage that did not retry reads exactly as
# it did before this existed.
mark_logs() {
  : > "$OA_MARKS"
  local log
  for log in $OA_LOG_GLOB; do
    [ -e "$log" ] || continue
    printf '%s\t%s\n' "$log" "$(wc -l < "$log")" >> "$OA_MARKS"
  done
}

attempt_from() { # logfile: the line the surviving attempt started at
  local from=""
  if [ -f "$OA_MARKS" ]; then
    from=$(awk -v f="$1" '$1 == f { print $2 }' "$OA_MARKS")
  fi
  echo "${from:-0}"
}

attempt_log() { # logfile: the lines the surviving attempt wrote
  tail -n "+$(( $(attempt_from "$1") + 1 ))" "$1" 2>/dev/null || true
}

# A retry is safe only for a stage whose one effect is the output it returns.
# A stage that files something has already filed it by the time the generation
# is lost: `record_create` on the incident sink makes a second record, and the
# re-marking above then hides the first call from the very check that verifies
# what was filed, so the duplicate is concealed by the same mechanism that
# makes the retry honest for read-only stages. There is no idempotency key on
# that surface to lean on, and inventing one would be a change to the sink
# rather than to the driver. So a write-bearing task does not retry, and says
# what it lost instead.
oa_run_once() { # same arguments, no retry: the task changes state elsewhere
  local err status=0
  mark_logs
  err=$(mktemp)
  if oa run "$@" 2>"$err"; then
    cat "$err" >&2
    rm -f "$err"
    return 0
  else
    status=$?
  fi
  if grep -Eq "$OA_RETRY_RE" "$err"; then
    echo "  transport failure on a stage that writes. Not retried: it may" >&2
    echo "  have filed before the generation was lost, and a second attempt" >&2
    echo "  would file again. Check the surface before re-running." >&2
  fi
  cat "$err" >&2
  rm -f "$err"
  return "$status"
}

oa_run() { # arguments are passed to `oa run`; stdout is the run's output
  local attempt err status=0
  for attempt in 1 2; do
    mark_logs
    err=$(mktemp)
    if oa run "$@" 2>"$err"; then
      cat "$err" >&2
      rm -f "$err"
      return 0
    else
      status=$?
    fi
    if [ "$attempt" -eq 1 ] && grep -Eq "$OA_RETRY_RE" "$err"; then
      # Prefixed, so nothing parsing stderr for this stage's structured error
      # can read the abandoned attempt's as the answer.
      sed 's/^/  [abandoned attempt] /' "$err" >&2
      echo "  transport failure above, retrying once. This is the provider" >&2
      echo "  losing a generation it made, not a control firing." >&2
      rm -f "$err"
      continue
    fi
    cat "$err" >&2
    rm -f "$err"
    return "$status"
  done
}
