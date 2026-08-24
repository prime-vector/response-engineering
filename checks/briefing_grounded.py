#!/usr/bin/env python3
"""A briefing carries the board's precedent, on the hypotheses that had it.

    python3 checks/briefing_grounded.py

Free, no key, no model. CI runs it over the committed samples.

The briefing's central claim is that it renders the board without extending it,
and that claim lived entirely in the prompt: the output schema can require a
confidence word and a falsifying test per entry, and can say nothing about
whether the sentence around them matches the hypothesis it came from.

The gate found what that costs. One render attached a prior incident, and a
divergence invented to go with it, to a hypothesis whose `precedent_cited` was
empty. Every check in this repository passed it. A citation that reads as
grounding with nothing under it is the anchoring failure the whole project is
about, produced by the agent built to prevent it, and `INC-2411` was in the
board, on a different hypothesis, so no token-level comparison would have
caught it either.

What makes this checkable is prompt rule 6a: one entry per hypothesis, in the
board's order. Alignment turns "did it cite the right thing" from a judgement
into an index lookup. That is the whole reason the rule is about order rather
than about presentation.

WHAT THIS DOES NOT CHECK. Whether an entry's prose is a fair rendering of its
hypothesis, whether a hedge was strengthened, or whether a claim not carrying a
citation is nonetheless unsupported. Those stay prompt rules and a reader's
job. This closes the one route that is mechanically checkable, which is a
precedent appearing where the board attached none.
"""

import json
import pathlib
import re
import sys

import jsonschema
import yaml

SAMPLES = pathlib.Path("docs/samples")
SPEC = ".agents/incident-commander.yaml"
REFERENCE = re.compile(r"\bINC-\d+\b|\bp-[0-9a-f]{12}\b")


def references(obj):
    return set(REFERENCE.findall(json.dumps(obj)))


