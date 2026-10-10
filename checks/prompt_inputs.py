#!/usr/bin/env python3
"""Every variable the runner will substitute is a required input, and back.

    python3 checks/prompt_inputs.py

Free, no key, no model. CI runs it.

The runner substitutes `{{ placeholders }}` only from keys present in the
input, and it applies no input-schema defaults. A referenced variable that is
not a required field therefore reaches the model as the literal text
`{{ evidence }}`, and the run does not fail: it degrades, silently, into a
different task that still returns something shaped like an answer.

That is not hypothetical. The commander's `brief` task had no prompts of its
own, so it inherited the root pair written for `assess`: ten placeholders, one
required input, and an output shape belonging to another task. It validated
green, it was in the spec from the beginning, and nobody noticed because it had
never been run. `oa validate` cannot see this, because nothing about it is
invalid; it is a relationship between two parts of a spec that are each fine
alone.

WHAT THE RUNNER ACTUALLY DOES, because a check that models it loosely passes
the shapes it was written to catch. `_resolve_prompts` resolves `system` and
`user` **independently**, each falling through four layers: CLI override, the
task's inline `prompts`, a Style B `prompts.<task>` map, then the root pair. So
a task declaring only `prompts.system` still takes its user template from the
root, which is the original defect wearing a prompts block. And **only the user
template is substituted**: the system prompt is returned raw, so a placeholder
in one is never filled, whatever the inputs are. Substitution matches three
spellings, `{key}`, `{{ key }}` and `{{ input.key }}`.

THE OTHER HALF OF THE SAME DEFECT. A prompt written for another task does not
only reference the wrong variables, it asks for the wrong answer: the pair
`brief` inherited told the model to produce `assess`'s output shape, against
`brief`'s output schema. Variables and inputs agreeing does not rule that out,
so the resolved prompts must also name every field the task's own output
requires at the top level. Nested requirements, `suspected[].falsifying_test`
and its siblings, are not traversed: every task here states its shape as a flat
key list, and walking arbitrary schema nesting to decide what a prompt ought to
mention invents an obligation the prompts do not have. A prompt that asks for the right shape names it; one written for a
different task does not. That holds for every task in this repository, which is
what makes it a check rather than a preference. Matching is on word boundaries
rather than by substring: a field called `r` is inside "produce", and substring
matching would credit a prompt with naming fields it has never heard of. One honest gap remains, that a field named for a common
word is matched by prose meaning something else, `outstanding` in the root pair
being the live example. That costs a field, not the check, because a prompt
written for another task misses the rest.

WHAT IT CHECKS ABOUT THE KEY LIST, AND WHAT IT DOES NOT. Where a prompt
enumerates the keys it wants, that list is the instruction the model obeys, and
a required field absent from it means a compliant response fails validation.
That is checked, and it is what shipped: `standing_conditions` was required,
appeared in a paragraph of rules explaining what it was for, and was missing
from the list at the end. The converse, a key the schema does not allow, is not
checked: these prompts qualify their lists in prose and no parse separates a
key from a qualifier reliably enough to accuse a correct spec.

ENUM VOCABULARY. Every string value of every inline output enum is checked
against this same resolved pair, at any schema depth: each must occur
case-sensitively as a whole word in either prompt. There is no exemption. A
first version exempted an enum the task's input declared under the same
property name, on the argument that the vocabulary then arrived through typed
input; a schema cannot promise that, since the instance may carry none of the
words (an empty board carries no confidence), so that arm was an exemption
keyed on a walk coincidence and it is gone. An enum with no string value is
skipped and counted as such. The walk descends only where the 2020-12
vocabulary puts a schema, by the structure of a keyword's value, the split
checks/contract_invariants.py moves to in PR #50; instance data, unknown
annotations and the keys of a name mapping are never read as schemas. This
checks presence, never whether the model reads a value. References are not
resolved.

WHAT THIS CANNOT SEE. `--system-prompt` and `--user-prompt` replace a prompt
wholesale at the command line, and a spec cannot know what they will carry.
They are not equivalent: substitution runs after override resolution, so a
`--user-prompt` is substituted like any template and only a `--system-prompt`
stays raw. The override files this repository keeps are checked directly below,
for placeholders and for the output shape they ask for; an override composed
anywhere else is outside what a spec-level check can reach, and CLAUDE.md's
note that CLI access is privileged covers the rest.
"""

import pathlib
import re
import sys

import yaml

SPECS = sorted(pathlib.Path(".agents").glob("*.yaml"))
# The override prompts this repository keeps in the tree. A CLI override is
# unsubstituted system text by definition, so any placeholder in one is dead.
OVERRIDES = sorted(pathlib.Path("demos").glob("*-prompt.txt"))

