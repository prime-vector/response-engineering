#!/usr/bin/env python3
"""Assert what the commander's board can and cannot express about precedent.

Four rules in `.agents/incident-commander.yaml` close the typed routes by which
precedent could become deciding evidence. They do not close prose, and the last
two cases below are the boards that prove it: a schema sees the list the board
wrote and never the view it was drawn from. The suite carries both halves,
because a check that only demonstrates its own successes is how a claim grows
past what it can keep.

Until this file existed the rules were exercised only when a live model
happened to produce a board that tried one, which is a test that runs when it
feels like it and costs an API call when it does.

Each case below is a board, and each says whether the contract should accept
it. No model, no network, no API key: the schema is read out of the spec and
handed to the same validator the runner uses.

    python3 checks/contract_invariants.py

Fails loudly on the first case whose verdict does not match, printing the
board and what the validator said.
"""

import copy
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")

try:
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
except ImportError:  # pragma: no cover
    sys.exit("jsonschema is required: pip install jsonschema")

SPEC = Path(__file__).resolve().parent.parent / ".agents" / "incident-commander.yaml"

# The smallest board this contract accepts, so a case's own edit is the only
# thing under test. Everything here is deliberately dull: the interesting part
# of each case is the one field it changes.
BASE = {
    "incident_state": "hypothesis_blocked",
    "hypotheses": [
        {
            "statement": "A recently activated daemon is consuming the host's memory.",
            "confidence": "plausible",
            "supporting_evidence": ["Process snapshot E-1."],
            "falsifying_test": "The audit denial log names another source domain.",
            "third_party_named": False,
        }
    ],
    "blocking_evidence": [
        {
            "description": "Audit denial log for the affected window.",
            "how_to_obtain": "Platform team pulls it from the host.",
            "still_outstanding": True,
        }
    ],
    "convergence_allowed": False,
    "next_actions": [
        {
            "action": "Obtain the audit denial log.",
            "owner_role": "platform_team",
            "authorisation_required": False,
        }
    ],
}


def case(name, mutate, accepted):
    board = copy.deepcopy(BASE)
    mutate(board)
    return name, board, accepted


def _cite(board, ids=("p-14cc2f280479",)):
    board["hypotheses"][0]["precedent_cited"] = list(ids)


CASES = [
    case("the base board", lambda b: None, True),
    # Precedent supports a hypothesis. This is the whole point: it has to be
    # expressible, or the agent has nowhere to put a citation and puts it in
    # prose instead.
    case("a hypothesis citing precedent", _cite, True),
    # Rule: a hypothesis resting on the archive cannot be confirmed. Both
    # spellings, because the const alone closes one and the enum closes the
    # rest.
    case("cited and confirmed", lambda b: (_cite(b), b["hypotheses"][0].update(confidence="confirmed")), False),
    case("cited and Confirmed", lambda b: (_cite(b), b["hypotheses"][0].update(confidence="Confirmed")), False),
    case("a confidence outside the scale", lambda b: b["hypotheses"][0].update(confidence="high"), False),
    # The three closed sets are closed in the schema and stated in the prompt.
    # A live board invented `guard_evidence_integrity` for this field the first
    # time the enum went in without the prompt naming its values.
    case("an intent outside the set",
         lambda b: b["next_actions"][0].update(intent="guard_evidence_integrity"), False),
    case("an incident_state outside the set",
         lambda b: b.update(incident_state="investigating_hard"), False),
    # Rule: the list convergence blocks on cannot carry a citation, as a field
    # or as anything else, because it carries no fields beyond its five.
    case("precedent attached to blocking evidence",
         lambda b: b["blocking_evidence"][0].update(precedent_cited=["p-14cc2f280479"]), False),
    case("any extra field on blocking evidence",
         lambda b: b["blocking_evidence"][0].update(note="retrieved from the archive"), False),
    # Rule: convergence is false while the board's own list has an outstanding
    # item, and the flag saying so cannot be dropped.
    case("convergence allowed with an item outstanding",
         lambda b: b.update(convergence_allowed=True), False),
    case("convergence allowed with nothing outstanding",
         lambda b: (b["blocking_evidence"][0].update(still_outstanding=False),
                    b.update(convergence_allowed=True)), True),
    case("still_outstanding omitted",
         lambda b: b["blocking_evidence"][0].pop("still_outstanding"), False),
    # The boolean and null failures that cost two whole boards in live runs.
    case("a qualification written into a boolean",
         lambda b: b["next_actions"][0].update(reversible="false within the window"), False),
    case("an optional string emitted as null",
         lambda b: b.update(convergence_block_reason=None), False),
    # The attribution rule this contract already had, kept here so a change to
    # one invariant cannot quietly cost the other.
    case("a third party named below confirmed, guard silent",
         lambda b: b["hypotheses"][0].update(third_party_named=True), False),
    # Accepted, and the point of the case is that it is accepted. Closing the
    # blocking-evidence object stops a citation entering the deciding list as
    # data; it cannot stop the board asserting in prose that a passage settled
    # an item and setting the flag to match. The pre-merge gate found this
    # while the surrounding documents claimed the contract could not express
    # it. If someone later closes it, this case starts failing, which is the
    # point of writing the hole down as a test rather than a caveat.
    case("precedent asserted in prose as satisfying a blocking item",
         lambda b: (_cite(b),
                    b["blocking_evidence"][0].update(
                        description="Audit denial log. INC-2288 records the same "
                                    "daemon as the source, so this is settled.",
                        still_outstanding=False),
                    b.update(convergence_allowed=True)), True),
    # Same hole, simpler: a board that raises nothing has nothing to block on.
    case("a board with no blocking evidence at all",
         lambda b: (b.update(blocking_evidence=[]), b.update(convergence_allowed=True)), True),
    # The rule reads one field by name, so the objects carrying it are closed.
    # The gate found this: a citation under any other name is a citation the
    # rule cannot see, on a hypothesis it then confirms.
    case("a citation smuggled under another field name",
         lambda b: b["hypotheses"][0].update(precedent_passage_id="p-14cc2f280479",
                                             confidence="confirmed"), False),
    case("an undeclared field on a next action",
         lambda b: b["next_actions"][0].update(precedent="p-14cc2f280479"), False),
    case("an undeclared field on the attribution guard",
         lambda b: b.update(attribution_guard={"triggered": False, "cited": "p-14cc2f280479"}), False),
    # Closing the items and leaving the board open is the same defect one level
    # up, and the gate found it there after finding it in the items.
    case("a citation smuggled onto the board itself",
         lambda b: b.update(precedent_cited=["p-14cc2f280479"]), False),
]