def check(board_path, brief_path, schema=None):
    board = json.loads(board_path.read_text())
    brief = json.loads(brief_path.read_text())
    label = brief_path.name
    failures = 0

    # Against the task's own schema first. Everything below is a comparison
    # this check invented; this is the contract the agent is actually held to,
    # and without it `falsifying_test` could leave `required`, or
    # `additionalProperties: false` could go, and CI would stay green while the
    # guarantees this change is about disappeared.
    if schema is not None:
        try:
            jsonschema.validate(instance=brief, schema=schema)
        except jsonschema.ValidationError as exc:
            failures += 1
            print(f"  FAIL {label} does not satisfy the brief task's output "
                  f"schema: {exc.message[:110]}")

    invented = sorted(references(brief) - references(board))
    if invented:
        failures += 1
        print(f"  FAIL {label} names {', '.join(invented)}, which the board "
              f"does not: the briefing invented a reference")

    hypotheses = board.get("hypotheses") or []
    suspected = brief.get("suspected") or []
    if len(suspected) != len(hypotheses):
        failures += 1
        print(f"  FAIL {label} has {len(suspected)} suspected entries against "
              f"{len(hypotheses)} hypotheses, so no entry can be matched to "
              f"the hypothesis it renders and nothing below can be checked")
        return failures

    for index, (entry, hypothesis) in enumerate(zip(suspected, hypotheses)):
        # Entries are typed objects now, so the confidence is a field and can
        # be compared to the board's rather than looked for in a sentence.
        if isinstance(entry, dict):
            named = references(entry)
            board_confidence = hypothesis.get("confidence")
            if entry.get("confidence") != board_confidence:
                failures += 1
                print(f"  FAIL {label} entry {index} is "
                      f"{entry.get('confidence')!r} where the board holds "
                      f"{board_confidence!r}: the briefing changed how "
                      f"strongly a hypothesis is held")
            cited = bool(hypothesis.get("precedent_cited"))
            carried = bool(entry.get("precedent"))
            if carried and not cited:
                failures += 1
                print(f"  FAIL {label} entry {index} carries a precedent but "
                      f"hypothesis {index} cites none: grounding with nothing "
                      f"under it")
            # And the other direction, which is the quieter loss. A precedent
            # dropped takes its divergence with it, and rule 6 exists because a
            # precedent that has lost its difference is the anchoring failure
            # the citation was supposed to expose.
            if cited and not carried:
                failures += 1
                print(f"  FAIL {label} entry {index} drops the precedent "
                      f"hypothesis {index} cites, and its divergence with it")
        else:
            named = set(REFERENCE.findall(entry))
        available = references(hypothesis)
        stolen = sorted(named - available)
        if stolen:
            failures += 1
            carried = "carries no precedent at all" if not (
                hypothesis.get("precedent_cited")) else \
                f"carries only {sorted(available & references(board))}"
            print(f"  FAIL {label} entry {index} names {', '.join(stolen)}, "
                  f"but hypothesis {index} {carried}. A precedent on the wrong "
                  f"hypothesis reads as grounding with nothing under it")

    outstanding = [e for e in (board.get("blocking_evidence") or [])
                   if e.get("still_outstanding")]
    if len(brief.get("outstanding") or []) != len(outstanding):
        failures += 1
        print(f"  FAIL {label} lists {len(brief.get('outstanding') or [])} "
              f"outstanding items against {len(outstanding)} still outstanding "
              f"on the board")

    conditions = brief.get("standing_conditions") or []
    if len(conditions) != len(board.get("standing_conditions_noted") or []):
        failures += 1
        print(f"  FAIL {label} carries {len(conditions)} standing conditions "
              f"against {len(board.get('standing_conditions_noted') or [])} on "
              f"the board: the findings that get lost first")
    # A condition filed beside the evidence has become evidence. Checked
    # against `known` only: the board can hold one thing as both a hypothesis
    # and a standing condition, so an entry in `suspected` that also appears
    # here is the board's own classification rather than a promotion.
    #
    # Per entry, and that is a stated limit rather than an oversight. The
    # committed render splits one standing condition across two `known`
    # entries, the auto-close half in one and the unacknowledged half in the
    # other, and neither half restates it alone. Detecting that needs a
    # threshold over subsets of entries, and every threshold that catches this
    # sample also flags conditions that merely share vocabulary with the
    # evidence, which they always do. A check that accuses correct output gets
    # worked around. So the whole-entry restatement is refused and the split
    # one is recorded in docs/samples/briefing-2026-08-24/, where it can be
    # read, rather than half-detected here.
    def shape(text):
        return {w for w in re.findall(r"[a-z0-9.]{4,}", (text or "").lower())}

    known = brief.get("known") or []
    duplicated = []
    for condition in conditions:
        want = shape(condition)
        if not want:
            continue
        for entry in known:
            got = shape(entry)
            if got and len(want & got) / min(len(want), len(got)) >= 0.6:
                duplicated.append(condition)
                break
    if duplicated:
        failures += 1
        print(f"  FAIL {label} restates {len(duplicated)} standing "
              f"condition(s) in known, whole or split across entries, which "
              f"files them beside the evidence the board separated them from")

    if not failures:
        print(f"  ok   {label}: {len(suspected)} entries aligned to the board, "
              f"every reference on the hypothesis that carries it, "
              f"{len(conditions)} standing conditions kept separate")
    return failures


# The committed counterexample exercises two of the six branches below. The
# other four are live and would be deleted unnoticed, which is the failure this
# repository keeps making, so they get synthetic pairs of their own. Each case
# names the reason it must fail, because a case that fails for a different
# reason proves nothing about the branch it is named for.
def _board(hypotheses=None, outstanding=1, conditions=1):
    return {
        "hypotheses": hypotheses if hypotheses is not None else
        [{"statement": "h0", "confidence": "plausible", "precedent_cited": []}],
        "blocking_evidence": [{"description": f"b{i}", "still_outstanding": True}
                              for i in range(outstanding)],
        "standing_conditions_noted": [f"condition {i}" for i in range(conditions)],
    }