# Substitution as the runner performs it, for the key shapes these specs use.
# The runner replaces literally, so an input named `9key` or `team/name` is
# substituted and is not matched below: the single-brace arm is bounded to
# identifier shapes because these prompts quote JSON at the model and anything
# looser reads `{"triggered": false}` as a placeholder. Every input key in this
# tree is an identifier, and a spec introducing one that is not gets no help
# from this check, which is a smaller promise than modelling substitution in
# general and is the one that can be kept. The runner does
# three literal replaces per input key: `{key}`, `{{ key }}` and
# `{{ input.key }}`, with exactly one space inside the braces. So a regex over
# `\s*` accepts `{{  board  }}`, which the runner leaves untouched, and a key
# pattern of `\w+` misses `{{ my-key }}`, which it substitutes happily. Both
# directions of that mismatch let a broken spec pass, which is the one thing
# this check may not do.
#
# Two questions are therefore asked separately. Would the runner substitute
# this occurrence, given the required inputs? And is there any placeholder
# shaped text left that it would not?
#
# The single-brace arm allows spaces inside the braces, because `{ board }` is
# not a form the runner replaces and is exactly the occurrence a check must not
# walk past: the runner leaves it literal, and a pattern demanding a word
# character straight after the brace never sees it. It is bounded to something
# shaped like an identifier rather than anything brace-delimited, because these
# prompts quote JSON at the model and `{"triggered": false}` is an example,
# not a placeholder someone misspelled.
BRACED = re.compile(r"{{[^{}]*}}|(?<!{){\s*[A-Za-z_][\w.-]*\s*}(?!})")


def substitutions(key):
    """Exactly what the runner would replace for this input key."""
    return (f"{{{key}}}", "{{ " + key + " }}", "{{ input." + key + " }}")


def unsubstituted(text, required):
    """Placeholder-shaped text the runner would leave in front of the model.

    Every occurrence is checked against the substitutions the runner would
    actually perform, so a misspaced or misspelled placeholder is caught as
    readily as one naming a variable that is not an input.
    """
    live = {form for key in required for form in substitutions(key)}
    return sorted({m for m in BRACED.findall(text or "") if m not in live})


# The prompts here end with an explicit key list, "exactly these top-level keys
# and no others: a, b, c". Where one is present it is the instruction the model
# follows, and it is the thing that has to agree with the schema: naming a field
# anywhere in the prompt is far too weak, because `standing_conditions` appeared
# in a paragraph of rules explaining what it was for while the key list the
# model obeys omitted it. A compliant response then failed validation, and this
# check passed the spec.
KEY_LIST = re.compile(
    r"exactly these\s+top-level keys(?:\s+and no others)?:\s*(.+?)(?:\.|\n\s*\n|$)",
    re.S)
# A key is a bare identifier. The list is followed by prose in most of these
# prompts, "and optionally caveats", "plus cause_basis only when cause_status
# is confirmed", and a matcher that takes everything up to the full stop reads
# those words as key names and reports fields the schema does not allow. Take
# the identifiers and drop the qualifiers, which is what the model does too.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def enumerated_keys(text):
    """The keys a prompt explicitly instructs, or None if it enumerates none."""
    match = KEY_LIST.search(text or "")
    if not match:
        return None
    keys = set()
    for chunk in match.group(1).replace("\n", " ").split(","):
        for word in chunk.replace(" and ", " ").replace(" plus ", " ").split():
            if IDENTIFIER.match(word):
                keys.add(word)
    return keys or None


def names(text, field):
    """Whether this text names this output field, on a word boundary.

    Not a substring: a field called `r` is inside "produce" and one called `id`
    is inside "consider", so substring matching credits a prompt with naming
    fields it has never heard of, which is the direction that makes the check
    useless. The self-test below catches exactly that.
    """
    return re.search(rf"\b{re.escape(field)}\b", text or "") is not None


def reads(text, key):
    """Whether the runner would put this key's value into this template."""
    return any(form in (text or "") for form in substitutions(key))


