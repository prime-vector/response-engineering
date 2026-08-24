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
requires. A prompt that asks for the right shape names it; one written for a
different task does not. That holds for every task in this repository, which is
what makes it a check rather than a preference. Matching is on word boundaries
rather than by substring: a field called `r` is inside "produce", and substring
matching would credit a prompt with naming fields it has never heard of. One honest gap remains, that a field named for a common
word is matched by prose meaning something else, `outstanding` in the root pair
being the live example. That costs a field, not the check, because a prompt
written for another task misses the rest.

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

# Substitution, modelled exactly rather than approximated. The runner does
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
        unnamed = sorted(f for f in out_required if not names(system + " " + user, f))
        if unnamed:
            failures += 1
            print(f"  FAIL {label} output requires {', '.join(unnamed)}, which "
                  f"its prompts never name. A prompt written for another task "
                  f"asks for that task's answer against this task's schema.")

        unseen = sorted(k for k in required if not reads(user, k))
        if unseen:
            failures += 1
            print(f"  FAIL {label} requires {', '.join(unseen)}, which the "
                  f"user template ({user_layer}) never reads. The caller "
                  f"computes and passes them and the model never sees them.")

        if not in_system and not left_over and not unseen and not unnamed:
            print(f"  ok   {label} system={system_layer}, user={user_layer}, "
                  f"{len(required)} input(s) all substituted, "
                  f"{len(out_required)} output field(s) all named")
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
    # And the only case that reaches `in_system`: a system prompt whose sole
    # defect is a placeholder, which is never substituted in one.
    ("a placeholder in an otherwise correct system prompt", "reach the model literally",
     {"tasks": {"t": {"input": {"required": ["a"]}, "output": {"required": ["r_field"]}}},
      "prompts": {"system": "produce r_field for {{ a }}", "user": "{{ a }}"}}),
)


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
    print()
    if failures:
        sys.exit(f"{failures} self-test(s) failed: the check does not behave "
                 f"the way it is documented to.")
    print(f"{len(SELF_TESTS) + len(OVERRIDE_SELF_TESTS)} self-tests hold, each "
          f"on the reason it names.")


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
