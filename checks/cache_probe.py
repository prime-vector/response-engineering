#!/usr/bin/env python3
"""Send two identical requests and print what the cache did with them.

The CLI's usage mapper keeps `input_tokens` and `output_tokens` and drops
everything else, so `oa run` cannot tell a cached request from an uncached one:
both look the same through it. That makes the caching patch in `patches/` the
one change here whose effect is invisible to the tool it changes, which is a
good way for a saving to quietly stop happening.

This calls the API directly, through the installed provider's own helpers, so
what it reports is what those helpers build rather than a re-implementation
that could drift from them. Two small requests on a cheap model:

    python3 checks/cache_probe.py

Needs ANTHROPIC_API_KEY and the patched provider. Not a CI check: it spends
money, and the amount is small rather than nothing.
"""

import json
import os
import sys
import urllib.error
import urllib.request

MODEL = os.environ.get("CACHE_PROBE_MODEL", "claude-haiku-4-5-20251001")
ENDPOINT = "https://api.anthropic.com/v1/messages"

# Comfortably over the highest per-model floor the patch sets, so a miss here
# is the breakpoint failing rather than the fixture being too short.
SYSTEM = "You are a fixture used to verify prompt caching. " * 500
FIRST_TURN = "Incident view placeholder. " * 1500


# Eligibility is a decision the helpers make before any request exists, and the
# live half below cannot see it: that request is oversized and carries no tools,
# so it would pass whether or not the rule were right. The gate found exactly
# that gap. These cases cost nothing and run without a key.
def eligibility_cases(floor):
    """Cases sized against the floor for the model under test, not a constant.

    The floor differs per model, so a table of fixed sizes tests Sonnet's rule
    and silently passes or fails Haiku's.
    """
    return [
        ("a system prompt over the floor", floor + 500, 0, True),
        ("a system prompt under it", floor - 500, 0, False),
        # The minimum applies to the prefix, which is the tools and then the
        # system block. Measured per block, this pair is declined twice over
        # while the pair itself clears the floor comfortably.
        ("a short system prompt behind substantial tools",
         int(floor * 0.6), int(floor * 0.6), True),
        ("both halves short", int(floor * 0.3), int(floor * 0.2), False),
    ]


def check_eligibility(system_field, cache_first_turn, model, floor):
    failures = 0
    for name, system_chars, prefix_chars, expected in eligibility_cases(floor):
        got = isinstance(system_field("s" * system_chars, {}, model, prefix_chars), list)
        ok = got == expected
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: "
              f"{'breakpoint' if got else 'no breakpoint'}")
        if cache_first_turn:
            turn = [{"role": "user", "content": "v" * system_chars}]
            marked = isinstance(
                cache_first_turn(turn, model, prefix_chars)[0]["content"], list)
            if marked != expected:
                failures += 1
                print(f"  FAIL {name}, first turn: disagrees with the system rule")
    return failures


def main():
    try:
        from oas_cli.providers.anthropic_http import _system_field
    except ImportError as exc:
        sys.exit(f"Cannot import the provider: {exc}")

    try:
        from oas_cli.providers.anthropic_http import _cache_first_turn
    except ImportError:
        _cache_first_turn = None
        print("note: _cache_first_turn is absent, so only the system "
              "breakpoint is under test. Is the caching patch applied?")

    try:
        from oas_cli.providers.anthropic_http import _cache_min_chars
    except ImportError:
        _cache_min_chars = None

    if _cache_min_chars:
        floor = _cache_min_chars(MODEL)
        print(f"eligibility against the {floor} character floor for {MODEL}, "
              "decided before any request is built:")
        if check_eligibility(_system_field, _cache_first_turn, MODEL, floor):
            sys.exit("\nThe floor is not being measured against the prefix.")
        print()

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY is not set, so the live half is skipped. The "
              "eligibility rules above hold.")
        return

    # The helpers take the model because the minimum cacheable length does:
    # a prompt long enough for Sonnet is short of what Haiku will cache.
    system = _system_field(SYSTEM, {}, MODEL)
    if not isinstance(system, list):
        sys.exit("The provider returned `system` as a plain string: the "
                 "caching patch is not applied, cache_prompt is off, or this "
                 "fixture is shorter than the floor for " + MODEL + ".")

    messages = [{"role": "user", "content": FIRST_TURN}]
    if _cache_first_turn:
        messages = _cache_first_turn(messages, MODEL)

    payload = {"model": MODEL, "max_tokens": 16, "system": system,
               "messages": messages}
    breakpoints = json.dumps(payload).count('"cache_control"')
    print(f"model {MODEL}, {breakpoints} cache breakpoint(s) in the request\n")

    seen = []
    for attempt in (1, 2):
        req = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload).encode(),
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                usage = json.loads(response.read())["usage"]
        except urllib.error.HTTPError as exc:
            sys.exit(f"HTTP {exc.code}: {exc.read()[:400].decode(errors='replace')}")
        seen.append(usage)
        print(f"  call {attempt}: input {usage.get('input_tokens')}, "
              f"cache write {usage.get('cache_creation_input_tokens')}, "
              f"cache read {usage.get('cache_read_input_tokens')}")

    read = seen[-1].get("cache_read_input_tokens") or 0
    print()
    if read:
        print(f"The second call read {read} tokens from cache rather than "
              "paying for them.")
    else:
        # Worth separating from a failure: a cold cache and a broken breakpoint
        # look the same on one pair of calls if the first write did not land.
        print("The second call read nothing from cache. Either the breakpoints "
              "are not reaching the API, or the first write did not land: "
              "check the write figure on call 1 before concluding.")
        sys.exit(1)


if __name__ == "__main__":
    main()