def resolve(spec_data, task_name):
    """(system, user, system_layer, user_layer), as `_resolve_prompts` would.

    Per key, not per block. Resolving the pair together is the bug this
    function exists to avoid: a task with an inline system and no inline user
    takes the root's user template, and a check that treats `prompts:` as
    all-or-nothing never looks at it.
    """
    tasks = spec_data.get("tasks") or {}
    inline = (tasks.get(task_name) or {}).get("prompts") or {}
    prompts = spec_data.get("prompts") or {}
    mapped = prompts.get(task_name) if isinstance(prompts.get(task_name), dict) else {}

    def pick(key, default=""):
        for layer, source in (("own", inline), ("mapped", mapped), ("root", prompts)):
            value = source.get(key)
            if value:
                return str(value), layer
        return default, "default"

    system, system_layer = pick("system")
    user, user_layer = pick("user", "{{ input }}")
    return system, user, system_layer, user_layer


# Where the JSON Schema 2020-12 vocabularies put a schema, by the structure
# of the keyword's value: the dialect `jsonschema.validate` applies when a
# schema names none, which is how the CLI validates. The walk descends
# through these and nothing else, so `const`, `default`, `required`, an
# unknown annotation and the compatibility `dependencies` are never read
# into however schema-shaped their values look, and under a name mapping
# every key is the author's. `definitions` is not in this dialect: the
# validator treats it as an unknown annotation, so an enum under it is not
# applied and is not read. The split checks/contract_invariants.py moves to
# in PR #50, for the same reason: a list of exceptions to "descend everywhere"
# grows by one member per review round, and the vocabulary's answer does not.
ONE_SCHEMA = ("additionalProperties", "unevaluatedProperties", "propertyNames",
              "items", "contains", "unevaluatedItems", "not", "if", "then",
              "else", "contentSchema")
SCHEMA_LIST = ("allOf", "anyOf", "oneOf", "prefixItems")
NAME_MAPPINGS = ("$defs", "properties", "patternProperties", "dependentSchemas")


def schema_enums(schema, property_name=None, path="$"):
    """Inline enums with their enclosing property name and schema path.

    References are not resolved. Names belong to properties, not definitions
    or patterns: copying a definition name is not copying a property.
    """
    if not isinstance(schema, dict):
        return
    if "enum" in schema:
        yield property_name, schema["enum"], path + ".enum"
    for key in ONE_SCHEMA:
        if key in schema:
            yield from schema_enums(schema[key], property_name, f"{path}.{key}")
    for key in SCHEMA_LIST:
        if isinstance(schema.get(key), list):
            for index, child in enumerate(schema[key]):
                yield from schema_enums(child, property_name, f"{path}.{key}[{index}]")
    for key in NAME_MAPPINGS:
        if isinstance(schema.get(key), dict):
            for name, child in schema[key].items():
                owner = name if key == "properties" else property_name
                yield from schema_enums(child, owner, f"{path}.{key}[{name!r}]")


def enum_named(text, value):
    """Literal vocabulary, bounded so negations and suffixes cannot match."""
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text) is not None


def check_enums(task, system, user, label):
    """Every string value an output enum pins must reach the model through
    its prompts. A mixed enum is checked on its strings: they are words the
    model must choose like any other, and a number beside them exempts
    nothing."""
    named = skipped = failures = 0
    for _, values, path in schema_enums(task.get("output") or {}):
        words = [v for v in values if isinstance(v, str)] if isinstance(values, list) else []
        if not words:
            skipped += 1
            continue
        named += 1
        missing = [v for v in words if not (enum_named(system, v) or enum_named(user, v))]
        if missing:
            failures += 1
            print(f"  FAIL {label} output {path} enum missing values: "
                  f"{missing!r}. Each value must occur as a case-sensitive "
                  f"whole word in the resolved system or user prompt.")
    if not failures:
        print(f"  ok   {label} enums: {named} named in the prompts, {skipped} with no string value")
    return failures