def _brief(suspected=None, outstanding=1, conditions=1, known=None):
    return {
        "headline": "h",
        "known": known if known is not None else [],
        "suspected": suspected if suspected is not None else
        [{"statement": "thing", "confidence": "plausible",
          "falsifying_test": "observe x"}],
        "outstanding": [f"b{i}" for i in range(outstanding)],
        "standing_conditions": [f"condition {i}" for i in range(conditions)],
    }


SELF_TESTS = (
    ("a faithful briefing", None, _board(), _brief()),
    ("a reference the board does not contain", "invented",
     _board(), _brief(suspected=[{"statement": "s, see INC-9999",
                                 "confidence": "plausible",
                                 "falsifying_test": "t"}])),
    ("more entries than the board has hypotheses", "suspected entries against",
     _board(), _brief(suspected=[
         {"statement": "one", "confidence": "plausible", "falsifying_test": "t"},
         {"statement": "two", "confidence": "plausible", "falsifying_test": "t"}])),
    ("a precedent on a hypothesis that carries none", "wrong hypothesis",
     _board(hypotheses=[{"statement": "h0", "confidence": "plausible",
                         "precedent_cited": []},
                        {"statement": "h1", "confidence": "plausible",
                         "precedent_cited": ["p-aaaaaaaaaaaa"], "note": "INC-2411"}]),
     _brief(suspected=[{"statement": "s", "confidence": "plausible",
                        "falsifying_test": "t", "precedent": "INC-2411"},
                       {"statement": "s", "confidence": "plausible",
                        "falsifying_test": "t"}])),
    ("fewer outstanding items than the board still has", "outstanding items",
     _board(outstanding=3), _brief(outstanding=1)),
    ("a standing condition dropped", "standing conditions",
     _board(conditions=3), _brief(conditions=1)),
    ("a standing condition repeated in known", "restates",
     _board(), _brief(known=["condition 0"])),
    # The paraphrase, which a prefix comparison passed and the gate caught in
    # the one sample this check was meant to vouch for.
    ("a standing condition restated in known in different words", "restates",
     {"hypotheses": [{"statement": "h0", "precedent_cited": []}],
      "blocking_evidence": [{"description": "b0", "still_outstanding": True}],
      "standing_conditions_noted": [
          "The integration service holds 23.1 GiB resident of 32 GiB total as "
          "steady state, with no alerting configured and no owner assigned"]},
     {"headline": "h",
      "known": ["No alerting configured and no owner assigned for the "
                "integration service holding 23.1 GiB resident of 32 GiB"],
      "suspected": [{"statement": "s", "confidence": "plausible",
                     "falsifying_test": "t"}],
      "outstanding": ["b0"],
      "standing_conditions": [
          "The integration service holds 23.1 GiB resident of 32 GiB total as "
          "steady state, with no alerting configured and no owner assigned"]}),
    # A typed entry may not change how strongly the board holds a hypothesis.
    ("an entry promoting the board's confidence", "changed how strongly",
     {"hypotheses": [{"statement": "h0", "confidence": "plausible",
                      "precedent_cited": []}],
      "blocking_evidence": [], "standing_conditions_noted": []},
     {"headline": "h", "known": [], "outstanding": [], "standing_conditions": [],
      "suspected": [{"statement": "s", "confidence": "supported",
                     "falsifying_test": "t"}]}),
    # The historical renders are kept because they fail, so the check that
    # says so is exercised rather than asserted in a README.
    ("a render whose entries are strings, as they were before typed fields",
     "output schema",
     {"hypotheses": [{"statement": "h0", "confidence": "plausible",
                      "precedent_cited": []}],
      "blocking_evidence": [], "standing_conditions_noted": []},
     {"headline": "h", "known": [], "outstanding": [], "standing_conditions": [],
      "suspected": ["PLAUSIBLE thing. Falsifying test: x."]}),
    ("an entry with no falsifying test", "output schema",
     {"hypotheses": [{"statement": "h0", "confidence": "plausible",
                      "precedent_cited": []}],
      "blocking_evidence": [], "standing_conditions_noted": []},
     {"headline": "h", "known": [], "outstanding": [], "standing_conditions": [],
      "suspected": [{"statement": "s", "confidence": "plausible"}]}),
    ("an entry carrying an undeclared field", "output schema",
     {"hypotheses": [{"statement": "h0", "confidence": "plausible",
                      "precedent_cited": []}],
      "blocking_evidence": [], "standing_conditions_noted": []},
     {"headline": "h", "known": [], "outstanding": [], "standing_conditions": [],
      "suspected": [{"statement": "s", "confidence": "plausible",
                     "falsifying_test": "t", "root_cause": "z"}]}),
    # Precedent dropped, which is the quieter half of the same rule.
    ("an entry dropping the precedent its hypothesis cites", "drops the precedent",
     {"hypotheses": [{"statement": "h0", "confidence": "plausible",
                      "precedent_cited": ["p-aaaaaaaaaaaa"]}],
      "blocking_evidence": [], "standing_conditions_noted": []},
     {"headline": "h", "known": [], "outstanding": [], "standing_conditions": [],
      "suspected": [{"statement": "s", "confidence": "plausible",
                     "falsifying_test": "t"}]}),
    # And may not carry a precedent the board did not attach.
    ("an entry carrying a precedent the board did not", "cites none",
     {"hypotheses": [{"statement": "h0", "confidence": "plausible",
                      "precedent_cited": []}],
      "blocking_evidence": [], "standing_conditions_noted": []},
     {"headline": "h", "known": [], "outstanding": [], "standing_conditions": [],
      "suspected": [{"statement": "s", "confidence": "plausible",
                     "falsifying_test": "t", "precedent": "a prior incident"}]}),
)


