#!/usr/bin/env python3
"""Check that the streaming patch reassembles a response the callers still fit.

The streaming patch in `patches/` changes how a generation arrives and nothing
about what it says, which is exactly the change a live run cannot confirm: a
request that streams correctly looks the same, through `oa run`, as one that
never streamed. What can go wrong is the reassembly, and it goes wrong in
places a happy-path call never reaches, so this drives `_collect_stream`
against canned event streams and compares the result against the response the
non-streaming path would have returned for the same message.

    python3 checks/stream_probe.py

Costs nothing and needs no key. Not a CI check even so: it tests the installed
provider, and CI installs the unpatched wheel.
"""

import json
import os
import sys

# `oa` is usually a pipx install, so oas_cli lives in its own virtualenv and
# the system interpreter cannot see it. Re-exec under the interpreter `oa`
# itself runs on, which is the install under test in any case: a probe that
# imported some other copy of the provider would be reporting on the wrong one.
def _reexec_under_oa():
    import shutil
    import subprocess

    oa = shutil.which("oa")
    if not oa:
        return
    try:
        with open(oa) as handle:
            shebang = handle.readline()
    except (OSError, UnicodeDecodeError):
        return
    if not shebang.startswith("#!"):
        return
    interpreter = shebang[2:].strip().split()[0]
    if not os.path.isfile(interpreter) or interpreter == sys.executable:
        return
    # Compared by path, deliberately, and not by realpath: a virtualenv's
    # python is a symlink to the system binary, so resolving it says they are
    # the same interpreter when only one of them can see oas_cli. The path is
    # what selects site-packages.
    os.environ["OA_PROBE_REEXEC"] = "1"
    raise SystemExit(subprocess.call([interpreter, *sys.argv]))


# Unconditionally, not merely when the import fails. A system python3 that
# *can* import some other oas_cli would certify a copy the demos never load,
# and that is the failure that looks exactly like a pass.
if not os.environ.get("OA_PROBE_REEXEC"):
    _reexec_under_oa()


# One message, both ways. The left side is what the API returns when the
# request does not stream; the right side is the event sequence for the same
# message. Everything the reassembly has to get right is in here: text and
# thinking accumulate across deltas, a tool call's arguments are only valid
# JSON once the fragments are joined, an argument-free tool call sends no
# fragment at all, stop_reason arrives late, and usage is merged from two
# events with the cache fields intact.
EXPECTED = {
    "id": "msg_fixture",
    "type": "message",
    "role": "assistant",
    "model": "claude-fixture",
    "content": [
        {"type": "thinking", "thinking": "Weigh the two.", "signature": "sig=="},
        {"type": "text", "text": "Recalling prior incidents."},
        {
            "type": "tool_use",
            "id": "toolu_a",
            "name": "precedent_search",
            "input": {"signature": "host.memory.exhaustion", "before": "2026-08-05"},
        },
        {"type": "tool_use", "id": "toolu_b", "name": "coverage_describe", "input": {}},
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 22_014,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 13_006,
        "output_tokens": 461,
    },
}