def check_spec(path):
    spec = yaml.safe_load(path.read_text())
    failures = 0
    for name, task in (spec.get("tasks") or {}).items():
        system, user, system_layer, user_layer = resolve(spec, name)
        required = set(((task.get("input") or {}).get("required")) or [])
        label = f"{path.name}:{name}"

        # Nothing in a system prompt is substituted, so a placeholder there is
        # dead text whatever the inputs are. Not a comparison against inputs.
        in_system = unsubstituted(system, set())
        if in_system:
            failures += 1
            print(f"  FAIL {label} system prompt ({system_layer}) contains "
                  f"{', '.join(in_system)}. The runner substitutes the user "
                  f"template only, so these reach the model literally.")

        left_over = unsubstituted(user, required)
        if left_over:
            failures += 1
            print(f"  FAIL {label} user template ({user_layer}) leaves "
                  f"{', '.join(left_over)} unsubstituted: not a required "
                  f"input, or not a form the runner replaces.")

        # The output half. Checked against the resolved pair rather than the
        # user template alone: an instruction naming the shape is as good in
        # either, since it is read by the model either way even though only
        # one of them is substituted.
        out_required = set(((task.get("output") or {}).get("required")) or [])
        prompts_text = system + " " + user
        unnamed = sorted(f for f in out_required if not names(prompts_text, f))
        if unnamed:
            failures += 1
            print(f"  FAIL {label} output requires {', '.join(unnamed)}, which "
                  f"its prompts never name. A prompt written for another task "
                  f"asks for that task's answer against this task's schema.")

        # Where the prompt enumerates keys, that list is what the model obeys.
        shape_wrong = False
        enumerated = enumerated_keys(prompts_text)
        strict = "and no others" in prompts_text
        if enumerated is not None:
            allowed = set((task.get("output") or {}).get("properties") or {})
            missing = sorted(out_required - enumerated)
            if missing:
                failures += 1
                shape_wrong = True
                print(f"  FAIL {label} instructs a key list omitting "
                      f"{', '.join(missing)}, which its output requires. A "
                      f"response obeying the prompt fails validation.")
            # The converse, only where the prompt says "and no others". That
            # phrase is a claim the list is complete, so the extracted set is
            # the keys and a name outside the schema means a compliant
            # response fails a closed output. Without it the list is qualified
            # in prose here, "and optionally caveats", "plus cause_basis only
            # when cause_status is confirmed", and the identifiers pulled out
            # include `optionally`, `when` and `confirmed`: two correct specs
            # failed that way, which is how a check gets worked around. So the
            # branch is gated on the phrase rather than dropped, because it is
            # exactly the prompts making the strict claim that can be held to
            # it.
            if strict:
                extra = sorted(enumerated - allowed) if allowed else []
                if extra:
                    failures += 1
                    shape_wrong = True
                    print(f"  FAIL {label} instructs {', '.join(extra)}, which "
                          f"its output schema does not allow, in a list saying "
                          f"'and no others'. A response obeying the prompt "
                          f"fails validation.")

        unseen = sorted(k for k in required if not reads(user, k))
        if unseen:
            failures += 1
            print(f"  FAIL {label} requires {', '.join(unseen)}, which the "
                  f"user template ({user_layer}) never reads. The caller "
                  f"computes and passes them and the model never sees them.")

        if not in_system and not left_over and not unseen and not unnamed \
                and not shape_wrong:
            print(f"  ok   {label} system={system_layer}, user={user_layer}, "
                  f"{len(required)} input(s) all substituted, "
                  f"{len(out_required)} output field(s) all named")
        failures += check_enums(task, system, user, label)
    return failures


def override_targets(driver=pathlib.Path("demos/governance.sh")):
    """Pair each override file with the spec and task it is run against.

    Read out of the driver rather than hardcoded, because the pairing is a
    property of how the demo invokes the CLI and a table here would drift from
    it silently. An override with no discoverable pairing is reported rather
    than skipped: unpaired means unchecked, and unchecked should be visible.
    """
    if not driver.exists():
        return {}
    text = driver.read_text()
    targets = {}
    for match in re.finditer(r"--system-prompt \"\$\(cat ([^)]+)\)\"", text):
        before = text[:match.start()]
        spec = re.findall(r"--spec (\S+)", before)
        task = re.findall(r"--task (\S+)", before)
        if spec and task:
            targets[match.group(1).strip()] = (spec[-1], task[-1])
    return targets


def check_overrides(overrides=None, driver=pathlib.Path("demos/governance.sh")):
    """An override is a whole prompt, so it carries a prompt's obligations.

    Two of them. It is never substituted, so a placeholder in one is dead
    text. And it replaces the instruction that names the output shape, so it
    has to name that shape itself: an override asking for another task's
    answer is the same defect as an inherited prompt asking for it, and
    checking only for placeholders left that half open for every override in
    the tree.
    """
    targets = override_targets(driver)
    failures = 0
    for path in (OVERRIDES if overrides is None else overrides):
        key = str(path)
        found = unsubstituted(path.read_text(), set())
        if found:
            failures += 1
            print(f"  FAIL {path} contains {', '.join(found)}. An override "
                  f"replaces a prompt wholesale and is never substituted.")

        target = targets.get(key)
        if target is None:
            failures += 1
            print(f"  FAIL {path} is not paired with a spec and task by "
                  f"demos/governance.sh, so the shape it asks for cannot be "
                  f"checked against the shape its task requires.")
            continue

        spec_path, task_name = target
        spec = yaml.safe_load(pathlib.Path(spec_path).read_text())
        task = (spec.get("tasks") or {}).get(task_name) or {}
        out_required = ((task.get("output") or {}).get("required")) or []
        text = path.read_text()
        unnamed = [f for f in out_required if not names(text, f)]
        if unnamed:
            failures += 1
            print(f"  FAIL {path} overrides {task_name} but never names "
                  f"{', '.join(unnamed)}, which that task's output requires.")
        elif not found:
            print(f"  ok   {path.name} overrides {task_name}, no placeholders, "
                  f"names all {len(out_required)} required output field(s)")
        system, user, _, _ = resolve(spec, task_name)
        failures += check_enums(task, text, user, f"{path} overrides {spec_path}:{task_name}")
    return failures


