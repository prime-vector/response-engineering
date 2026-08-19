# How `expect.relevant` is judged

Ground truth in `dataset.yaml` is hand-authored, so the judgement has to be
auditable without reverse-engineering it out of the YAML. This is that record.

## The rule

> `relevant` is a property of the incident as the case states it, meaning
> (`as_of`, `symptom`, `evidence`, `missing_evidence`). It is not scoped to what
> the case is testing, and not to what the canonical query can reach.

Two consequences, and they pull against each other. Both matter.

**Consequence one: same incident, same set.** Cases describing the same incident
at the same bound with the same evidence must name the same documents, however
differently they probe it. `a01`, `a03`, `a04` and `d02` are four probes of one
incident and carry one relevance set between them.

This is what stops the dataset grading itself. Scoping relevance to the case is
the subtle version of fitting to the retriever: a (case, document) pair left out
because the probe cannot reach it is never counted as a miss, and the published
recall figure rises without retrieval improving. That is exactly what happened
in the first version of this dataset, and it is why the observed figure moved
from 36/41 to 36/60 with no change to the retriever.

**Consequence two: relevance still has to discriminate.** A document is relevant
when it would change what the responder does or believes: the shape matches, or
it warns against the obvious wrong move. Sharing a signature type is not
sufficient. If every memory case listed every memory document, `hit_rate` would
measure nothing at all.

So relevance is neither "everything that matches the signature" nor "what this
case wants to talk about". It is what a responder holding this view would want
in front of them.

The first half is enforced rather than remembered: cases sharing a
`relevance_group` are one incident seen one way, and `validate.py` asserts their
`relevant` and `applicability` are identical. The second half cannot be
mechanised, which is why the judgements below are written out.

## The judgements

### The composite incident, bridge bound (`a01`, `a03`, `a04`, `d02`)

One incident, four probes. Evidence names the audit analysis daemon;
`missing_evidence` names the denial log and the process attribution.

| Document | Why | Applicability |
| --- | --- | --- |
| `INC-2411` | Same signature type. Resolution was a revert, and there is no change here to revert. | partial |
| `INC-2419` | Same signature type, cause never established, and the restart that ended it destroyed the attribution this incident still needs. | partial |
| `INC-2288` | The denial-daemon axis. Its resolution has since been withdrawn. | superseded |
| `memory-pressure` | The procedure for the failure being investigated. | applies |
| `denial-log-collection` | The outstanding deciding evidence is the denial log, and this is the procedure for collecting it before it is destroyed. | applies |

`a03` probes the denial axis and `a04` probes with the reported symptom used
whole. Neither changes the incident, so neither changes the set. Both are marked
down for what their probe cannot reach, which is the measurement working.

### The composite incident, D+1 bound (`a02`, `d03`)

`INC-2411`, `INC-2419`, `memory-pressure`.

`INC-2288` and `denial-log-collection` are **not** relevant here, and this is the
rule doing real work rather than being applied mechanically. At D+1 no denial
daemon has been observed: `a02` holds only the standing condition and `d03` holds
no evidence at all. Nothing in the view points at a denial axis, so a responder
would have no reason to want either document. Thinner evidence, smaller set.

### Same host, thinner view (`g01`)

`INC-2411`, `INC-2419`, `memory-pressure`. Bridge bound and the same host as
`a01`, but the case states no collected evidence, so the denial axis is not in
view. Same reasoning as D+1.

### Before the runbooks existed (`f04`)

`INC-2411`, `INC-2419`. A bare memory-exhaustion view with a restart proposed, so
it matches `g01`, minus the five runbooks that are not recorded until 2026-01-12
and are listed in `unreachable_by_bound`.

### Everything else

Single-axis cases, where the shape decides it: the prior record that matches and
diverges, plus the procedure that covers the failure in view.

**Both halves, in every group.** An earlier version of this file said near
misses name "the one prior record that matches and diverges", which contradicted
the rule two sections above and was already false of five of the seven. It left
`b01` without `memory-pressure` despite being a host swapping with attribution
outstanding, which is what that runbook opens on and what `b03`, `b05` and `b06`
all cite it for. It left `b04` without it too, even though the container
runbook's own closing section is what sends a host with no runtime there.

That was the scoring subset surviving in group B: both probes miss
`memory-pressure`, and while it went unlisted those misses never reached the
published figure. Grok's second review found it.

