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
what makes it a check rather than a preference. Matching is by substring, which
is coarse in one direction: an output field named for a common word can be
"named" by prose that means something else, and `outstanding` in the root pair
is exactly that. It costs a field, not the check, because a prompt written for
another task will miss the others.

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
BRACED = re.compile(r"{{.*?}}|(?<![{\w]){\w[^{}]*}")


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

        # The system prompt is never substituted. A placeholder in one is dead
        # text whatever the inputs are, so this is not a comparison.
        # Nothing in a system prompt is substituted, so any placeholder there
        # is dead text whatever the inputs are.
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
        unnamed = sorted(f for f in out_required if f not in system + " " + user)
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


def check_overrides():
    """An override is a whole prompt, so it carries a prompt's obligations.

    Two of them. It is never substituted, so a placeholder in one is dead
    text. And it replaces the instruction that names the output shape, so it
    has to name that shape itself: an override asking for another task's
    answer is the same defect as an inherited prompt asking for it, and
    checking only for placeholders left that half open for every override in
    the tree.
    """
    targets = override_targets()
    failures = 0
    for path in OVERRIDES:
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
        unnamed = [f for f in out_required if f not in text]
        if unnamed:
            failures += 1
            print(f"  FAIL {path} overrides {task_name} but never names "
                  f"{', '.join(unnamed)}, which that task's output requires.")
        elif not found:
            print(f"  ok   {path.name} overrides {task_name}, no placeholders, "
                  f"names all {len(out_required)} required output field(s)")
    return failures


def main():
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
