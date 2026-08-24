# Three briefings, and the board they were rendered from

`board.json` is an `assess` output from a live run on 24 Aug 2026.
`briefing-bridge.json` is what `brief` produced from it, for `audience:
bridge`, on the same day. Two earlier renders of the same board are kept beside
it, each showing a different way the briefing failed and the rule that now
prevents it.

## Why these are committed when `runs/` is not

`runs/` holds pipeline captures and is gitignored, because a live board is a
claim about what a model did on one day, nothing checks it, and it goes stale
the moment a spec changes. All of that is still true of these two files.

They are committed anyway for one reason: PLAN.md and this repository's own
argument about flattening refer to them. A claim whose evidence a reader cannot
open is not a claim, it is an assertion with a footnote, and the gate said so
twice. If it is cited, it is committed. If it is not worth committing, the
citation goes instead.

## The three renders, and what each one shows

`briefing-bridge-before-rule-3a.json` strengthened a verb.
`briefing-bridge-before-rule-6a.json` invented a citation.
`briefing-bridge.json` is the current render, which does neither.

Both failures were found by a reviewer reading output against board, and both
were produced by the agent built to prevent exactly that. Neither was caught by
any check here at the time: the confidence words were present, the falsifying
tests were present, the schema was satisfied.

The second is the worse one and the reason `checks/briefing_grounded.py` exists.
That render attached `INC-2411`, and a divergence invented to go with it, to the
endpoint-agent hypothesis, whose `precedent_cited` on the board is empty.
`INC-2411` is genuinely in the board, on a different hypothesis, so no
comparison of which references appear anywhere would have found it. What makes
it checkable is that entries are rendered one per hypothesis in board order,
which turns "did it cite the right thing" into an index lookup. Run the check
against that file and it fails on both the citation and a standing condition it
had copied back into `known`.

## The before and after, and why both are here

The earlier render is the clearest evidence in this repository of the failure
the project is about, produced by the agent built to prevent it.

Against a board whose summary says setroubleshootd "correlates with" batch
latency, and which holds the causal connection as a `supported` hypothesis, that
render's headline said it "is driving" latency. One word, in the sentence a
reader takes at face value, and every automated check here passed it: the
confidence words were present, the falsifying tests were present, the schema was
satisfied. It also filed "the only change record in the pre-onset window" under
`known`, which is a correlator finding the board holds at `plausible`, not a
direct observation.

Rule 3a now forbids strengthening the board's own verbs, and rule 3 says a
correlator statement is not a direct observation whatever its confidence. The
current render says "correlates with", and puts the change record's bare fact in
`known` with its interpretation in `suspected` at PLAUSIBLE. It also carries the
board's standing conditions, which the earlier one dropped entirely.

Two things worth keeping in view. The rule is prompt-only, so this is one run
behaving rather than a property: read the pair rather than trusting the claim.
And the fix arrived only because a reviewer read output and board side by side,
which is the argument for committing them.

The earlier render does not validate against the current schema, because
`standing_conditions` is required now and did not exist then. That is what a
dated record looks like when the spec moves, and editing it to pass would make
it useless.

## What they are for

Reading the briefing against the board is the only way to see what the schema
cannot check. The output contract requires a confidence word and a falsifying
test in each `suspected` entry and forbids undeclared fields. It cannot check
that the confidence matches the one the board gave, or that the sentence around
it reads as a suspicion rather than a finding.

So this pair is the worked example of that gap. Compare `headline` and `known`
against `summary` and the `hypotheses` confidences, which is where a reader
takes a sentence at face value, and where the strengthening of a hedge would go
unnoticed by every automated check here. The earlier render is what that looks
like when it happens.

## Committed byte for byte

Including the em dashes, which the repository's language rule forbids in
authored copy. These are not authored copy. Editing a model's output to satisfy
a style guide leaves something that is no longer the output, and the whole value
of this pair is that it is exactly what came back. `evals/results/` is committed
on the same basis and for longer.

## What they are not

Not a fixture, not a baseline, not regenerated, and nothing in CI compares
anything to them. They are dated because they are a record of one run. If they
disagree with the current specs, the specs are right and these are history.