The counter-pressure still holds and is what stops this collapsing into "every
memory case lists every memory document". `INC-2350` on `b01` would be that
collapse: a different shape that happens to share a signature type. The covering
procedure is not.

`b07` names no runbook because there is no CPU runbook in the corpus, which is
an absence in the archive rather than a judgement.

### The applies group, and where the covering-procedure rule stops

Group C was the next place the carve-out hid, because this file described group
B and then stopped. Writing the C judgements out is what would have caught it.

`c06` is `host.memory.exhaustion` with a restore proposed before onset is known.
It names `recovery-point-selection`, which answers the question being asked, and
`memory-pressure`, which covers the failure in view: its closing section is
exactly "do not restart the workload as a first step, it resolves the symptom
and destroys the evidence in the same action", and a restore is that move. It
does not name `INC-2411` or `INC-2419`. Those would be the collapse: a different
shape that happens to share a signature type.

`c08` is the case that shows the rule is not mechanical. It is
`host.memory.pressure` on a host that is deliberately overcommitted, with the
page fault rate inside its own baseline and nothing outstanding. A scan by
signature type flags it as missing `memory-pressure` exactly as it flagged
`c06`, and it is correct to leave out. That runbook tells a responder to take a
process snapshot and attribute the memory before changing anything, which is
investigative work on a host where nothing is wrong. The right answer is
`INC-2489`: correct the threshold, change nothing on the host.

So the test is not "does the signature type have a runbook". It is whether the
procedure's guidance is the right thing to do here. `c06` yes, `c08` no.

`validate.py` now enforces this rather than trusting it. Any case whose
signature type has a covering procedure in reach must either name it or fill
`covering_procedure_waived`, which is what `c08` does.

### Record status (`d01`, `d02`, `d03`)

`d01` is the case this whole rule cost the most to get right, and it is worth
recording why rather than just correcting it.

It was written as a refusal: the best-matching record is `DRAFT-2508`, a draft
cannot ground a claim, so `no_applicable_precedent` looked correct. That was
true of the incident records and false of the archive. `memory-pressure` opens
on a host reported as swapping, `d01` is a host swapping with the working set
unmeasured, and the runbook is in reach at this bound.

The consequence was not a missed document. It was a gold set teaching the wrong
answer: with `precedent_exists: false`, an agent that correctly cited the
procedure scored as a **false precedent**, and one that refused scored as
correct. A dataset can be wrong in the direction of over-refusal, and this one
was. Refusal is a feature of this agent, which is exactly why a case that
rewards it wrongly is expensive.

`d01` now expects the procedure cited and `DRAFT-2508` refused. That is a
sharper test than the original: it separates "will not ground a claim on an
unreviewed note" from "will not answer".

`d02` and `d03` are the composite incident and are covered above.

### Novel (`e01` to `e10`)

`relevant` is empty, and this needs no waiver: these are TLS, DNS, deadlock,
clock skew and quota failures. No procedure in this corpus covers any of them,
and the corpus holds no counterpart record. The refusal is the relevance floor
working, not a judgement call.

### The time bound (`f01` to `f04`)

Relevance is whatever survives the bound, which is what these cases are for.
`f01` at 2025-09-01 and `f02` at 2025-08-01 are genuinely empty for their
failure. `f03` at 2025-10-01 names `INC-2350` alone: the runbooks are not
recorded until 2026-01-12, so the covering procedure does not exist yet.
Likewise `f04` at 2026-01-01, eleven days early.

That is the honest reason those cases carry no runbook, and it is checkable
against `recorded_at` rather than argued.

### Identity (`g01`, `g02`)

`g01` is the composite incident in a thinner view and is covered above. `g02` is
a disk latency incident: no procedure in the corpus covers disk latency, and its
only listed document is the one it must **not** cite, `INC-2446`, which is about
the same host and a different failure. That is the identity collapse in its
purest form, the right machine and the wrong incident.

Runbooks are listed when the procedure covers the failure being investigated,
not whenever the topic is adjacent. `container-resource-limits` appears on `b04`
and `c02` because a container limit is genuinely in question; it does not appear
on host-exhaustion cases that mention no container runtime.

## What is deliberately not judged here

Section-level relevance: which part of a relevant document a citation should
land on. Ground truth is `source_uri` because the two chunkers share no passage
ids, and nothing currently measures the section-level gap. See the `README.md`
section on what that costs.
