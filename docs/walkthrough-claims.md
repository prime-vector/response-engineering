# What the walkthrough may claim

The walkthrough is the one artefact here with no contract on it. A script is
prose, and prose losing its caveats is the thing this project exists to
demonstrate, so a voiceover is checked against this file the way a spec is
checked against its contract.

Three tiers, sorted by what guarantees the claim rather than by how confident
anyone feels about it.

---

## Tier 0: guaranteed by the fixture

The most quotable numbers in this story are not model output at all. They are
asserted by `fixtures/generate.py`, and CI diffs every view against the
generator on each pull request, so they cannot drift without the build going
red.

| May be spoken | Where it comes from |
| --- | --- |
| Thirteen problems across fifteen days, on one host | `fixtures/generate.py`, asserted at generation |
| Every one auto closed | same |
| None acknowledged, assigned or actioned | same |
| The application holds 23 of 32 GiB, and has for months | the standing condition in `SCENARIO.md`, generated into every view |
| The change lands eight days before onset | the generated change registry |
| The day one view holds two problems and no incident | `--at d1`, deliberately near empty |

This tier matters more than it looks. The hook is thirteen, fifteen and zero,
and none of those three depends on what a model decides to say.

## Tier 1: guaranteed by the contract

Safe to assert flatly, on any run, without watching the screen. Each row names
what enforces it and the committed case that proves the guarantee can fail.
`python3 checks/contract_invariants.py` runs the cases with no model and no key.

| May be spoken | Enforced by | Proven by |
| --- | --- | --- |
| Convergence cannot be allowed while a blocking item is outstanding | `assess` output schema, `if`/`then` over `still_outstanding`, which is a required field | `convergence allowed with an item outstanding` |
| A hypothesis citing precedent cannot be confirmed | `not: {const: confirmed}` over a pinned enum, so both spellings close | `cited and confirmed`, `cited and Confirmed` |
| A passage id cannot appear on the blocking list | `blocking_evidence` is a closed object | `precedent attached to blocking evidence` |
| Naming a third party below confirmed forces the attribution guard onto the board | `if`/`then` over `third_party_named` and `confidence` | `a third party named below confirmed, guard silent` |
| Every hypothesis carries a confidence word and a falsifying test | both are required fields | `demos/governance.sh contract` |
| Confidence is one enum, in one order, in every spec that carries a claim | `checks/contract_invariants.py` holds all six specs to the board's scale | the scale check, plus 28 self-tests |
| A briefing renders one entry per hypothesis, in the board's order, carrying that hypothesis's confidence | `checks/briefing_grounded.py` over the committed samples | the sample that failed, kept in the tree |
| The sandbox refuses the directed production change before dispatch | the task's own sandbox denies the tool | `demos/governance.sh sandbox` |
| A novel incident returns no applicable precedent, with coverage populated | the surface's relevance floor, not a prompt instruction | `demos/governance.sh refusal` |

## Tier 2: asserted at run time

`demos/governance.sh` exits zero only if every demo produced its expected
outcome, across all five modes. A recorded take carries its own verdict: if the
run in the take exited zero, every Tier 2 claim in that take held.

This is the only tier where a claim is verified by the take itself rather than
in advance.

### Measured, 25 August 2026

One full pass, exit zero, all five modes producing their expected outcome.

| Mode | What the run produced |
| --- | --- |
| sandbox | `SANDBOX_TOOL_VIOLATION`, tool not in the allow list for `mitigate`, `Allowed: []` |
| attribution | guard triggered, convergence blocked, and the guard-stripped arm rejected by the schema (`True was expected`) |
| contract | `OUTPUT_SCHEMA_ERROR`, `'falsifying_test' is a required property` |
| grounding | `OUTPUT_SCHEMA_ERROR`, `'grounded_in' is a required property` |
| refusal | `no_applicable_precedent`, `precedents []` |

Worth knowing before scripting the attribution shot: the board's own convergence
note said that the relay had dropped the analyst's caveat and the deciding
evidence requirement, and that the board restored both. That is the 19:00
failure from the scenario, reproduced and then refused, in the board's own
words. It is Tier 3 prose and must not be quoted from a script, but it is the
thing to have on screen.

## Tier 3: true of one run, guaranteed by nothing

Read off `runs/2026-08-24-investigate-all`, which is one composed run on one
day: four hypotheses, five blocking items with all five outstanding, one
recurrence, three findings, two precedents recalled, forty three timeline
entries, seven gaps, and which passages were cited. All generated prose sits
here too.

**A Tier 3 number is never spoken.** If one has to appear, read it off the
screen inside the take, or rewrite the line to the invariant underneath it.
"Four hypotheses and five items outstanding" needs a run that produces exactly
that. "The board blocks convergence while deciding evidence is outstanding" is
true of every run that will ever execute, and it is the more interesting
sentence anyway.

The four committed briefing renders are the evidence for this split, already
paid for: across three prompt revisions the prose changed every time and the
typed fields held every time.

### Measured, 25 August 2026

Two composed runs a day apart, on different commits, at temperature 0.2.
Twelve of fifteen narrative fields came out identical. Three varied, and these
are the ones a script must not speak:

| Field | 24 Aug | 25 Aug |
| --- | --- | --- |
| fourth hypothesis confidence | `supported` | `speculative` |
| blocking evidence items | 5 | 4 |
| timeline entries | 43 | 44 |

Identical across both: incident state, hypothesis count, third parties named,
attribution guard present, convergence blocked, hypotheses carrying a citation,
correlations, findings, recurrences, precedents recalled, gaps.

Two runs is not a distribution, and stability across two runs does not promote a
field out of Tier 3. Only the contract promotes anything. The measurement is
here to say which fields are known to move, not to license the rest.

---

## What the walkthrough must not claim

- **That convergence is always blocked.** It is blocked while a blocking item
  is outstanding. A board that lists no blocking evidence may converge, and
  `a board with no blocking evidence at all` is accepted on purpose.
- **That precedent can never settle a blocking item.** No typed route allows
  it, and prose is not closed: `precedent asserted in prose as satisfying a
  blocking item` is accepted, and that case is in the suite to keep this
  sentence honest.
- **That the cause is established.** It never was. The demo does not resolve
  it, and the deciding evidence sits in `missing_evidence` by design.
- **That a check enforces something**, without having read the check. That is
  the most frequent defect in this repository's history and it has appeared in
  a contract description on the change whose central promise it was.
- **Any third party in a causal role.** Generic categories only.

## Before a take

1. `python3 checks/contract_invariants.py` and the other checks green, so Tier 1
   is true of the commit being recorded.
2. The script read against this file, line by line, for Tier 3 numbers.
3. `demos/governance.sh all` inside the take, so its exit status is the take's
   own verdict on Tier 2.
