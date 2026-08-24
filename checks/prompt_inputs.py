#!/usr/bin/env python3
"""Every variable a prompt references is a required input, and the reverse.

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

The reverse direction is checked too, and is the quieter fault: a required
input no prompt mentions is a field the caller is obliged to compute, and pass,
and which the model never sees. The caller has every reason to believe it
arrived.
"""

import pathlib
import re
import sys

import yaml

SPECS = sorted(pathlib.Path(".agents").glob("*.yaml"))
PLACEHOLDER = re.compile(r"{{\s*(\w+)\s*}}")


def prompt_text(task, root):
    """A task's own prompts, or the root pair it inherits when it has none.

    Resolved the way the runner resolves it. Checking only the prompts a task
    declares would pass every inherited-prompt case, which is the one this
    check exists for.
    """
    prompts = task.get("prompts") or root
    inherited = prompts is root and bool(root)
    text = " ".join(v for v in (prompts or {}).values() if isinstance(v, str))
    return text, inherited


def check(path):
    spec = yaml.safe_load(path.read_text())
    root = spec.get("prompts") or {}
    failures = 0
    for name, task in (spec.get("tasks") or {}).items():
        text, inherited = prompt_text(task, root)
        refs = set(PLACEHOLDER.findall(text))
        required = set(((task.get("input") or {}).get("required")) or [])

        unsubstituted = sorted(refs - required)
        if unsubstituted:
            failures += 1
            where = "inherits the root prompts, which reference" if inherited \
                else "references"
            print(f"  FAIL {path.name}:{name} {where} "
                  f"{', '.join(unsubstituted)}, which are not required inputs. "
                  f"They will reach the model as literal template text.")

        unseen = sorted(required - refs)
        if unseen:
            failures += 1
            print(f"  FAIL {path.name}:{name} requires "
                  f"{', '.join(unseen)}, which no prompt reads. The caller "
                  f"computes and passes them and the model never sees them.")

        if not unsubstituted and not unseen:
            kind = "inherited" if inherited else "own"
            print(f"  ok   {path.name}:{name} {len(refs)} variable(s), "
                  f"{kind} prompts, all required inputs")
    return failures


def main():
    if not SPECS:
        sys.exit("No specs found under .agents/. Run from the repository root.")
    failures = sum(check(path) for path in SPECS)
    print()
    if failures:
        sys.exit(f"{failures} task(s) whose prompts and inputs disagree.")
    print("Every prompt variable is a required input, and every required "
          "input is read by a prompt.")


if __name__ == "__main__":
    main()
