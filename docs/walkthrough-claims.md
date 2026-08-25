# What the walkthrough may claim

The walkthrough is the one artefact here with no contract on it. A script is
prose, and prose losing its caveats is the thing this project exists to
demonstrate, so a voiceover is checked against this file the way a spec is
checked against its contract.

Claims are sorted by what guarantees them. Two different questions matter and
they have different answers, so they are kept apart:

- **Can it vary between takes?** That is the retake risk.
- **Can it drift as the repository changes?** That is whether the sentence is
  still true of the commit being recorded.

A value read out of a committed file cannot vary between takes and can still
drift. A schema rule cannot do either. Model output can do both.

---

## Tier 0a: asserted by the generator, and diffed in CI

Cannot vary between takes and cannot drift. `fixtures/generate.py` asserts
these in `assert_feed_shape`, and the workflow diffs every committed view
against the generator on each pull request, so an edit that breaks one goes red.

| May be spoken | The assertion |
| --- | --- |
| Thirteen problems | `len(feed) == 13` |
| Across fifteen days | span of `PROBLEM_DAYS` is 15 |
| Every one auto closed | `all(p["auto_closed"])` |
| None acknowledged | `not any(p["acknowledged_by"])` |
| The same signature throughout | one distinct signature |
| The same severity throughout | one distinct severity |

**Say "none acknowledged", not "none acknowledged, assigned or actioned".**
There is no assigned or actioned field in the feed. The longer phrase is prose
from a note string and asserts nothing.

**The ban is on the claim, not on the voiceover.** A frame asserts to a viewer
whatever it holds long enough to read, so quoting the note string on screen
makes the same unasserted claim the voice is forbidden to make, and does it
without a line anyone reviewed. Model output quotes that string readily: one
`findings` entry in the 25 August act one capture carries it verbatim as
supporting evidence. Check what a held frame says, not only what is said over
it.

## Tier 0b: committed to a fixture, not asserted

Cannot vary between takes, because they are values in a file that a take reads.
They can drift, because a generator edit moves the fixture and the diff stays
green: nothing asserts the value itself.

Safe to show on screen and safe to speak in a take recorded on a green commit.
Not safe to write into permanent copy as though a check defends them.

- The application holds 23.1 GiB of 32, and has for at least six months
- The change lands eight days before onset
- The day one view holds two problems, no incident, and no change query

## Tier 1: guaranteed by the contract

Cannot vary and cannot drift without a check going red. Each row names the
mechanism and the committed case that proves the guarantee can fail.
`python3 checks/contract_invariants.py` runs the cases with no model and no key.

| May be spoken | Enforced by | Proven by |
| --- | --- | --- |
| Convergence cannot be allowed while a blocking item is outstanding | `if`/`then` over `still_outstanding`, which is required so it cannot be dodged by omission | `convergence allowed with an item outstanding` |
| A hypothesis citing precedent cannot be confirmed | `not: {const: confirmed}` over a pinned enum, so both spellings close | `cited and confirmed`, `cited and Confirmed` |
| A blocking item has no field a passage id can be filed in | `blocking_evidence` is a closed object | `precedent attached to blocking evidence` |
| Naming a third party below confirmed forces an attribution guard onto the board | `if`/`then` over `third_party_named` and `confidence` | `a third party named below confirmed, guard silent` |
| Every hypothesis carries a confidence word and a falsifying test | both are required fields on the hypothesis | required in the schema; the contract demo shows the falsifying half |
| Confidence is one enum, in one order, in every spec that declares one | `checks/contract_invariants.py` holds all six declarations, across five specs, to the board's scale | the scale check, plus 28 self-tests |
| The task that would change production state binds no tools at all | an empty allow list on `mitigate`, which denies every tool by name | `demos/governance.sh sandbox` |

**The guard row is presence only.** `attribution_guard` has no required
properties: `party`, `reason` and `evidence_required` are optional. A script
may say the guard is forced onto the board. It may not say what the guard
contains. The demo checks the contents, which makes that Tier 2.

**Comms declares no confidence**, by a written exception, so it is six
declarations across five specs. "All six specs" is wrong in both halves.