EVENTS = [
    {"type": "message_start", "message": {
        "id": "msg_fixture", "type": "message", "role": "assistant",
        "model": "claude-fixture", "content": [], "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 22_014, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 13_006, "output_tokens": 2}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "thinking_delta", "thinking": "Weigh "}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "thinking_delta", "thinking": "the two."}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "signature_delta", "signature": "sig=="}},
    {"type": "content_block_stop", "index": 0},
    {"type": "ping"},
    {"type": "content_block_start", "index": 1,
     "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "text_delta", "text": "Recalling "}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "text_delta", "text": "prior incidents."}},
    {"type": "content_block_stop", "index": 1},
    {"type": "content_block_start", "index": 2,
     "content_block": {"type": "tool_use", "id": "toolu_a",
                       "name": "precedent_search", "input": {}}},
    # Split mid-token on purpose: a fragment boundary that falls inside a JSON
    # string is the case a naive per-fragment parse gets wrong.
    {"type": "content_block_delta", "index": 2,
     "delta": {"type": "input_json_delta", "partial_json": '{"signature": "host.mem'}},
    {"type": "content_block_delta", "index": 2,
     "delta": {"type": "input_json_delta",
               "partial_json": 'ory.exhaustion", "before": "2026-08-05"}'}},
    {"type": "content_block_stop", "index": 2},
    # No input_json_delta at all: the empty accumulator must mean {}.
    {"type": "content_block_start", "index": 3,
     "content_block": {"type": "tool_use", "id": "toolu_b",
                       "name": "coverage_describe", "input": {}}},
    {"type": "content_block_stop", "index": 3},
    {"type": "message_delta",
     "delta": {"stop_reason": "tool_use", "stop_sequence": None},
     "usage": {"output_tokens": 461}},
    {"type": "message_stop"},
]


# The other shape, and the one that motivated the patch: a text-only reply
# ending in `end_turn`, which is what every single-shot task returns and what
# the commander's board arrives as. The tool-bearing fixture above exercises
# more machinery; this exercises the path that was actually failing.
BOARD_EXPECTED = {
    "id": "msg_board",
    "type": "message",
    "role": "assistant",
    "model": "claude-fixture",
    "content": [{"type": "text", "text": '{"incident_state": "hypothesis_blocked"}'}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 24_500, "output_tokens": 3_812},
}

BOARD_EVENTS = [
    {"type": "message_start", "message": {
        "id": "msg_board", "type": "message", "role": "assistant",
        "model": "claude-fixture", "content": [], "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 24_500, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": '{"incident_state": '}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": '"hypothesis_blocked"}'}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                        "stop_sequence": None},
     "usage": {"output_tokens": 3_812}},
    {"type": "message_stop"},
]


def sse(events):
    """The events as the wire carries them: one `data:` line each, plus noise.

    The blank lines and `event:` lines are what an SSE stream actually
    contains, and a reader that chokes on them fails on every real response
    while passing any fixture that omits them.
    """
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}\n".encode())
        lines.append(f"data: {json.dumps(event)}\n".encode())
        lines.append(b"\n")
    return lines


def check_reassembly(collect):
    failures = 0
    for name, events, expected in (
        ("a tool-calling message", EVENTS, EXPECTED),
        ("a text-only end_turn reply, the assess shape", BOARD_EVENTS,
         BOARD_EXPECTED),
    ):
        got = collect(sse(events))
        if got == expected:
            print(f"  ok   {name} reassembles to the non-streaming shape")
            continue
        print(f"  FAIL {name} differs from the non-streaming shape")
        failures += 1
        for key in sorted(set(expected) | set(got)):
            if got.get(key) != expected.get(key):
                print(f"       {key}:\n         expected {expected.get(key)!r}"
                      f"\n         got      {got.get(key)!r}")
    return failures


def check_usage_maps(collect):
    """The cache fields have to survive, or this patch undoes the caching one."""
    from oas_cli.usage import from_anthropic

    usage = collect(sse(EVENTS))["usage"]
    failures = 0
    for field, want in (("cache_read_input_tokens", 13_006),
                        ("cache_creation_input_tokens", 0),
                        ("output_tokens", 461)):
        ok = usage.get(field) == want
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} usage carries {field} "
              f"({usage.get(field)!r}, expected {want!r})")
    # The mapper canonicalises to prompt/completion/total and drops the cache
    # fields on the way through, which is why `oa run` cannot report a hit and
    # `checks/cache_probe.py` exists. What matters here is only that the merged
    # counts reach it: output_tokens from message_delta, not the placeholder
    # message_start opened with.
    canonical = from_anthropic(usage)
    ok = bool(canonical) and canonical.get("completion_tokens") == 461 \
        and canonical.get("prompt_tokens") == 22_014
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} the CLI's usage mapper reads the "
          f"merged counts ({canonical!r})")
    return failures