# The check's own correctness, on the paths this repository's specs do not
# take. Style B prompts, the runner's default user template and per-key
# layering precedence are all live code here and all unexercised by any spec in
# the tree, which is how a resolver that looked right stayed wrong through a
# whole review round. Run with --self-test; CI does.
# Each case carries the reason it must fail, not merely that it must. Asserting
# the outcome alone is what let `unseen` and `in_system` go unproven through a
# review round: every case that failed, failed on leftover placeholders or an
# unnamed output field first, so deleting either branch left the suite green.
# A case that starts failing for a different reason is now a failure too.
SELF_TESTS = (
    ("Style B prompts, correct", None,
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"t": {"system": "sys names r_field", "user": "{{ a }}"}}}),
    ("Style B prompts referencing a non-input", "unsubstituted",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"t": {"system": "sys names r_field", "user": "{{ a }} {{ b }}"}}}),
    # The runner defaults the user template to `{{ input }}`, which its own
    # substitution loop never replaces, so a task with no prompts anywhere
    # hands the model that literal string.
    ("no prompts at all, runner default template", "unsubstituted",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}}}),
    ("no inputs and no placeholders", None,
     {"tasks": {"t": {"input": {}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "produce r_field", "user": "produce r_field"}}),
    # Precedence per key: inline system, Style B user, and a root user template
    # that must not be reached. Resolving the pair as a block takes the root's
    # broken placeholder and fails this case.
    ("inline system over Style B user over root", None,
     {"tasks": {"t": {"prompts": {"system": "names r_field"},
                      "input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"t": {"user": "{{ a }}"}, "user": "{{ zzz }}"}}),
    ("a misspaced placeholder the runner will not substitute", "unsubstituted",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "names r_field", "user": "{{  a  }}"}}),
    ("a prompt asking for another task's output shape", "never name",
     {"tasks": {"t": {"input": {"required": ["a"]},
                      "output": {"required": ["headline", "known"]}}},
      "prompts": {"system": "produce incident_state and hypotheses",
                  "user": "{{ a }}"}}),
    # The case that found substring matching: `r` is inside "produce", so a
    # prompt naming nothing was credited with naming this task's whole output.
    ("a one-letter output field not actually named", "never name",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r"]}}},
      "prompts": {"system": "produce the answer", "user": "{{ a }}"}}),
    # The reverse direction, and the shape that shipped: a template with no
    # leftover placeholders that simply never reads one of its required inputs.
    # `board` is computed by the caller, passed, and never substituted. This is
    # the only case that reaches `unseen`, which went a whole round unproven.
    ("a required input the well-formed template never reads", "never reads",
     {"tasks": {"t": {"input": {"required": ["audience", "board"]},
                      "output": {"required": ["headline"]}}},
      "prompts": {"system": "produce a headline", "user": "for {{ audience }}"}}),
    # The other two substitution forms. Every case above uses `{{ key }}`, so
    # single-brace and `{{ input.key }}` support could both be deleted with the
    # suite green, which is the coverage the docstring claims.
    ("the single-brace form the runner also replaces", None,
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "produce r_field", "user": "value {a}"}}),
    ("the input-dotted form the runner also replaces", None,
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "produce r_field", "user": "value {{ input.a }}"}}),
    # A spaced single brace is not a form the runner replaces, so it is dead
    # text and must be caught rather than read as a reference to `a`.
    ("a spaced single brace, which the runner leaves literal", "unsubstituted",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "produce r_field", "user": "value { a }"}}),
    # The enumerated key list, which the model obeys and which nothing
    # exercised: both branches below were deletable with the suite green while
    # the brief prompt was instructing a shape its schema rejected.
    ("an enumerated key list matching the schema", None,
     {"tasks": {"t": {"input": {"required": ["a"]},
                      "output": {"required": ["r_field"],
                                 "properties": {"r_field": {}, "extra": {}}}}},
      "prompts": {"system": "exactly these top-level keys: r_field, extra.",
                  "user": "{{ a }}"}}),
    ("an enumerated key list omitting a required field", "instructs a key list",
     {"tasks": {"t": {"input": {"required": ["a"]},
                      "output": {"required": ["r_field", "other"],
                                 "properties": {"r_field": {}, "other": {}}}}},
      "prompts": {"system": "produce other. exactly these top-level keys: "
                            "r_field.", "user": "{{ a }}"}}),
    ("a strict key list naming a field the schema forbids", "does not allow",
     {"tasks": {"t": {"input": {"required": ["a"]},
                      "output": {"required": ["r_field"],
                                 "properties": {"r_field": {}}}}},
      "prompts": {"system": "exactly these top-level keys and no others: "
                            "r_field, root_cause.", "user": "{{ a }}"}}),
    # A list qualified in prose still yields its keys and is not held to the
    # strict rule, which is what the two specs doing that need.
    ("an enumerated key list qualified in prose", None,
     {"tasks": {"t": {"input": {"required": ["a"]},
                      "output": {"required": ["r_field", "other"],
                                 "properties": {"r_field": {}, "other": {}}}}},
      "prompts": {"system": "exactly these top-level keys: r_field, and "
                            "optionally other.", "user": "{{ a }}"}}),
    # The wording split across a line break, which the first pattern missed.
    ("an enumerated key list wrapped across lines", "instructs a key list",
     {"tasks": {"t": {"input": {"required": ["a"]},
                      "output": {"required": ["r_field", "other"],
                                 "properties": {"r_field": {}, "other": {}}}}},
      "prompts": {"system": "produce other, with exactly these\n  top-level "
                            "keys and no others: r_field.", "user": "{{ a }}"}}),
    # And the only case that reaches `in_system`: a system prompt whose sole
    # defect is a placeholder, which is never substituted in one.
    ("a placeholder in an otherwise correct system prompt", "reach the model literally",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "produce r_field for {{ a }}", "user": "{{ a }}"}}),
)