## Tier 2: asserted at run time

The take carries its own verdict. `demos/governance.sh` exits zero only if
every mode produced its expected outcome, and `demos/investigate.sh` verifies
tool use from the adapter log rather than from the output.

Anything here is safe to say **about the run on screen** and unsafe to say about
runs in general.

| Claim | What asserts it |
| --- | --- |
| A novel incident returned no applicable precedent, with coverage populated | `governance.sh refusal` |
| The guard named the missing evidence and what would settle it | `governance.sh attribution` checks the guard's contents |
| A board with no falsifying test was rejected | `governance.sh contract` |
| A precedent with no grounding was rejected | `governance.sh grounding` |
| Every citation came from what the archive returned this run, at that bound | `investigate.sh` checks each id against the bounded search |

**Recall is not fully bounded and a script must not say it is.**
`precedent_search` and `coverage_describe` take a required `before`.
`passage_get` takes an id and no bound, so the bound reaches it only through
where the id came from, checked by the driver. Two of the three calls are
bounded.

## Tier 3: guaranteed by nothing

Model output. Everything in `runs/`, all generated prose, and every count the
board or the timeline produces.

**A Tier 3 number is never spoken, and neither is a sentence only one run
satisfies.** "The analyst reports the recurrence" is a Tier 3 claim without a
digit in it: `recurrence_detected` is a required boolean, not a constant.

### Measured, 25 August 2026

Two composed `investigate.sh all` runs a day apart on different commits, and one
`governance.sh all` pass, five modes, all expected outcomes.

| Field | 24 Aug | 25 Aug |
| --- | --- | --- |
| fourth hypothesis confidence | `supported` | `speculative` |
| blocking evidence items | 5 | 4 |
| timeline entries | 43 | 44 |

Twelve other narrative fields were identical. That is worth knowing and it
guarantees nothing: two runs is not a distribution, the captures are in `runs/`
and therefore gitignored, so no reader can recount them, and stability across
two runs promotes nothing out of Tier 3.

---

## What the walkthrough must not claim

This list is **not closed**. It holds the false sentences found so far, and
finding another is expected rather than surprising, because it is a claim about
prose and there is no vocabulary to enumerate.

- **That convergence is always blocked.** It is blocked while a blocking item
  is outstanding. `a board with no blocking evidence at all` is accepted.
- **That the deciding evidence is always outstanding.** The schema knows that
  *some* item is outstanding. Which item, and whether it is the audit log, is
  the board's judgement. The blocking count already moved between two runs.
- **That precedent can never settle a blocking item.** Not by any typed route.
  It can in prose, and that case is accepted deliberately.
- **That a passage id cannot appear on the blocking list.** No field can carry
  one. A `description` or a `how_to_obtain` string can.
- **That a caveat has nowhere to fall.** True of a typed handoff between
  agents. False of any prose rendering, including the briefing, including this
  walkthrough. Do not say it without the rendering half in the same breath.
- **That every archive call is time bounded.** Two of the three are.
- **That the cause is established.** It never was.
- **That the briefing fabricated a record.** The failing render in
  `docs/samples/briefing-2026-08-24/` attaches `INC-2411` to a hypothesis whose
  `precedent_cited` is empty. `INC-2411` is a real corpus document. It carried
  a precedent the board did not cite, which is the failure; inventing a
  document is a different and larger one that did not happen.
- **That a check enforces something**, without having read the check.
- **Any third party in a causal role.**

## Before a take

1. All checks green on the commit being recorded, so Tier 1 is true of what is
   on screen and Tier 0b is true of the fixture in shot.
2. This file read against the script, line by line. Tier 3 leaks are usually
   not digits, they are sentences that only one run satisfies.
3. `demos/governance.sh all` run **before** the take, with its exit status
   captured beside the footage the take will show. The guarantee is that the
   exit status belongs to the run on screen, not that it was produced while
   recording, and `docs/walkthrough-script.md` records why pre-running is the
   settled practice.
4. Three patches applied and `checks/stream_probe.py` green, or a long
   generation can be cut in transit and the take is lost at length rather than
   at content.
