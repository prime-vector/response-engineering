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
    duplicated = [k for k in (brief.get("known") or [])
                  for c in conditions if k[:60] == c[:60]]
    if duplicated:
        failures += 1
        print(f"  FAIL {label} repeats {len(duplicated)} standing condition(s) "
              f"in known, which undoes the separation the board made")

    if not failures:
        print(f"  ok   {label}: {len(suspected)} entries aligned to the board, "
              f"every reference on the hypothesis that carries it, "
              f"{len(conditions)} standing conditions kept separate")
    return failures


def main():
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
