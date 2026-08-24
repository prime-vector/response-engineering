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

WHAT THIS CANNOT SEE. `--system-prompt` and `--user-prompt` replace a prompt
wholesale at the command line, and a spec cannot know what they will carry. The
override files this repository keeps are checked directly, below; an override
composed anywhere else is outside what a spec-level check can reach, and
CLAUDE.md's note that CLI access is privileged covers the rest.
"""

import pathlib
import re
import sys

import yaml

SPECS = sorted(pathlib.Path(".agents").glob("*.yaml"))
# The override prompts this repository keeps in the tree. A CLI override is
# unsubstituted system text by definition, so any placeholder in one is dead.
OVERRIDES = sorted(pathlib.Path("demos").glob("*-prompt.txt"))

# The three spellings the runner replaces. `{{ input.key }}` and `{key}` are
# not decoration: a check matching only `{{ key }}` reports a clean spec while
# the runner is filling, or failing to fill, names it never saw.
PATTERNS = (
    re.compile(r"{{\s*(\w+)\s*}}"),
    re.compile(r"{{\s*input\.(\w+)\s*}}"),
    re.compile(r"(?<![{\w]){(\w+)}(?!})"),
)


def variables(text):
    found = set()
    for pattern in PATTERNS:
        found |= set(pattern.findall(text or ""))
    return found


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
        in_system = sorted(variables(system))
        if in_system:
            failures += 1
            print(f"  FAIL {label} system prompt ({system_layer}) references "
                  f"{', '.join(in_system)}. The runner substitutes the user "
                  f"template only, so these reach the model literally.")

        in_user = variables(user)
        unsubstituted = sorted(in_user - required)
        if unsubstituted:
            failures += 1
            print(f"  FAIL {label} user template ({user_layer}) references "
                  f"{', '.join(unsubstituted)}, which are not required inputs. "
                  f"They will reach the model as literal template text.")

        unseen = sorted(required - in_user)
        if unseen:
            failures += 1
            print(f"  FAIL {label} requires {', '.join(unseen)}, which the "
                  f"user template ({user_layer}) never reads. The caller "
                  f"computes and passes them and the model never sees them.")

        if not in_system and not unsubstituted and not unseen:
            print(f"  ok   {label} system={system_layer}, user={user_layer}, "
                  f"{len(in_user)} variable(s), all required inputs")
    return failures


def check_overrides():
    failures = 0
    for path in OVERRIDES:
        found = sorted(variables(path.read_text()))
        if found:
            failures += 1
            print(f"  FAIL {path} references {', '.join(found)}. An override "
                  f"replaces a prompt wholesale and is never substituted.")
        else:
            print(f"  ok   {path.name} carries no placeholders")
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
    print("Every variable the runner will substitute is a required input, and "
          "every required input is read by the template it substitutes.")


if __name__ == "__main__":
    main()
