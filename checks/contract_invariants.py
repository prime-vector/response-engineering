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

One rule crosses every spec rather than sitting in one, and is checked here for
the same reason: the confidence scale is a single vocabulary, and a claim keeps
its epistemics only while the agent receiving it can express the word the agent
sending it used. `oa validate` sees each spec alone and cannot notice two of
them drifting apart.

    python3 checks/contract_invariants.py
    python3 checks/contract_invariants.py --self-test

Fails loudly on the first case whose verdict does not match, printing the
board and what the validator said. The self-test drives the scale check's own
branches, which no spec in the tree reaches while the scales agree.
"""

import contextlib
import copy
import io
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
AGENTS = sorted(SPEC.parent.glob("*.yaml"))

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


# A schema can pin the value of a property in exactly two ways, and the
# keywords below are what each way costs this walker.
#
# It can apply a subschema to the property. Then either the property is named
# under `properties`, which the walker reads, or it is reached by indirection
# (`$ref` and its two dynamic forms), by matching its name
# (`patternProperties`), or as one of the ones nobody named
# (`additionalProperties`, `unevaluatedProperties`). Every other subschema
# keyword (`items`, `contains`, `allOf`, `if`/`then`, `dependentSchemas`, ...)
# nests a literal `properties` the walker reaches by recursion.
#
# `propertyNames` is deliberately not here. It applies its subschema to the
# property *names* and never to their values, so it cannot pin a confidence:
# `{propertyNames: {enum: [confidence]}}` accepts `confidence: anything at
# all`. It was in this set for a round, rejected conservatively, which sounds
# harmless and is not: the list stopped being the case split it claims to be,
# and a set with one member nobody can derive is a list again.
#
# Or it can assert the whole object against an instance literal, with `const`
# or `enum`, which pins the property without any subschema at all. Those two
# are the only assertion keywords that carry instance values, and they are
# reported only when the literal is a mapping: `enum` on a string field is the
# normal way to declare a scale, and `const: confirmed` is how the commander's
# rules narrow one.
#
# Enumerating the routes rather than the sightings is what stops this being one
# more keyword every review round. Each entry sits on its own line so a test
# can remove exactly one.
HIDES_A_PROPERTY = (
    "$ref",
    "$dynamicRef",
    "$recursiveRef",
    "patternProperties",
)
APPLIES_TO_UNNAMED = (
    "additionalProperties",
    "unevaluatedProperties",
)
ASSERTS_AN_OBJECT = (
    "const",
    "enum",
)


def holds_a_mapping(literal):
    """Whether an instance literal contains an object at any depth.

    At one level deep this was `any(isinstance(m, dict) for m in members)`, and
    `enum: [[{confidence: high}]]` walked straight past it: a list of lists of
    objects is as valid a literal as a list of objects, and nothing downstream
    recognises a bare `confidence` key outside `properties`. The depth is
    unbounded in the schema, so it is unbounded here.
    """
    if isinstance(literal, dict):
        return True
    if isinstance(literal, list):
        return any(holds_a_mapping(item) for item in literal)
    return False


def declared_scales(specs):
    """Every `confidence` field declared by any task output, with its enum.

    Yields (spec_name, task, path, enum-or-None, readable). A node counts as a
    declaration when it sits under a `properties` mapping and carries a `type`
    or an `enum`. The commander's precedent and attribution rules also write
    `confidence` under `properties`, as a bare `not: {const: confirmed}` with
    no type of its own: those constrain a field declared elsewhere rather than
    declaring one, and counting them would report a scale drift for every rule
    that narrows the scale on purpose. The exemption is any node whose *only*
    key is `not`, which is broader than that one shape and deliberately so: it
    is the absence of anything else, rather than the presence of a `const`,
    that makes a node a constraint rather than a declaration.

    Anything else is reported rather than skipped, with `readable` false, and
    this walker reads exactly one form: `properties.confidence` written inline.
    It resolves no references, matches no patterns, does not follow a
    constraint that applies to properties nobody named, and does not read an
    object out of an instance literal, so every keyword in the three tuples
    above is reported on sight,
    whether or not a confidence is hiding behind it. That is deliberate and it
    is the whole guarantee. `required: [confidence]` beside an
    `additionalProperties` schema declares and constrains a confidence with no
    `properties.confidence` anywhere, and a walker looking for a literal key
    finds nothing to report. The first version reported a
    `$ref` written *on* the confidence field and silently walked past one on
    its parent, which is the shape a shared finding object actually takes:

        $defs: {finding: {properties: {confidence: {enum: [...]}}}}
        tasks: {detect: {output: {properties: {findings: {items:
               {$ref: "#/$defs/finding"}}}}}}

    Nothing was declared, nothing was unreadable, the summary line said every
    declaration shares one scale, and a live field drifted under a green check.
    A form this cannot read is not a form to skip: it is the claim failing.
    """
    def walk(node, path):
        if isinstance(node, dict):
            for key in HIDES_A_PROPERTY:
                if key in node:
                    yield f"{path}/{key}", None, False
            for key in APPLIES_TO_UNNAMED:
                # `false` forbids properties that were not named, which is the
                # opposite of constraining one out of sight.
                if key in node and node[key] is not False:
                    yield f"{path}/{key}", None, False
            for key in ASSERTS_AN_OBJECT:
                # Only when the literal is a mapping. A list of strings under
                # `enum` is a scale being declared, which is the thing this
                # check exists to read rather than a place to hide one.
                if key in node and holds_a_mapping(node[key]):
                    yield f"{path}/{key}", None, False
            for key, value in node.items():
                if isinstance(value, dict) and key == "properties":
                    for field, decl in value.items():
                        if field != "confidence":
                            continue
                        if not isinstance(decl, dict):
                            yield f"{path}/{field}", None, False
                        elif "type" in decl or "enum" in decl:
                            yield f"{path}/{field}", decl.get("enum"), True
                        elif set(decl) != {"not"}:
                            # Only a bare narrowing rule is exempt. `not`
                            # beside anything else is a node doing something
                            # this does not model.
                            yield f"{path}/{field}", None, False
                yield from walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, f"{path}[{index}]")

    for name in sorted(specs):
        for task, definition in sorted((specs[name].get("tasks") or {}).items()):
            if "output" not in definition:
                continue
            for path, enum, readable in walk(definition["output"], task):
                yield name, task, path, enum, readable


def board_scale(spec):
    """The commander's hypotheses confidence, by path rather than by search.

    It is the scale every other declaration is held to, so it is read from the
    one place it lives rather than found. A scan takes whichever confidence
    comes first under `assess`, and `assess` already declares more than one:
    the attribution and precedent rules write a `confidence` of their own. Add
    a container ahead of `hypotheses`, or remove `hypotheses` while another
    remains, and the reference silently becomes a different field, after which
    the suite agrees with itself about the wrong vocabulary and every spec
    passes against a scale nobody chose.

    Renaming `hypotheses` is the opposite case and the reason this is a path.
    A scan would follow the rename and carry on; this stops finding anything
    and says so. Losing the reference is not a thing to survive quietly.

    Returns (enum-or-None, whether the field is declared at all, elsewhere):
    a board that declares no confidence and a board that declares it as a bare
    string are different defects, and reporting either as the other sends the
    fix to the wrong file. `elsewhere` is read only when the reference path is
    absent and lists two kinds of path separately: the confidences the walker
    actually read under `assess`, so a hypotheses object wrapped in `allOf`,
    or renamed, is reported as a declaration this reads by path and did not
    find rather than as one that does not exist; and the forms it refuses to
    read, which may hold the board's confidence or nothing, and which
    establish neither presence nor absence. A sentinel is not a sighting.
    Right verdict either way; the message is what sends a reader to the
    right fix.
    """
    node = spec
    for key in ("tasks", "assess", "output", "properties", "hypotheses",
                "items", "properties", "confidence"):
        if not isinstance(node, dict) or key not in node:
            assess = ((spec.get("tasks") or {}).get("assess") or {}) \
                if isinstance(spec, dict) else {}
            found = list(declared_scales({"assess-only": {"tasks": {"assess": assess}}})) \
                if isinstance(assess, dict) and "output" in assess else []
            elsewhere = {"declared": [path for _, _, path, _, readable in found if readable],
                         "unreadable": [path for _, _, path, _, readable in found if not readable]}
            return None, False, elsewhere
        node = node[key]
    if not isinstance(node, dict):
        # `confidence: true` is a valid schema meaning anything. Reading
        # `.get` off it raises, and a check that dies prints no verdicts for
        # anyone to read: the exact failure a mutation harness exists to
        # catch, left in the one path every other case depends on.
        return None, True, {"declared": [], "unreadable": []}
    return node.get("enum"), True, {"declared": [], "unreadable": []}


def confidence_scales_hold(specs):
    """Every declared confidence enum is the commander's board's, exactly.

    This was a regex over a free string, and three review rounds went into it:
    word boundaries so `likely` did not match inside `unlikely`, lookbehinds so
    it did not match inside `not likely`, then casing on those lookbehinds so it
    did not match inside `NOT LIKELY`. Each round closed one spelling of one
    hole. The hole was that a caveat carried as prose can be negated by prose,
    and no pattern closes that.

    Every confidence a spec declares is an enum now, which is what CLAUDE.md
    required of any output carrying a claim from the start. So what is left to
    check is the thing a schema cannot notice: that the scales have not drifted
    apart. They are one vocabulary crossing five specs, and a claim keeps its
    epistemics only while the agent receiving it can express the word the agent
    sending it used. An analyst that can say `supported` handing a board that
    cannot leaves the model to pick a different word, and a briefing that cannot
    express `likely` rejects the faithful rendering of a hypothesis at that
    confidence.

    What this does not check: whether an output that carries a claim declares a
    confidence at all. It holds the ones that are declared. Presence is the rule
    in CLAUDE.md with the Comms agent as its one written exception, and nothing
    here enforces it.

    Returns (failures, declarations checked).
    """
    found = list(declared_scales(specs))
    declarations = [d for d in found if d[4]]
    board, declared, elsewhere = board_scale(specs.get(SPEC.name) or {})
    if not declared:
        # Three different fixes. With a confidence read somewhere else the
        # reference is read by path and the path has moved, most likely a
        # container such as allOf ahead of the field, and adding a second
        # declaration is the wrong first move. With only a form this check
        # refuses to read, nothing is established either way: the board's
        # confidence may be behind it, and the form is what to fix first.
        # With nothing at all, the declaration is missing.
        if elsewhere["declared"]:
            print(f"  FAIL {SPEC.name} declares no confidence at the reference "
                  f"path assess/hypotheses/items/confidence, which this check "
                  f"reads by path and not by search; a confidence exists "
                  f"elsewhere under assess at {', '.join(elsewhere['declared'])}, "
                  f"so the path has moved rather than the declaration gone missing")
        elif elsewhere["unreadable"]:
            print(f"  FAIL {SPEC.name} declares no confidence at the reference "
                  f"path assess/hypotheses/items/confidence, and the only thing "
                  f"under assess that could hold one is a form this check cannot "
                  f"read, at {', '.join(elsewhere['unreadable'])}: neither present "
                  f"nor absent until that form is replaced")
        else:
            print(f"  FAIL {SPEC.name} declares no confidence on assess/hypotheses "
                  f"and none anywhere under assess, so there is no scale for "
                  f"anything else to be held to")
        return 1, len(declarations)
    if board is None:
        print("  FAIL the board's confidence is not an enum, so any string is "
              "a valid confidence and there is no scale to hold anything to")
        return 1, len(declarations)

    failures = 0
    for name, task, path, enum, readable in found:
        where = f"{name} {path}"
        if not readable:
            print(f"  FAIL {where} is declared in a form this check cannot "
                  f"read, with no type, no enum and no narrowing rule: it may "
                  f"be a scale, and nothing here is holding it to the board's")
            failures += 1
        elif enum is None:
            # Absent rather than different: a confidence declared as a bare
            # string accepts anything, which is the failure this whole change
            # was about, and it is not a drift the comparison below would see.
            print(f"  FAIL {where} is not an enum, so any string is a valid "
                  f"confidence and this agent can invent one")
            failures += 1
        elif enum != board:
            print(f"  FAIL {where} declares {enum} against the board's "
                  f"{board}: a claim one can carry is one the other cannot "
                  f"express, and the model's way out is a different word")
            failures += 1
    if not failures:
        print(f"  ok   every confidence declared in .agents/ is the board's "
              f"scale, all {len(board)} values in the same order, "
              f"{len(declarations)} declarations")
    return failures, len(declarations)


def scale_self_test():
    """Drive the branches above, which no spec in the tree reaches.

    Every case asserts the reason it failed and not merely that it did: a
    drifted scale and a bare string are different defects with different fixes,
    and a suite that cannot tell them apart passes a check reporting either one
    for the other.
    """
    def spec(scale, task="assess", container="hypotheses"):
        field = {"type": "string"}
        if scale is not None:
            field["enum"] = list(scale)
        return {"tasks": {task: {"output": {"properties": {container: {
            "type": "array", "items": {"type": "object",
                                       "properties": {"confidence": field}}}}}}}}

    def with_rule(base):
        """The shape the commander's precedent rule uses: `confidence` under a
        `properties` mapping with no type, narrowing a field declared above it.
        Counted as a declaration it would report a drift for every rule whose
        whole job is to narrow the scale."""
        base["tasks"]["assess"]["output"]["properties"]["cited"] = {
            "type": "array", "contains": {"properties": {
                "confidence": {"not": {"const": "confirmed"}}}}}
        return base

    def by_ref(base):
        """A confidence with no type, no enum and no narrowing rule: the shape
        a `$ref` or a `oneOf` wrapper would leave. Skipped rather than
        reported, it would be a spec whose scale nothing compares, under a
        summary line saying every declaration shares one."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        (base["tasks"][task]["output"]["properties"][container]["items"]
         ["properties"]["confidence"]) = {"$ref": "#/definitions/scale"}
        return base

    def shared_object(base):
        """The shape that got past the first version: the confidence is real
        and fully declared, but it lives in a `$defs` block the walker never
        visits, reached by a `$ref` on the container. Nothing declared, nothing
        unreadable, and a green summary line saying they all agree."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        base["$defs"] = {"finding": base["tasks"][task]["output"]["properties"]
                         [container]["items"]}
        base["tasks"][task]["output"]["properties"][container]["items"] = {
            "$ref": "#/$defs/finding"}
        return base

    def pattern_site(base):
        """A `patternProperties` mapping added beside a correctly declared
        confidence, which is what makes this a test of the sentinel rather
        than of the pattern: the walker matches key names, so it cannot know
        whether a pattern declares a second confidence or nothing at all, and
        the guarantee is that its presence fails the check either way."""
        task, = base["tasks"]
        base["tasks"][task]["output"]["patternProperties"] = {
            "^confidence$": {"type": "string"}}
        return base

    def boolean_site(base):
        """`confidence: true` is a valid JSON Schema meaning "anything". It is
        not a dict, so the first version skipped it while it accepted every
        word in the language."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        (base["tasks"][task]["output"]["properties"][container]["items"]
         ["properties"]["confidence"]) = True
        return base

    def wrapped_in_allof(base):
        """The hypotheses object under `allOf`, so `items` carries no literal
        `properties` key and the reference path stops before the confidence
        that is right there. Fail-closed before this case existed, with a
        message saying the declaration was missing: right verdict, wrong
        reason, and the fix a reader would try first is to add a second one."""
        items = base["tasks"]["assess"]["output"]["properties"]["hypotheses"]["items"]
        base["tasks"]["assess"]["output"]["properties"]["hypotheses"]["items"] = {
            "allOf": [items]}
        return base

    def unreadable_board(base):
        """The hypotheses object behind a `$ref`, with no confidence the walker
        can read anywhere under assess. A sentinel is not a sighting: the
        board's confidence may be behind it or nothing may be, and a message
        saying one exists elsewhere sends the reader after a declaration the
        check never saw. The gate on PR #50 found the first version doing
        exactly that for every one of the eight sentinel keywords."""
        base["tasks"]["assess"]["output"]["properties"]["hypotheses"]["items"] = {
            "$ref": "#/$defs/hypothesis"}
        return base

    def sentinel_beside_declaration(base):
        """A sentinel beside a readable declaration elsewhere: the read one is
        the path-moved message's evidence, and the sentinel must not be
        promoted to a sighting beside it."""
        base = wrapped_in_allof(base)
        base["tasks"]["assess"]["output"]["properties"]["notes"] = {
            "const": {"status": "ok"}}
        return base

    def no_confidence_anywhere(base):
        """A board with no confidence under assess at all, which is the other
        reading of the same absent path and needs the other message."""
        items = base["tasks"]["assess"]["output"]["properties"]["hypotheses"]["items"]
        del items["properties"]["confidence"]
        return base

    def bare_wrapper(base):
        """A confidence declared as a `oneOf` wrapper and nothing else: no type,
        no enum, no narrowing rule and no reference keyword. Only the
        `set(decl) != {"not"}` branch can report it, so this is the case that
        branch owns; `by_ref` and `rule_plus` trip it and a `$ref` sentinel
        together, and a count asserted on them cannot say which fired."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        (base["tasks"][task]["output"]["properties"][container]["items"]
         ["properties"]["confidence"]) = {"oneOf": [{"enum": ["high", "low"]}]}
        return base

    def rule_plus(base):
        """A narrowing rule with something else beside it. Exempting any node
        carrying a `not` would wave this through whatever the something is."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        (base["tasks"][task]["output"]["properties"][container]["items"]
         ["properties"]["confidence"]) = {"not": {"const": "confirmed"},
                                          "$ref": "#/$defs/scale"}
        return base

    def hidden_by(base, keyword, value):
        """A confidence constrained with no `properties.confidence` to find.
        `required` names it, the keyword constrains it, and a walker matching
        literal keys sees a findings object with no confidence in it."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        base["tasks"][task]["output"]["properties"][container]["items"] = {
            "type": "object", "required": ["confidence"], keyword: value}
        return base

    def forbids_unnamed(base):
        """`additionalProperties: false` forbids what was not named instead of
        constraining it, so it hides nothing and must not be reported. Nine of
        these sit in the specs today and every one would go red."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        (base["tasks"][task]["output"]["properties"][container]["items"]
         ["additionalProperties"]) = False
        return base

    def names_only(base):
        """`propertyNames` beside a correct declaration. It constrains names
        and never values, so it cannot pin a confidence and must not be
        reported: this case is what makes re-adding it to the set cost
        something, since a conservative rejection nobody can derive is how the
        list stopped being a case split the first time."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        (base["tasks"][task]["output"]["properties"][container]["items"]
         ["propertyNames"]) = {"enum": ["confidence", "statement"]}
        return base

    def asserts_object(base, keyword, literal):
        """A whole-object assertion. `const: {confidence: high}` pins the
        property with no subschema anywhere, so there is no `properties` for a
        walker to find and nothing to recurse into that looks like one."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        base["tasks"][task]["output"]["properties"][container]["items"] = {
            keyword: literal}
        return base

    def scalar_assertions(base):
        """The shapes the specs really use: a string `enum` declaring a scale
        and a scalar `const` narrowing one. Neither hides an object and
        neither may be reported, or nine narrowing rules and six declarations
        go red at once."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        items = base["tasks"][task]["output"]["properties"][container]["items"]
        items["properties"]["severity"] = {"type": "string",
                                           "enum": ["low", "high"]}
        items["properties"]["closed"] = {"const": "confirmed"}
        return base

    def inside_a_list(base):
        """A declaration nested in a list, which is how `allOf` and friends
        carry subschemas. Only the walker's list branch reaches it."""
        task, = base["tasks"]
        container, = base["tasks"][task]["output"]["properties"]
        items = base["tasks"][task]["output"]["properties"][container]["items"]
        items["allOf"] = [{"properties": {"confidence": dict(
            items["properties"]["confidence"])}}]
        return base

    def decoy_first(base):
        """A second confidence in `assess`, ordered ahead of `hypotheses` and
        carrying a different scale. A scan would take this one as the
        reference and report the real board as the drift; reading by path
        takes the board and reports this one. The FAIL line names which."""
        output = base["tasks"]["assess"]["output"]
        board = output["properties"].pop("hypotheses")
        output["properties"] = {
            "early": {"type": "array", "items": {"type": "object", "properties": {
                "confidence": {"type": "string", "enum": ["low", "high"]}}}},
            "hypotheses": board}
        return base

    def boolean_board(base):
        """`confidence: true` on the reference path itself. `board_scale`
        walks a fixed path and read `.get` off whatever it landed on, so this
        raised instead of reporting, and a crash prints no verdicts at all."""
        (base["tasks"]["assess"]["output"]["properties"]["hypotheses"]["items"]
         ["properties"]["confidence"]) = True
        return base

    real = yaml.safe_load(SPEC.read_text())
    # Derived from the spec rather than typed out, so a change to the scale
    # cannot quietly change what these cases measure, and read by path rather
    # than through the scanner these cases are testing.
    scale, declared, _ = board_scale(real)
    if not declared or scale is None:
        # Loudly, because a self-test that cannot find the scale it derives
        # from otherwise dies on a TypeError inside a case, and a mutation
        # that crashes the suite prints no verdicts for anyone to read.
        sys.exit(f"  FAIL {SPEC.name} declares no confidence enum on "
                 f"assess/hypotheses, so these cases have no scale to derive")
    cases = [
        ("every scale is the board's",
         {SPEC.name: spec(scale), "other.yaml": spec(scale, "detect", "findings")},
         0, "in the same order", 2),
        ("another spec declares a bare string",
         {SPEC.name: spec(scale), "other.yaml": spec(None, "detect", "findings")},
         1, "is not an enum", 2),
        ("another spec is missing a value",
         {SPEC.name: spec(scale), "other.yaml": spec(scale[:-1], "detect", "findings")},
         1, "against the board's", 2),
        ("another spec has the values in a different order",
         {SPEC.name: spec(scale), "other.yaml": spec(list(reversed(scale)), "detect", "findings")},
         1, "against the board's", 2),
        ("the board itself is a bare string",
         {SPEC.name: spec(None), "other.yaml": spec(scale, "detect", "findings")},
         1, "the board's confidence is not an enum", 2),
        ("the board declares its confidence somewhere other than the path",
         {SPEC.name: spec(scale, container="suspected"),
          "other.yaml": spec(scale, "detect", "findings")},
         1, "elsewhere under assess at assess/properties/suspected/items/"
            "confidence", 2),
        ("the board's hypotheses object is wrapped in allOf",
         {SPEC.name: wrapped_in_allof(spec(scale)),
          "other.yaml": spec(scale, "detect", "findings")},
         1, "elsewhere under assess at assess/properties/hypotheses/items/"
            "allOf[0]/confidence", 2),
        ("the board's hypotheses object is an unreadable form and nothing else declares one",
         {SPEC.name: unreadable_board(spec(scale)),
          "other.yaml": spec(scale, "detect", "findings")},
         1, "neither present nor absent until that form is replaced", 1),
        ("a sentinel beside a read declaration is not a second sighting",
         {SPEC.name: sentinel_beside_declaration(spec(scale)),
          "other.yaml": spec(scale, "detect", "findings")},
         1, "elsewhere under assess at assess/properties/hypotheses/items/"
            "allOf[0]/confidence, so", 2),
        ("the board declares no confidence anywhere under assess",
         {SPEC.name: no_confidence_anywhere(spec(scale)),
          "other.yaml": spec(scale, "detect", "findings")},
         1, "and none anywhere under assess", 1),
        ("a confidence that is only a oneOf wrapper",
         {SPEC.name: spec(scale),
          "other.yaml": bare_wrapper(spec(scale, "detect", "findings"))},
         1, "form this check cannot read", 1),
        ("a second task in the same spec drifts",
         {SPEC.name: {"tasks": {
             "assess": spec(scale)["tasks"]["assess"],
             "brief": spec(scale[:2], "brief", "suspected")["tasks"]["brief"]}}},
         1, "against the board's", 2),
        ("a rule narrowing the scale is not a declaration",
         {SPEC.name: with_rule(spec(scale))},
         0, "in the same order", 1),
        ("a confidence in a form the check cannot read",
         {SPEC.name: spec(scale), "other.yaml": by_ref(spec(scale, "detect", "findings"))},
         # Twice: once as a confidence node declaring nothing this reads, once
         # as the reference itself. Both lines are true and both name a real
         # path, and collapsing them would mean deciding which of the two
         # reasons to withhold.
         2, "form this check cannot read", 1),
        ("a confidence in a shared object reached by $ref",
         {SPEC.name: spec(scale),
          "other.yaml": shared_object(spec(scale, "detect", "findings"))},
         1, "form this check cannot read", 1),
        ("a confidence declared through patternProperties",
         {SPEC.name: spec(scale),
          "other.yaml": pattern_site(spec(scale, "detect", "findings"))},
         1, "form this check cannot read", 2),
        ("a confidence declared as a boolean schema",
         {SPEC.name: spec(scale),
          "other.yaml": boolean_site(spec(scale, "detect", "findings"))},
         1, "form this check cannot read", 1),
        ("a confidence constrained by additionalProperties, never named",
         {SPEC.name: spec(scale), "other.yaml": hidden_by(
             spec(scale, "detect", "findings"), "additionalProperties",
             {"type": "string", "enum": ["high", "low"]})},
         1, "form this check cannot read", 1),
        ("a confidence constrained by unevaluatedProperties",
         {SPEC.name: spec(scale), "other.yaml": hidden_by(
             spec(scale, "detect", "findings"), "unevaluatedProperties",
             {"enum": ["high", "low"]})},
         1, "form this check cannot read", 1),
        ("propertyNames constrains names, so it is not in the set",
         {SPEC.name: spec(scale),
          "other.yaml": names_only(spec(scale, "detect", "findings"))},
         0, "in the same order", 2),
        ("a confidence pinned by an enum of arrays of objects",
         {SPEC.name: spec(scale), "other.yaml": asserts_object(
             spec(scale, "detect", "findings"), "enum",
             [[{"confidence": "high"}]])},
         1, "form this check cannot read", 1),
        ("a confidence pinned by a const nested two deep",
         {SPEC.name: spec(scale), "other.yaml": asserts_object(
             spec(scale, "detect", "findings"), "const",
             [[{"confidence": "high"}]])},
         1, "form this check cannot read", 1),
        ("a confidence behind a $dynamicRef",
         {SPEC.name: spec(scale), "other.yaml": hidden_by(
             spec(scale, "detect", "findings"), "$dynamicRef", "#finding")},
         1, "form this check cannot read", 1),
        ("additionalProperties false is not a hiding place",
         {SPEC.name: spec(scale),
          "other.yaml": forbids_unnamed(spec(scale, "detect", "findings"))},
         0, "in the same order", 2),
        ("a confidence pinned by a whole-object const",
         {SPEC.name: spec(scale), "other.yaml": asserts_object(
             spec(scale, "detect", "findings"), "const", {"confidence": "high"})},
         1, "form this check cannot read", 1),
        ("a confidence pinned by an enum of objects",
         {SPEC.name: spec(scale), "other.yaml": asserts_object(
             spec(scale, "detect", "findings"), "enum", [{"confidence": "high"}])},
         1, "form this check cannot read", 1),
        ("a scalar const and a string enum are not object assertions",
         {SPEC.name: spec(scale),
          "other.yaml": scalar_assertions(spec(scale, "detect", "findings"))},
         0, "in the same order", 2),
        ("a confidence behind a $recursiveRef",
         {SPEC.name: spec(scale), "other.yaml": hidden_by(
             spec(scale, "detect", "findings"), "$recursiveRef", "#")},
         1, "form this check cannot read", 1),
        ("additionalProperties true is a hiding place",
         {SPEC.name: spec(scale), "other.yaml": hidden_by(
             spec(scale, "detect", "findings"), "additionalProperties", True)},
         1, "form this check cannot read", 1),
        ("a declaration nested inside a list",
         {SPEC.name: spec(scale),
          "other.yaml": inside_a_list(spec(scale, "detect", "findings"))},
         0, "in the same order", 3),
        ("a second confidence in assess, declared first",
         # Names the decoy, not the board: if the reference had been scanned
         # rather than read by path, these two swap and the message would
         # report the real board as the field that drifted.
         {SPEC.name: decoy_first(spec(scale))},
         1, "assess/properties/early", 2),
        ("the board's confidence is a boolean schema",
         {SPEC.name: boolean_board(spec(scale)),
          "other.yaml": spec(scale, "detect", "findings")},
         1, "the board's confidence is not an enum", 1),
        ("a narrowing rule with another keyword beside it",
         {SPEC.name: spec(scale),
          "other.yaml": rule_plus(spec(scale, "detect", "findings"))},
         2, "form this check cannot read", 1),
    ]

    failures = 0
    for name, specs, want, reason, want_declared in cases:
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                got, declared = confidence_scales_hold(specs)
            output = buffer.getvalue()
        except Exception as exc:
            # A case that raises is a case that failed, and the suite has to
            # survive it: an uncaught exception here takes every later case
            # with it and prints no verdicts, which is the same hole the guard
            # in `board_scale` closes. Report the crash as the reason.
            got, declared = None, None
            output = buffer.getvalue() + f"  FAIL raised {exc!r}\n"
        ok = got == want and reason in output and declared == want_declared
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"       wanted {want} failure(s) over {want_declared} "
                  f"declarations, reported as {reason!r}; got {got} over "
                  f"{declared} from:\n{output.rstrip()}")
    if failures:
        sys.exit(f"\n{failures} of {len(cases)} scale self-tests failed.")
    print(f"\n{len(cases)} scale self-tests pass: the check reports a bare "
          f"string, a drifted scale, a reordered one and a form it cannot "
          f"read, each for its own reason, and does not report the rule that "
          f"narrows the scale on purpose.")
    return 0


def main():
    if "--self-test" in sys.argv:
        return scale_self_test()
    specs = {path.name: yaml.safe_load(path.read_text()) for path in AGENTS}
    schema = specs[SPEC.name]["tasks"]["assess"]["output"]
    scale_failures, declarations = confidence_scales_hold(specs)
    failures = 0
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
    # Counted apart, not summed: they are two different claims with two
    # different fixes, and a total says neither. A drifted scale is one line in
    # one spec; a board the contract accepts that it should not is the contract.
    if failures or scale_failures:
        sys.exit(f"\n{failures} of {len(CASES)} contract invariants did not "
                 f"hold, and {scale_failures} of {declarations} confidence "
                 f"declarations are not the board's scale.")
    print(f"\n{len(CASES)} contract invariants hold against {SPEC.name}, and "
          f"the {declarations} confidence declarations in .agents/ share one "
          f"scale.")


if __name__ == "__main__":
    main()
