# Contributing

Thanks for looking. This is a reference implementation, so most changes are
to specs, checks and the copy that explains them, and the bar is that every
sentence stays true of the tree.

## Read first

`SCENARIO.md` is the source of truth. Every spec, fixture and piece of copy
derives from it. `CLAUDE.md` is written for the coding agent that works here
but it is also the fullest statement of the conventions, and a change that
contradicts it will be sent back to it.

## Four rules that are not negotiable

1. **No source material.** The scenario is a composite of a recurring
   pattern, derived from real engagements. Nothing from those engagements
   enters this repository: no transcripts, screenshots, host names, ticket
   references or names, in any branch, gitignored or not. Git history is
   permanent. If a change needs reference material to make its point, the
   point has to be made another way.
2. **No vendor is named in a causal role.** Third-party products appear only
   as generic categories: the observability platform, the endpoint compliance
   agent. Naming a vendor as a cause without direct evidence is the failure
   this project criticises, so doing it here would be self-refuting. Vendors
   may be named in capability mappings, such as the adapter table in
   `interfaces/TELEMETRY.md`.
3. **The cause is never established.** The incident in the scenario was never
   resolved to a root cause, and nothing here may resolve it: not a spec, not
   a fixture, not a sample, not a sentence. A change that asserts a confirmed
   cause is a bug.
4. **Specs name capability, never a platform.** Adapters implement it. A spec
   that references a specific product has broken the interface abstraction.

## Before you open a pull request

Run what CI runs, locally, so the review is about the change and not about
the generated artefacts:

```bash
oa validate --spec .agents/<name>.yaml      # every spec you touched
python3 checks/prompt_inputs.py             # any prompt, input schema or demos/ override
python3 checks/contract_invariants.py       # either commander contract, or any confidence enum
python3 corpus/ingest.py --check            # if the corpus changed, plus --chunker fixed --check
python3 corpus/eval.py                      # against both indexes
python3 -m pytest tests                     # the regression tests
```

Fixtures and the corpus index are generated, never hand-edited: change the
generator and regenerate. `evals/results/` and `docs/samples/` hold model
outputs byte for byte and are not edited at all.

Three things CI cannot check and a reviewer will: the four rules above, no
commercial detail, and the language. Copy is Australian English, with no em
dashes, and it says *production*, *incident response*, *responders*,
*investigation*, *specs*, *contracts* and *evidence* rather than any of the
managed-service vocabulary those words replace.

## What a good change looks like

A sentence that says a check enforces something is held to the check. Before
writing *every*, *closed* or *exactly N*, say where that set is defined
outside your own judgement. When the code and the claim disagree, narrow the
claim to what the code does and widen it as its own change. The section
"Before asking for a review" in `CLAUDE.md` is the longer version, written
from the findings that kept recurring.
