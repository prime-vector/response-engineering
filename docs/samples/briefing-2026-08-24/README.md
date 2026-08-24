# Four briefings, and the board they were rendered from

`board.json` is an `assess` output from a live run on 24 Aug 2026.
`briefing-bridge.json` is what `brief` produced from it, for `audience:
bridge`, on the same day. Three earlier renders of the same board are kept
beside it, each showing a different way the briefing failed and what now
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

## The four renders, and what each one shows

`briefing-bridge-before-rule-3a.json` strengthened a verb.
`briefing-bridge-before-rule-6a.json` invented a citation.
`briefing-bridge-before-typed-fields.json` carried its caveats as words inside a
sentence, which is how both of those were possible.
`briefing-bridge.json` is the current render, with `suspected` as typed objects.

The first three do not validate against the current schema, and that is the
point of keeping them: each one is what the contract looked like before it was
made to carry what it claimed.

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

## Why the caveats became fields

Three review rounds went into a regex holding the caveats in prose: word
boundaries so `likely` did not match inside `unlikely`, lookbehinds so it did
not match inside `not likely`, then casing on those lookbehinds so it did not
match inside `NOT LIKELY`. Each round closed one spelling of one hole.

CLAUDE.md had said from the beginning that an output carrying a claim declares
`confidence` and `falsifying_test` as required fields, with Comms the single
written-down exception. Applying that rule here ends the whole class: the
confidence is an enum, so no spelling of a negation reaches it, and
`checks/briefing_grounded.py` compares it to the board's rather than trusting
it. The lesson is not about regexes. It is that the rule already existed and
this task had quietly been made an undeclared second exception to it.

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

## What four renders measured

Every live render of this task so far has strengthened something the board
hedged. Four for four, across three prompt revisions written to stop it.

| Render | What it strengthened |
| --- | --- |
| `before-rule-3a` | The board says setroubleshootd "correlates with" latency; the headline said it "is driving" it |
| `before-rule-6a` | Attached `INC-2411` and an invented divergence to a hypothesis the board carries no precedent on |
| `before-typed-fields` | Caveats held as words in a sentence, which is what made the first two expressible |
| current | "13 occurrences over 15 days" became problems "repeating nightly from 2026-03-02 onward", and a standing condition is restated across two `known` entries |

That is the result, and it is not a queue of defects to work through. It is
evidence for the thing this repository argues about incident reporting
generally: a caveat carried as prose does not survive a change of format, and
the fix is to stop carrying it as prose. Where that was possible it was done,
and `suspected` is typed. Where it was not, in a headline and a list of
observations that have to read as English, the claim has been withdrawn rather
than defended.

The current render's own violation is left in place deliberately. A sample that
had been re-rolled until it passed would say less than one that shows what the
guarantee is worth.

## What they are not

Not a fixture, not a baseline, and not regenerated. CI does compare the current
render against `board.json`, through `checks/briefing_grounded.py`: it validates
against the task's output schema and checks the typed relationships. It does not
compare the prose, which is the part that keeps failing. They are dated because they are a record of one run. If they
disagree with the current specs, the specs are right and these are history.