# What none of this catches, stated here rather than left for a reader to
# assume otherwise: a passage paraphrased into supporting_evidence with no
# citation at all, and the last two cases above, where the board writes its way
# out of its own list. The first is why the demo checks citations against the
# adapter log. The rest is a judgement the contract cannot make, because a
# schema sees the board and never the view it was drawn from, and it is a
# responder's job rather than a validator's.


def confidence_scale_holds(spec):
    """The briefing's pattern must carry every confidence `assess` can emit.

    `brief` renders a hypothesis with the confidence the board gave it, and its
    output schema requires a confidence word in each entry. If the pattern is
    missing one of the enum's values, the faithful rendering of a hypothesis at
    that confidence is rejected and the model's way out is to change the word,
    so a constraint added to prevent flattening causes it instead. The pattern
    started life missing `likely` and nothing would have said so.
    """
    enum = (spec["tasks"]["assess"]["output"]["properties"]["hypotheses"]
            ["items"]["properties"]["confidence"]["enum"])
    patterns = (spec["tasks"]["brief"]["output"]["properties"]["suspected"]
                ["items"]["allOf"])
    # The case-insensitive spelling is [Ll][Ii][Kk]..., so a value is carried
    # when its letters appear in order as bracketed pairs. Test it the way the
    # validator will rather than parsing the pattern by hand.
    joined = " ".join(p.get("pattern", "") for p in patterns)
    missing = [v for v in enum
               if "".join(f"[{c.upper()}{c.lower()}]" for c in v) not in joined
               and "".join(f"[{c.lower()}{c.upper()}]" for c in v) not in joined
               and "".join(f"[{c.upper()}{c.lower()}]" for c in v).lower() not in joined.lower()]
    if missing:
        print(f"  FAIL the briefing's suspected pattern omits "
              f"{', '.join(missing)}, which assess can emit. A faithful "
              f"rendering at that confidence would be rejected.")
        return 1
    print(f"  ok   the briefing's suspected pattern carries all "
          f"{len(enum)} confidence values assess can emit")
    return 0


def main():
    spec = yaml.safe_load(SPEC.read_text())
    schema = spec["tasks"]["assess"]["output"]
    failures = confidence_scale_holds(spec)
    for name, board, accepted in CASES:
        try:
            validate(instance=board, schema=schema)
            got, why = True, "accepted"
        except ValidationError as exc:
            got, why = False, exc.message
        ok = got == accepted
        failures += not ok
        verdict = "ok  " if ok else "FAIL"
        print(f"  {verdict} {name}: {'accepted' if got else 'rejected'}"
              + ("" if got else f" ({why[:70]})"))
        if not ok:
            print(json.dumps(board, indent=2))
    if failures:
        sys.exit(f"\n{failures} of {len(CASES)} contract invariants did not hold.")
    print(f"\n{len(CASES)} contract invariants hold against {SPEC.name}.")


if __name__ == "__main__":
    main()