def self_test():
    import contextlib
    import io
    import tempfile

    failures = 0
    for label, expected, board, brief in SELF_TESTS:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "board.json").write_text(json.dumps(board))
            (root / "briefing-bridge.json").write_text(json.dumps(brief))
            buf = io.StringIO()
            spec = yaml.safe_load(pathlib.Path(SPEC).read_text())
            with contextlib.redirect_stdout(buf):
                count = check(root / "board.json", root / "briefing-bridge.json",
                              spec["tasks"]["brief"]["output"])
        output = buf.getvalue()
        if expected is None:
            ok, detail = count == 0, "accepted"
            if not ok:
                detail = "rejected: " + output.strip().splitlines()[0][:70]
        elif count == 0:
            ok, detail = False, "accepted, but should have been rejected"
        else:
            ok = expected in output
            detail = (f"rejected on {expected!r}" if ok else
                      f"rejected for the wrong reason, wanted {expected!r}")
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {detail}")
    print()
    if failures:
        sys.exit(f"{failures} self-test(s) failed: the check does not behave "
                 f"the way it is documented to.")
    print(f"{len(SELF_TESTS)} self-tests hold, each on the reason it names.")


def main():
    if "--self-test" in sys.argv:
        return self_test()
    pairs = [(d / "board.json", d / "briefing-bridge.json")
             for d in sorted(SAMPLES.glob("briefing-*"))
             if (d / "board.json").exists() and (d / "briefing-bridge.json").exists()]
    if not pairs:
        sys.exit("No board and briefing pair found under docs/samples/.")
    spec = yaml.safe_load(pathlib.Path(SPEC).read_text())
    schema = spec["tasks"]["brief"]["output"]
    failures = sum(check(b, r, schema) for b, r in pairs)
    print()
    if failures:
        sys.exit(f"{failures} grounding failure(s): a briefing is claiming "
                 f"something its board does not carry.")
    print(f"{len(pairs)} briefing(s) carry only what their board gave them.")


if __name__ == "__main__":
    main()
