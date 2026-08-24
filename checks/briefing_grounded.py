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

SAMPLES = pathlib.Path("docs/samples")
REFERENCE = re.compile(r"\bINC-\d+\b|\bp-[0-9a-f]{12}\b")


def references(obj):
    return set(REFERENCE.findall(json.dumps(obj)))


def check(board_path, brief_path):
    board = json.loads(board_path.read_text())
    brief = json.loads(brief_path.read_text())
    label = brief_path.name
    failures = 0

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
            if bool(entry.get("precedent")) and not hypothesis.get("precedent_cited"):
                failures += 1
                print(f"  FAIL {label} entry {index} carries a precedent but "
                      f"hypothesis {index} cites none: grounding with nothing "
                      f"under it")
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
    # A condition listed twice is a condition promoted back into the evidence.
    # Compared by shared content words rather than by a common prefix: the
    # prefix test passed a `known` entry that restated a standing condition in
    # different words, which is the same promotion wearing a paraphrase, and
    # the gate found it in the one sample the check was meant to vouch for.
    def shape(text):
        return {w for w in re.findall(r"[a-z0-9.]{4,}", (text or "").lower())}

    duplicated = []
    for entry in (brief.get("known") or []):
        for condition in conditions:
            a, b = shape(entry), shape(condition)
            if a and b and len(a & b) / min(len(a), len(b)) >= 0.6:
                duplicated.append(entry)
                break
    if duplicated:
        failures += 1
        print(f"  FAIL {label} repeats {len(duplicated)} standing condition(s) "
              f"in known, which undoes the separation the board made")

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
    ("a standing condition repeated in known", "repeats",
     _board(), _brief(known=["condition 0"])),
    # The paraphrase, which a prefix comparison passed and the gate caught in
    # the one sample this check was meant to vouch for.
    ("a standing condition restated in known in different words", "repeats",
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
            with contextlib.redirect_stdout(buf):
                count = check(root / "board.json", root / "briefing-bridge.json")
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
    failures = sum(check(b, r) for b, r in pairs)
    print()
    if failures:
        sys.exit(f"{failures} grounding failure(s): a briefing is claiming "
                 f"something its board does not carry.")
    print(f"{len(pairs)} briefing(s) carry only what their board gave them.")


if __name__ == "__main__":
    main()