# Every substitution form, live and dead, plus text that must not be read as a
# placeholder at all. The self-test cases above each drive one branch through a
# whole spec; this drives the form matching directly, because the claim "matches
# the three forms the runner replaces, and flags the ones it does not" is about
# strings and is cheapest to test as strings.
FORM_CASES = (
    ("{a}", True, "single brace"),
    ("{{ a }}", True, "double brace"),
    ("{{ input.a }}", True, "input dotted"),
    ("{{  a  }}", False, "double brace with extra spaces"),
    ("{ a }", False, "single brace with spaces"),
    ("{{a}}", False, "double brace with no spaces"),
    ("{{ input.a}}", False, "input dotted, missing space"),
    ("{{ b }}", False, "not an input"),
    ("{b}", False, "single brace, not an input"),
)

# Brace-bearing text that is not a placeholder. These prompts quote JSON at the
# model, so a form matcher that flags `{"triggered": false}` fails the tree.
NOT_PLACEHOLDERS = ('reply with {"triggered": false}', "JSON {} empty",
                    "keys: {a, b}", "set {x: 1} aside", "a { b", "}} stray")


def form_self_test():
    failures = 0
    for form, substituted, label in FORM_CASES:
        text = f"x {form} y"
        dead = unsubstituted(text, {"a"})
        seen = reads(text, "a")
        ok = (not dead and seen) if substituted else bool(dead)
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {form}: "
              f"{'substituted' if substituted else 'left literal'} ({label})")
    for text in NOT_PLACEHOLDERS:
        dead = unsubstituted(text, {"a"})
        failures += bool(dead)
        print(f"  {'ok  ' if not dead else 'FAIL'} not a placeholder: {text}")
    return failures


def self_test():
    import contextlib
    import io
    import tempfile

    failures = 0
    for label, expected, spec in SELF_TESTS:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "probe.yaml"
            path.write_text(yaml.safe_dump(spec))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                count = check_spec(path)
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
    failures += override_self_test()
    failures += form_self_test()
    enum_failures, enum_total = enum_self_test()
    failures += enum_failures
    print()
    if failures:
        sys.exit(f"{failures} self-test(s) failed: the check does not behave "
                 f"the way it is documented to.")
    total = (len(SELF_TESTS) + len(OVERRIDE_SELF_TESTS) + len(FORM_CASES)
             + len(NOT_PLACEHOLDERS) + enum_total)
    print(f"{total} self-tests hold, each on the reason it names.")


