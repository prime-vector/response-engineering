# Plan

## What this is

A reference implementation of an agent-run incident response layer, built on [Open Agent Spec](https://github.com/prime-vector/open-agent-spec). It exists to demonstrate that production investigation can be defined as code, tested in CI and constrained by contract, rather than performed from memory on a bridge call at 3am.

It is a demonstration, not a platform. Success is a four minute video and a repo that a sceptical SRE can read and believe.

---

## Milestones

### M1: Scenario locked
**Done when:** `SCENARIO.md` is reviewed, the fixture satisfies the feed properties SCENARIO.md section 3 fixes, and no source material has entered the repo.

- [x] Composite scenario drafted
- [x] Fixture generator producing 13 problems across 15 days
- [x] Cadence fixed as asserted properties rather than against a reference chart. The chart was source material and could not enter the tree, so the item could never close as written. `fixtures/generate.py` now asserts the four properties section 3 owns: thirteen problems across fifteen days, all auto-closed, none acknowledged, uniform signature and severity.
- [x] Sanitisation review, first pass. Shape, figures and the twelve corpus documents that existed then read by the author; full-history mechanical sweep found one rule 5 break, fixed. The five distractors postdate the pass and are not covered by it. The second pass by another person is M5.
- [x] Precedent copy read for cause creep

### M2: Specs written
**Done when:** all five specs validate against OAS 1.6.0 and the role boundaries hold without overlap.

- [x] Incident Commander, holds the hypothesis board
- [x] Telemetry Analyst, consumes the problem feed and detects recurrence
- [x] Change Correlator, correlates change and package history against onset
- [x] Scribe, produces the timeline and the draft change record
- [ ] Comms, produces the stakeholder update

Cost Guardrail is deliberately excluded. It does not fit this scenario and forcing it in would weaken the demo.

### M3: Runnable
**Done when:** `oa run` executes the pipeline end to end against the fixture with no live platform.

- [x] Mock MCP adapter serving the `telemetry` surface on 8422
- [x] Mock MCP adapter serving the `change_registry` surface on 8423
- [x] `depends_on` chain wired commander to brief
- [x] Pipeline driver composing the acts as dataflow: correlator output into the commander's `correlation` input, the live board into the Scribe's timeline (`demos/investigate.sh`)
- [ ] Deterministic enough to record without retakes

### M4: Governance visible
**Done when:** all three failure modes are demonstrable on demand, not described.

- [x] Sandbox blocks a production state change and reports why
- [x] Output contract rejects a board missing its falsifying test
- [x] Attribution guard fires on third-party convergence without evidence

All three run from `demos/governance.sh`, which exits zero only when every failure mode behaves. The sandbox demo's `mitigate` prompt cooperates with the directed change deliberately: what blocks it is the allow list, so the demo proves the boundary belongs to the harness rather than to prompt wording.

Two of the three fail closed in the runner. The attribution guard is a different class of control: the agent's judgement made structural, with a schema backstop that rejects any board naming a third party below confirmed confidence without the guard triggered. The demo exercises both paths, the guard firing live and the guard-off board being rejected, but the firing itself remains the model's judgement. Say it that way; do not sell it as a peer of the sandbox.

This milestone proves the boundaries only. The narrated act three, blast radius stated, escalation for authorisation, Scribe's draft change record, is demo assembly plus Scribe's milestone and is not claimed here.

This milestone is the product. If it is not visible on screen, this is just another AI incident tool.

### M5: Public
**Done when:** the repo is public, the video is recorded, and the site points at both.

- [ ] Sanitisation review, second pass, by someone other than the author
- [ ] Repo moved to the org, once the brand decision is made
- [ ] Four minute walkthrough recorded
- [ ] README readable by someone with no context

### M6: Precedent Analyst

Full spec: `docs/precedent-analyst.md`

The fifth agent. Owns a retrieval surface over prior incident records and runbook documentation, hands the commander typed precedent alongside findings and correlation. Headline risk is the confident wrong precedent, so refusal and divergence are contract requirements, not tuning targets.

- [x] `interfaces/PRECEDENT.md` written, no implementation named
- [x] Adapter serving `precedent_archive`, cited passages, corpus manifest populated
- [x] `.agents/precedent-analyst.yaml` validates against OAS 1.6.0, runs standalone
- [x] `no_applicable_precedent` path and grounding guard both exercised
- [x] `demos/governance.sh grounding` passes fire and reject
- [ ] Evals baseline recorded
- [ ] Measured improvement documented with before and after
- [ ] `investigate.sh` composes three acts with recall in act one, typed precedent entering the board as supporting and never deciding evidence

**Done when:** a board cites precedent by `passage_id`, convergence still blocks on outstanding deciding evidence, and the README carries a results table the runner can regenerate.

#### Where this is up to

Phases 0 and 1 are merged. The surface is live and honest enough to consume: `python3 mock/adapter.py --surface precedent_archive` on 8426, 17 documents, 82 heading-aware passages, `corpus/eval.py` green on both chunkers, CI running the lot.

Phase 2 is merged. On the bridge view `recall` returns three precedents whose every cited `passage_id` resolves through `passage_get`, with citations byte-identical to the archive: `INC-2411` and `INC-2419` as `partial`, `INC-2288` as `superseded` with the `document_superseded_by` text reproduced so `SEC-STD-14 (2026-01-30)` is named. No draft passage is cited.

Four things the live runs settled, none of which `oa validate` or the conformance suite could have caught:

- **The provider rejects `anyOf` at the top level of a tool `input_schema`.** `precedent_search` declared one to express "at least one of `signature_terms` and `symptom_text`", and the runner passes the MCP schema through verbatim, so the request 400d before the model saw a tool. The either/or now lives in the tool description and `corpus/eval.py` asserts that instead. No conformance case could have found it: the suite never calls a provider.
- **A verbose query returns nothing, and this is two separate measurements.** At the bridge bound, `limit 8`: the reported symptom used whole as `symptom_text` scores 79 of 82 passages above zero and clears the floor 0 times. The signature type added to that same whole symptom scores 80 and still clears 0. Those are the dilution measurements. The separate experiment is the signature type on its own, which scores 54, clears 35 and returns the near miss. Re-measured after the distractors and the recency tie-break; the finding is unchanged and the counts moved with the corpus. Do not collapse the three into one sentence: the dilution figure and the near-miss figure come from different queries. Hence the prompt telling the agent to query distinctive terms and to query more than once, which is also what surfaces `INC-2288` on the denial-daemon axis.
- **A citation has to be copied, not retyped.** An early run truncated every `heading_path` to the document title and dropped the `> Summary` segment, which is the part that makes a citation checkable in five seconds. The prompt now pins the citation fields as verbatim.
- **`superseded` without the name is not a warning.** A run that correctly set `applicability: superseded` then wrote "this resolution is superseded" and dropped `SEC-STD-14` entirely. The qualifier had travelled: `document_superseded_by` is copied onto every passage of that document. It was the model that dropped the name, the same class of failure as the truncated heading, so it is pinned the same way: copy `document_superseded_by` into `divergence`, do not paraphrase it.

**What the adapter log can now tell you.** It used to log `tools/call {name}` and nothing else, so it verified *that* a call happened and never *what came back*, and claims of the shape "the trap was retrieved and rejected" were not checkable from it. The archive now logs what left the surface as well: a `hit {passage_id} {source_uri}#{ordinal}` line per passage returned by `precedent_search` or `passage_get`, plus the counts behind a search. Ids, uris and counts only, never passage text, because an audit trail that reproduces the archive is a second copy of it.

That closes the gap the grounding demo needed. It checks every cited `passage_id` against the returned set rather than against the output's own word, so an invented citation fails the demo, and it can report the working note as retrieved and uncited rather than asserting it. On the runs recorded below, `DRAFT-2601` was in the returned set and no precedent cited it.

What the surface work had already decided for the spec, all of it still true:

- **`as_of` is a required input field.** Both `precedent_search` and `coverage_describe` require `before`, and the runner substitutes only from keys present in the input, so a missing `as_of` reaches the model as literal template text and the run degrades silently.
- **The prompt passes the signature type, never the entity id.** `host.memory.exhaustion`, not `host.memory.exhaustion:intg-prod-a1`. Identity is not a similarity feature, and the archive holds records about this host.
- **The mitigate-style wording covers both calls.** "Do not report `no_applicable_precedent` until you have called `coverage_describe`" as well as the search, or the agent self-attests a refusal it never checked. Verify from the adapter log, never from the output.
- **`DRAFT-2601` is visible at the bridge bound and that is correct.** It was written by then. A draft working note is not evidence, so the spec has to handle it through `record_status` and the attribution guard rather than through the time bound. Do not move its date.
- **The near miss is `INC-2411`.** Same signature, resolution that would be actively wrong to repeat here. It is what `divergence` exists to catch.

Live `oa run` needs an API key and the `patches/` provider patch. `oa validate` needs neither.

Phase 3 is done, and both halves of it are live runs rather than surface behaviour. `demos/governance.sh` now runs five modes.

- **`grounding`, fire and reject.** Fire recalls against the bridge view: three precedents, `INC-2411` and `INC-2419` as `partial`, `INC-2288` as `superseded` naming `SEC-STD-14 (2026-01-30)`, every cited `passage_id` present in the adapter's returned set, no draft cited, and the near miss not offered as applying. Reject overrides the system prompt with `demos/grounding-stripped-system-prompt.txt` and is refused with `OUTPUT_SCHEMA_ERROR: 'grounded_in' is a required property`.
- **`refusal`, live.** `fixtures/novel-incident.json` is a separate invented incident, session establishment failing between a broker and its consumers, dated after every document in the archive so coverage is the whole corpus and the bound is doing no work. The run established coverage first, issued six queries, every one returning nothing above the floor, and reported `no_applicable_precedent: true` with `search_coverage` populated and the queries recorded verbatim. The demo asserts the calls from the log, so a refusal that searched nothing fails.

Two things the reject path settled. A soft stripped prompt does not force the failure: told only that it need not look things up, the model called the archive anyway, issued verbose queries, got nothing above the floor and correctly refused, and the run exited zero with no precedent to be ungrounded. The prompt has to name the precedent it is asserting from recall, exactly as the guard-stripped prompt names the party. And the override replaces the whole system prompt, so the retrieval guidance goes with it: a stripped run is not a plain run minus one rule.

Phase 4 is in progress. The dataset is written and the baseline table is not.

`evals/dataset.yaml` holds 38 cases against the 17-document corpus: 14 where no
applicable precedent exists, 7 near misses, and the rest split across precedent
that genuinely transfers, draft record status, the time bound and identity.
`evals/validate.py` asserts every claim the corpus can settle, against both
indexes, and runs in CI.

Two things the dataset settled, both of which change what the spec asked for:

- **Ground truth names documents, not passages.** `docs/precedent-analyst.md`
  specified `expected_passages: [<passage_id>, ...]`. Passage ids key on the
  chunker name, so the two indexes share none: 82 passages under heading-aware,
  39 under fixed, disjoint. The baseline is recorded against the fixed chunker
  and Phase 5 compares heading-aware against it, so passage-level truth would
  score zero on whichever index it was not written against and the whole Phase 5
  improvement would be the id scheme changing. Truth is `source_uri`. It costs
  the ability to distinguish a citation of the right document's `Resolution`
  from its `Gaps`, and that cost is unmeasured rather than mitigated: adapter-log
  groundedness proves only that a cited passage was in the returned set, so a
  citation of `Gaps` passes whenever `Gaps` was a hit, and the `groundedness` in
  the metrics table is a separate LLM-judge check that is not written yet. It
  belongs in the results table as a stated limit.
- **The dataset is hand-authored and has no generator.** Every other artefact
  derived from the corpus has a `--check` that fails on drift, so generating this
  one is the obvious move and it is wrong: ground truth generated from the
  retriever measures only that the retriever agrees with itself. The cases are
  made checkable instead, including the ones that could go vacuous. A case about
  rejecting the hindsight trap now fails if the trap stops being retrieved, which
  is the failure mode that hollowed out the grounding demo once the distractors
  widened the scoring band.

One early figure, and it is a floor rather than a baseline: on a single canonical
query per case at limit 8, the surface reaches 36 of 51 relevant documents under
heading-aware and 38 under fixed. One query per case where the spec tells the
agent to issue several, so a case probing one axis of a multi-axis incident is
counted as missing what its other axis reaches. That fixed currently edges
heading-aware is worth carrying into Phase 5 rather than explaining away: larger
chunks match more query terms, and whether heading-aware wins on the metrics that
matter is not settled in advance.

Grok's review of the dataset (PR #14) found the first version of that figure
inflated. Relevance had been scoped to what each case was testing rather than to
the incident, so a document a case's probe could not reach was often not listed
and never counted as a miss: four cases probing one incident disagreed about
which documents mattered. Relevance is now a property of (`as_of`, `symptom`,
`evidence`, `missing_evidence`), the judgements are recorded in
`evals/RELEVANCE.md`, and the figure moved from 36/41 to 36/51 with no change to
the retriever. The bookkeeping moved, not the retrieval.

---

## Definition of done for the demo

Three acts, four minutes, in this order:

1. **Day two.** Recurrence detected in the problem feed, standing condition attached. The predictive half.
2. **Day fifteen.** Bridge opens with change correlation already on the board. Hypotheses carry confidence and falsifying tests. Attribution guard fires.
3. **Mitigation.** Sandbox blocks the security control change, states blast radius, escalates for authorisation. Scribe drafts the change record.

**It closes on a blocked state, not a resolution.** Hypothesis unresolved, deciding evidence outstanding, the single command that would settle it, and what each outcome rules in or out. This is not a limitation to apologise for. It is the most credible thing in the demo.

---

## Non-goals

- Building an orchestrator or agent runtime. OAS plus external orchestration is sufficient.
- Competing with APM vendors on automated root cause analysis.
- Alert correlation. Correlation reduces noise. This investigates.
- Autonomous remediation. Every production state change requires human authorisation, by design and permanently.
- Generality. Incident investigation only. No adjacent use cases until this one is finished.

---

## Open decisions

| Decision | Status |
| --- | --- |
| Brand and org the repo lands under | Open. Blocks M5, nothing earlier. |
| Whether act one is a separate invocation or the first turn of the pipeline | Resolved during M3: a separate invocation of the Telemetry Analyst against the D+1 view. |
| Whether the mock adapter becomes its own package | The mock exists in-repo. Repackage only if a second consumer appears. |
| Who owns the change registry | Resolved: the Change Correlator, exclusively. The commander consumes the correlator's typed output through its `correlation` input, never raw registry rows, and declares no evidence surface at all. Its only surface is `host` actuation, bound by `mitigate` so the sandbox has something to block. |
| Comms boundary against the commander's `brief` | Open. Blocks the Comms spec, nothing earlier. `brief` already renders the board for bridge, incident manager and executive audiences; either it narrows to investigation-internal audiences, or Comms owns external stakeholders only. Leaning: Comms owns outward stakeholder updates (business impact, expectations, no board detail), `brief` keeps the three internal audiences. |

---

## Notes

Commercial objectives, pricing and pipeline are tracked outside this repository and must not be added to it.
