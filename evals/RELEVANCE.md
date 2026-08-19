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
from 36/41 to 36/51 with no change to the retriever.

**Consequence two: relevance still has to discriminate.** A document is relevant
when it would change what the responder does or believes: the shape matches, or
it warns against the obvious wrong move. Sharing a signature type is not
sufficient. If every memory case listed every memory document, `hit_rate` would
measure nothing at all.

So relevance is neither "everything that matches the signature" nor "what this
case wants to talk about". It is what a responder holding this view would want
in front of them.

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

Single-axis cases where the shape decides it: `b01` to `b07` name the one prior
record that matches and diverges, `c01` to `c08` name the record that transfers
plus the procedure that covers it, `f03` names the one document in bound whose
shape matches.

Runbooks are listed when the procedure covers the failure being investigated,
not whenever the topic is adjacent. `container-resource-limits` appears on `b04`
and `c02` because a container limit is genuinely in question; it does not appear
on host-exhaustion cases that mention no container runtime.

## What is deliberately not judged here

Section-level relevance: which part of a relevant document a citation should
land on. Ground truth is `source_uri` because the two chunkers share no passage
ids, and nothing currently measures the section-level gap. See the `README.md`
section on what that costs.