# The override half, driven the same way and for the same reason: its
# output-shape branch was the one branch a mutation could delete with the whole
# suite green, because nothing exercised it.
OVERRIDE_SELF_TESTS = (
    ("a correct override", None, "produce headline and known", True),
    ("an override carrying a placeholder", "never substituted",
     "produce headline and known for {{ audience }}", True),
    ("an override asking for another task's shape", "never names",
     "produce incident_state and hypotheses", True),
    ("an override the driver does not pair", "not paired",
     "produce headline and known", False),
)


def override_self_test():
    import contextlib
    import io
    import tempfile

    failures = 0
    for label, expected, body, paired in OVERRIDE_SELF_TESTS:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            spec = root / "probe.yaml"
            spec.write_text(yaml.safe_dump(
                {"tasks": {"t": {"output": {"required": ["headline", "known"]}}}}))
            override = root / "probe-system-prompt.txt"
            override.write_text(body)
            driver = root / "driver.sh"
            driver.write_text(
                f'oa run --spec {spec} --task t '
                f'--system-prompt "$(cat {override})"\n' if paired else "no pairing here\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                count = check_overrides([override], driver)
        output = buf.getvalue()
        if expected is None:
            ok, detail = count == 0, "accepted"
        elif count == 0:
            ok, detail = False, "accepted, but should have been rejected"
        else:
            ok = expected in output
            detail = (f"rejected on {expected!r}" if ok else
                      f"rejected for the wrong reason, wanted {expected!r}")
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {detail}")
    return failures


def enum_self_test():
    import contextlib
    import io
    import tempfile

    # Derive prompt vocabulary and near misses from the schema, so these
    # assertions measure its declared values rather than a parallel fixture.
    scale = {"type": "string", "enum": ["likely", "supported"]}
    values = scale["enum"]
    output = {"properties": {"confidence": scale}}
    path = "$.properties['confidence'].enum"
    cases = []

    def case(label, out=output, inp=None, system="", user="reply", missing=(),
             named=1, skipped=0):
        cases.append((label, {"input": inp or {}, "output": out}, system, user,
                      list(missing), (named, skipped)))

    case("named in the system prompt", system=", ".join(values))
    case("named in the user prompt", user=", ".join(values))
    case("one value missing", system=values[0], missing=[(path, values[1:])])
    case("near misses unlikely and unsupported", system=" ".join("un" + v for v in values),
         missing=[(path, values)])
    case("suffix near misses", system=" ".join(v + "ness" for v in values),
         missing=[(path, values)])
    one = {"properties": {"confidence": {"enum": values[:1]}}}
    case("case must match", out=one, system=values[0].capitalize(),
         missing=[(path, values[:1])])
    # No exemption: the same enum on the input, under the same name, changes
    # nothing. A schema cannot promise the words reach the model.
    case("the same enum on the input is not an exemption", inp=output,
         missing=[(path, values)])
    case("the same enum on the input and the words in the prompt pass as named",
         inp=output, system=" ".join(values))
    case("boolean schema is not an enum",
         out={"properties": {"confidence": False, "other": True}}, named=0)
    case("malformed enum is skipped", out={"enum": 1}, named=0, skipped=1)
    for label, vocabulary in (("numeric", [1, 2]), ("boolean", [True, False])):
        case(label + " enum has no string to name", out={"properties": {"confidence": {"enum": vocabulary}}},
             named=0, skipped=1)
    case("a mixed enum is checked on its strings",
         out={"properties": {"confidence": {"enum": [values[0], 1]}}}, missing=[(path, values[:1])])
    case("a mixed enum passes when its strings are named",
         out={"properties": {"confidence": {"enum": [values[0], 1]}}}, system=values[0])
    case("empty enum has no values to name", out={"enum": []}, named=0, skipped=1)
    case("escaped regex metacharacters", out={"enum": ["a.b", "c+d"]},
         system="axb cccd", missing=[("$.enum", ["a.b", "c+d"])])
    case("nonword edge values named literally", out={"enum": ["+ok", "ok+"]},
         system="+ok ok+")
    case("multiword value cannot straddle prompts", out={"enum": ["not established"]},
         system="not", user="established", missing=[("$.enum", ["not established"])])

    # Written out rather than read from the tuples under test: a case taken
    # from the collection it checks disappears with the member it would have
    # caught, and every mutation reads as covered.
    singles = ("additionalProperties", "unevaluatedProperties", "propertyNames",
               "items", "contains", "unevaluatedItems", "not", "if", "then",
               "else", "contentSchema")
    lists = ("allOf", "anyOf", "oneOf", "prefixItems")
    for keyword in singles + lists:
        child = [scale] if keyword in lists else scale
        out = {"properties": {"confidence": {keyword: child}}}
        enum_path = "$.properties['confidence']." + keyword
        enum_path += "[0].enum" if keyword in lists else ".enum"
        case("enum under " + keyword, out=out, missing=[(enum_path, values)])
    case("oneOf branch property", out={"oneOf": [{}, output]},
         missing=[("$.oneOf[1].properties['confidence'].enum", values)])
    for keyword in ("properties", "patternProperties", "$defs", "dependentSchemas"):
        # A name spelling an instance keyword is still a name. Skip the
        # container level and the declaration disappears.
        out = {keyword: {"examples": output}}
        enum_path = f"$.{keyword}['examples'].properties['confidence'].enum"
        case("names under " + keyword, out=out, missing=[(enum_path, values)])
    # Not schemas in 2020-12, however schema-shaped: an unknown annotation,
    # a name mapping whose values are name lists, the compatibility
    # `dependencies` and the pre-2019 `definitions`, which the validator
    # does not apply.
    case("unknown keyword value is not a schema", out={"x-note": output}, named=0)
    case("dependentRequired values are names, not schemas",
         out={"dependentRequired": {"confidence": ["other"]}}, named=0)
    case("dependencies is syntax the dialect does not apply",
         out={"dependencies": {"other": output}}, named=0)
    case("definitions is not applied in this dialect and is not read",
         out={"definitions": {"scale": scale}}, named=0)
    for keyword in ("const", "enum", "default", "examples"):
        literal = {"enum": list(values)}
        out = {keyword: [literal] if keyword in ("examples", "enum") else literal}
        # Object-valued enum is itself skipped; the enum inside that object
        # is instance data, just as it is inside defaults and examples.
        case("instance data stop " + keyword, out=out, named=0,
             skipped=int(keyword == "enum"))

    failures = 0
    for label, task, system, user, missing, counts in cases:
        buf = io.StringIO()
        spec = {"tasks": {"t": {**task, "prompts": {"system": system, "user": user}}}}
        with tempfile.TemporaryDirectory() as tmp:
            probe = pathlib.Path(tmp) / "probe.yaml"
            probe.write_text(yaml.safe_dump(spec))
            with contextlib.redirect_stdout(buf):
                try:
                    count = check_spec(probe)
                except Exception as exc:
                    # A broken guard must produce a named FAIL, not abort the
                    # suite before its skipped-vocabulary case can report it.
                    count = -1
                    print(f"exception {type(exc).__name__}: {exc}")
        text = buf.getvalue()
        if missing:
            reasons = [f"output {p} enum missing values: {v!r}." for p, v in missing]
            ok = count == len(missing) and all(reason in text for reason in reasons)
            detail = "; ".join(reasons)
        else:
            named, skipped = counts
            reason = f"enums: {named} named in the prompts, {skipped} with no string value"
            ok = count == 0 and reason in text
            detail = reason
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} enum {label}: {detail}")
        if not ok:
            print("    observed: " + text.strip().replace("\n", " | "))

    # The override replaces the system only; its task's resolved user still
    # reaches the model. Both halves must be tested through the driver pairing.
    override_cases = (("override enum missing", "reply", values),
                      ("override user supplies enum", " ".join(values), []))
    for label, user, missing in override_cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            probe = root / "probe.yaml"
            spec = {"tasks": {"t": {"output": output,
                                     "prompts": {"system": " ".join(values), "user": user}}}}
            probe.write_text(yaml.safe_dump(spec))
            override = root / "probe-prompt.txt"
            override.write_text("reply")
            driver = root / "driver.sh"
            driver.write_text(f'oa run --spec {probe} --task t --system-prompt "$(cat {override})"')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                count = check_overrides([override], driver)
        reason = (f"output {path} enum missing values: {missing!r}." if missing
                  else "enums: 1 named in the prompts, 0 with no string value")
        ok = count == bool(missing) and reason in buf.getvalue()
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} enum {label}: {reason}")
    return failures, len(cases) + len(override_cases)


def main():
    if "--self-test" in sys.argv:
        return self_test()
    if not SPECS:
        sys.exit("No specs found under .agents/. Run from the repository root.")
    failures = sum(check_spec(path) for path in SPECS)
    if OVERRIDES:
        print()
        failures += check_overrides()
    print()
    if failures:
        sys.exit(f"{failures} disagreement(s) between prompts and inputs.")
    print("Every variable the runner will substitute is a required input, "
          "every required input is read by the template it substitutes, and "
          "every task's prompts name the output shape its schema requires.")


if __name__ == "__main__":
    main()
