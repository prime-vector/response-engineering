# Three outputs, and every confidence word in them

The three tasks whose `confidence` was pinned from a free string to an enum,
each captured from a live run on 24 Aug 2026, before the pinning. They are the
evidence offered in PLAN.md for not spending a live run per spec to find out
whether the enum would start rejecting what these agents normally write.

| File | Task | Confidence values |
| --- | --- | --- |
| `act1-detect.json` | Telemetry Analyst, `detect` | 3: one `confirmed`, two `supported` |
| `act2-correlate.json` | Change Correlator, `correlate` | 3: two `plausible`, one `speculative` |
| `act3-timeline.json` | Scribe, `timeline` | 43: 39 `confirmed`, two `supported`, two `plausible` |

Forty-nine values. Every one of them is in the five-word scale and in the
casing the enum declares, so the enum rejects nothing these three agents
produced on that day.

## Why these are committed when `runs/` is not

The same reason as `briefing-2026-08-24/`, and the rule is written in
`.gitignore` beside the `runs/` line: if a document cites a capture, the capture
is committed, and if it is not worth committing then the citation goes instead.

That rule paid for itself here. The citation was first written as 55 values
across these three tasks, which is wrong: 55 is the count across all five tasks
in that capture, including the commander's board and the Precedent Analyst's
recall, neither of which this change touches. Nobody could check it, because
the file it named was not in the tree. Committing the three outputs made the
number countable and the number was wrong.

## What this does and does not establish

It establishes that the vocabulary these three agents reach for is the
vocabulary now pinned, on one run each, under the prompts as they stood that
day.

It does not establish that they cannot write `Confirmed`, or a word from
outside the scale, under other conditions. One run is not a distribution.

And it predates one of the changes it is offered in support of. The Telemetry
Analyst's prompt did not state the five values when this was captured; the
scale lived only in the schema's `description`. So this run shows that the
prose scale was already enough to elicit in-scale words from that task. It
cannot show anything about the prompt sentence added alongside the enum, which
is a strengthening of the same condition rather than a change to it.

Read it as a record of one run on one day. If it disagrees with the current
specs, the specs are right.
