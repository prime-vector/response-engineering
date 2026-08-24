# One briefing, and the board it was rendered from

`board.json` is an `assess` output from a live run on 24 Aug 2026.
`briefing-bridge.json` is what `brief` produced from it, for `audience:
bridge`, on the same day.

## Why these two are committed when `runs/` is not

`runs/` holds pipeline captures and is gitignored, because a live board is a
claim about what a model did on one day, nothing checks it, and it goes stale
the moment a spec changes. All of that is still true of these two files.

They are committed anyway for one reason: PLAN.md and this repository's own
argument about flattening refer to them. A claim whose evidence a reader cannot
open is not a claim, it is an assertion with a footnote, and the gate said so
twice. If it is cited, it is committed. If it is not worth committing, the
citation goes instead.

## What they are for

Reading the briefing against the board is the only way to see what the schema
cannot check. The output contract requires a confidence word and a falsifying
test in each `suspected` entry and forbids undeclared fields. It cannot check
that the confidence matches the one the board gave, or that the sentence around
it reads as a suspicion rather than a finding.

So this pair is the worked example of that gap. Compare `headline` and `known`
against `summary` and the `hypotheses` confidences, which is where a reader
takes a sentence at face value, and where the strengthening of a hedge would go
unnoticed by every automated check here.

## What they are not

Not a fixture, not a baseline, not regenerated, and nothing in CI compares
anything to them. They are dated because they are a record of one run. If they
disagree with the current specs, the specs are right and these are history.