def check_failures(collect, provider_error):
    """The cases where failing loudly is the whole point.

    Each fault is injected into an otherwise complete stream, and the message
    is matched. Both matter. A two-event prefix would raise on the missing
    `message_stop` whatever the helper did with the fault, so the case would
    pass with the handling it names deleted; and a raise alone does not say
    which check fired. What is being demonstrated is refusing a response that
    still has its blocks, which cannot be shown on a stream that never
    finished.
    """
    def fault_in_the_middle(event):
        """The fault lands mid-stream, so everything else still arrives."""
        return EVENTS[:6] + [event] + EVENTS[6:]

    # Malformed tool arguments: the stream completed and nothing is missing,
    # but the fragments do not join into JSON. Silently passing {} would hand
    # the tool loop a call the agent did not make.
    truncated_args = [e for e in EVENTS if e.get("index") != 2 or
                      e.get("type") != "content_block_delta"]
    truncated_args.insert(12, {"type": "content_block_delta", "index": 2,
                               "delta": {"type": "input_json_delta",
                                         "partial_json": '{"signature": "host.mem'}})

    cases = [
        ("a stream that closes before any content", EVENTS[:1], "message_stop"),
        # Distinct from the case above, and the reason it needs its own: that
        # one is caught by the completeness guard and would still pass with
        # the no-content check deleted. This stream finished properly and
        # carried nothing, which only the second check can refuse.
        ("a complete stream carrying no content at all",
         [EVENTS[0], {"type": "message_delta",
                      "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                      "usage": {"output_tokens": 0}},
          {"type": "message_stop"}],
         "no content blocks"),
        # The quiet one. Every block arrived and the shape is plausible, but
        # message_delta never landed, so stop_reason is still None and
        # invoke_with_tools would read a cut generation as a final answer.
        ("a stream cut after its content but before message_stop",
         EVENTS[:-2], "message_stop"),
        ("an error event in an otherwise complete stream",
         fault_in_the_middle({"type": "error",
                              "error": {"type": "overloaded_error",
                                        "message": "Overloaded"}}),
         "stream error"),
        # An unknown delta type is content this reassembly would drop on the
        # floor, returning a message that differs from the non-streaming one
        # and passes every shape check while doing it. `citations_delta` is
        # the live example: nothing in this repository reads citations, and a
        # response quietly missing them is still the wrong response.
        ("an unrecognised delta type",
         fault_in_the_middle({"type": "content_block_delta", "index": 1,
                              "delta": {"type": "citations_delta",
                                        "citation": {"type": "char_location"}}}),
         "unrecognised delta"),
        ("truncated tool arguments", truncated_args, "malformed tool input"),
    ]

    failures = 0
    for name, events, expected in cases:
        try:
            collect(sse(events))
        except provider_error as exc:
            if expected in str(exc):
                print(f"  ok   {name} raises: {exc}")
            else:
                print(f"  FAIL {name} raised the wrong check: {exc}")
                failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - any other type is a failure too
            print(f"  FAIL {name} raised {type(exc).__name__}, not ProviderError")
            failures += 1
            continue
        print(f"  FAIL {name} returned instead of raising")
        failures += 1

    # Invalid UTF-8 is the one that parses anyway. Replacing the bad bytes
    # would put U+FFFD inside a JSON string, json.loads would succeed, and the
    # caller would get a message whose text differs from what the model sent
    # while passing every check above. The non-streaming path decodes strictly
    # and fails, so anything else here makes the same-response claim false.
    text_event = EVENTS[8]
    mangled = json.dumps(text_event).encode().replace(
        b'"Recalling "', b'"Recalling \xff\xfe"')
    undecodable = (sse(EVENTS[:8]) + [b"data: " + mangled + b"\n", b"\n"]
                   + sse(EVENTS[9:]))
    try:
        got = collect(undecodable)
    except provider_error as exc:
        if "undecodable" in str(exc):
            print(f"  ok   undecodable bytes raise: {exc}")
        else:
            print(f"  FAIL undecodable bytes raised the wrong check: {exc}")
            failures += 1
    else:
        joined = "".join(b.get("text", "") for b in got["content"])
        print("  FAIL undecodable bytes were rewritten and parsed: "
              f"{joined!r}")
        failures += 1

    # Same discipline for the wire itself: a `data:` line that will not parse
    # is text missing from the middle of a generation, and the stream around
    # it is complete, so the refusal has to come from the parse and not from
    # the completeness check.
    corrupted = (sse(EVENTS[:6]) + [b'data: {"type": "content_bl\n', b"\n"]
                 + sse(EVENTS[6:]))
    try:
        collect(corrupted)
    except provider_error as exc:
        if "unparseable event" in str(exc):
            print(f"  ok   an unparseable event raises: {exc}")
        else:
            print(f"  FAIL an unparseable event raised the wrong check: {exc}")
            failures += 1
    else:
        print("  FAIL an unparseable event was skipped")
        failures += 1

    return failures


def check_call_sites(module):
    """Both call sites must stream, and both must honour the off switch.

    `invoke_verbose` serves the single-shot tasks and `invoke_with_tools` every
    round of a tool loop including its final reply, which is the longest
    generation of the two. A patch that reaches one of them fixes half the
    exposure and reads, from a passing live run, exactly like a patch that
    reached both.
    """
    import inspect

    failures = 0
    for method in ("invoke_verbose", "invoke_with_tools"):
        try:
            source = inspect.getsource(getattr(module.AnthropicProvider, method))
        except (AttributeError, OSError) as exc:
            print(f"  FAIL cannot read {method}: {exc}")
            failures += 1
            continue
        for fragment, what in (("_post(", "posts through the shared helper"),
                               ('config.get("stream"', "reads the stream switch")):
            ok = fragment in source
            failures += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {method} {what}")
    return failures


def main():
    try:
        import oas_cli.providers.anthropic_http as provider
        from oas_cli.providers.anthropic_http import _collect_stream
        from oas_cli.providers.base import ProviderError
    except ImportError as exc:
        sys.exit(f"Cannot import the streamed provider: {exc}. Is the "
                 "streaming patch applied?")

    failures = 0

    print("call sites:")
    failures += check_call_sites(provider)
    print("\nreassembly:")
    failures += check_reassembly(_collect_stream)
    print("\nusage:")
    failures += check_usage_maps(_collect_stream)
    print("\nfailing loudly:")
    failures += check_failures(_collect_stream, ProviderError)

    print()
    if failures:
        sys.exit(f"{failures} check(s) failed: the streaming patch is partly "
                 "applied, or reassembly has drifted from the response shape.")
    print("The streamed path returns what the non-streaming path returned.")


if __name__ == "__main__":
    main()
