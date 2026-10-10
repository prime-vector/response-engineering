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
**Done when:** the five specs below validate against OAS 1.6.0 and the role boundaries hold without overlap. The Precedent Analyst is a sixth, tracked in M6.

- [x] Incident Commander, holds the hypothesis board
- [x] Telemetry Analyst, consumes the problem feed and detects recurrence
- [x] Change Correlator, correlates change and package history against onset
- [x] Scribe, produces the timeline and the draft change record
- [x] Comms, produces the stakeholder update. Owns outward audiences only and is never given the board: no evidence, no hypotheses, no correlation, no precedent, and no dedicated cause field in the output. A narrowing rather than a fence, because prose still travels.

Cost Guardrail is deliberately excluded. It does not fit this scenario and forcing it in would weaken the demo.

### M3: Runnable
**Done when:** `oa run` executes the pipeline end to end against the fixture with no live platform.

- [x] Mock MCP adapter serving the `telemetry` surface on 8422
- [x] Mock MCP adapter serving the `change_registry` surface on 8423
- [x] ~~`depends_on` chain wired commander to brief~~ **Removed, 24 Aug 2026, and it should never have been ticked.** The runner does not treat `depends_on` as documentation: it executes the dependency and merges its output into the dependent task's input flat, key by key. So the chain delivered `hypotheses`, `blocking_evidence` and the rest as separate top-level keys and never a `board`, which no prompt asking for one could have been substituted from, and it re-ran `assess`, the longest generation here, on every briefing. Wired is not the same as carrying anything, and only running the task tells you which of the two it was
- [x] Pipeline driver composing the acts as dataflow: correlator output into the commander's `correlation` input, the live board into the Scribe's timeline (`demos/investigate.sh`). `brief` is not one of the acts and the driver does not call it; it takes its board by the same composition, from a caller that has one
- [x] `brief` has its own prompt pair, its real inputs and its own contract, and has now been run. It had inherited the root pair written for `assess`: ten placeholders against one required input, all reaching the model as literal template text, asking for `assess`'s output shape rather than `brief`'s. Run once, on 24 Aug. The board it rendered and the briefing it produced are committed as `docs/samples/briefing-2026-08-24/`, because a claim about how the briefing behaves that a reader cannot open is not a claim: reading the two side by side is the only way to see what the schema cannot check. What is committed and checkable is the typed half: `suspected` entries carry `confidence` as an enum matching the board's and a non-empty `falsifying_test` as required fields, no undeclared fields, and `checks/briefing_grounded.py` compares each entry's confidence and precedent against the hypothesis it renders. The prose half is not, and that is a measurement rather than a caveat: four live renders across three prompt revisions each strengthened something the board hedged, a verb, a citation, and a count restated as a rate. All four are committed under `docs/samples/briefing-2026-08-24/`, including the current one, which still does it. That is the finding. A caveat carried as prose does not survive a change of format, which is what this project says about incident reporting and is now measured on its own agent. The class behind it is now checked: `checks/prompt_inputs.py` compares every prompt's variables against its task's required inputs in both directions, resolved the way the runner resolves them, and CI runs it. `oa validate` cannot see this, because neither half is invalid alone
- [x] Deterministic enough to record without retakes, **by recording verified footage rather than by making the model repeat itself**. Ticked, unticked and ticked again on 25 Aug 2026, and the route matters more than the verdict. Completion was the original failure and the streaming patch fixed it: three composed runs now complete, exit zero. Variation was then chased twice and neither attempt closed it. Two runs at the shipped `temperature: 0.2` agreed on twelve of fifteen narrative fields. A third at `temperature: 0`, run by editing the working tree and restoring it rather than committing a spec change, moved four fields the first two had agreed on, which settles nothing about temperature from one sample and is not worth a second: no field involved is one the script may speak, and the API is not guaranteed deterministic at 0 anyway. What the three runs did establish is the thing worth having. Every field the walkthrough is allowed to claim was identical across all three, through a temperature change: incident state, attribution guard present, convergence blocked, which hypotheses carry a citation. Every field `docs/walkthrough-claims.md` forbids speaking moved under every condition tried. So the tiering is measured rather than asserted, and the retake risk is closed by sequencing rather than by sampling: the acts run before the take, their output is checked against the claim list, and the narration goes over footage already known good. The Tier 2 guarantee survives that intact, since `governance.sh` exiting zero for the footage being shown is still that footage's own verdict, and a bad run then costs a re-run and a re-check rather than a re-record. Captures in `runs/2026-08-24-investigate-all`, `runs/2026-08-25-investigate-all` and `runs/2026-08-25-investigate-temp0`

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

- [x] Sanitisation review, second pass, by someone other than the author. Read in the week of 17 to 23 Aug 2026 by an observability engineer who knows the pattern this composite is drawn from, which is a stronger pass than a cold reader can give: someone who never saw the source material can apply the rules but cannot confirm an absence. Nothing identifiable found. Scope recorded rather than assumed, because the tree grew in four steps and only the dates say what was in it: eleven corpus documents landed 16 Aug, `DRAFT-2601` on 17 Aug, the five distractors on 18 Aug in `3706dd2`, and both `docs/samples/` directories on 24 Aug. Seventeen, which is the count `README.md` and M6 carry, and the twelve M1 records as read by the first pass are the 16 Aug eleven plus `DRAFT-2601`. The whole corpus was in the tree by 18 Aug and the read ran to 23 Aug, so the corpus was covered in full and the samples postdate the read. That gap is deliberate rather than outstanding: the samples are model output, the model only ever saw synthetic fixtures and the synthetic corpus, so it cannot emit source material it never had, and its one real exposure is naming a vendor in a causal role. The reproducible half of the pass is a sweep anyone can re-run and it is clean: no email addresses anywhere in tracked files, no routable IP other than loopback, no external hostname beyond `api.anthropic.com`, `github.com`, `genai.com.au` and `www.w3.org`, and four vendor mentions all in capability tables or market positioning rather than a causal role
- [x] Repo moved to the org. Already there: `prime-vector/response-engineering`, which is the standards home the brand decision put it under. **Still private**, and that is the separate condition in this milestone's done-when rather than a leftover of this item. Going public is now gated on nothing in the tree: the sanitisation second pass is done and recorded above, and the mechanical sweep in that item is the part a reader can re-run
- [x] Four minute walkthrough recorded. 4:37, uploaded unlisted on 7 Oct 2026: https://youtu.be/OTdecUh1C98. Over the four minute name on purpose, for the reason `docs/walkthrough-script.md` gives: the length is where the spoken copy and a phrased read came out, and words were not cut to a clock. The shot list's timings are cut from the recorded takes
- [ ] README readable by someone with no context
- [x] Mechanical sanitisation sweep, third pass, re-run 10 Oct 2026 against `main` at `a18f46f`, 141 tracked files, after the tree grew again in October: agent traces, the OpenTelemetry document, the model split and its measurements, the objectives. Clean on every axis the second pass recorded, stated as what each grep found rather than as a count: no email address in any tracked file; no IP beyond loopback; the external hostnames are the four named above plus `youtu.be`, the walkthrough link added on 7 Oct, and no other; no vendor is named in a causal role, which is rule 2 and the only thing a sweep for product names can attest, since no list of names is closed and where a name sits is a reading, not a grep. Three axes the second pass did not record were swept as well: the two record directories, `evals/results/` and `docs/samples/`, name the model provider and model ids, which is what a record of a run must carry, and no other vendor; no tracked file carries a rate, revenue figure, client name or pipeline detail; and the added and removed lines of every commit on every branch were searched for addresses and routable IPs, finding only the SSH form of the GitHub remote. Untracked files: none. What a mechanical sweep cannot do is confirm an absence of source material, which is why the second pass was a read by someone who knows the pattern, and nothing added since then was derived from anything but the generators and the model
- [ ] Walkthrough shot 3: the architecture still shows the Scribe filing the timeline, which it stopped doing in PR #42. Re-render the still from `docs/diagrams/architecture.svg` and replace that shot in the upload. The narration never mentions the filing, so only the label is stale

### M6: Precedent Analyst

Full spec: `docs/precedent-analyst.md`

The fifth agent. Owns a retrieval surface over prior incident records and runbook documentation, hands the commander typed precedent alongside the correlator's correlation. The Telemetry Analyst's findings are not composed into the board: act one is a separate invocation and `assess` has no `findings` input. Headline risk is the confident wrong precedent, so refusal and divergence are contract requirements, not tuning targets.

- [x] `interfaces/PRECEDENT.md` written, no implementation named
- [x] Adapter serving `precedent_archive`, cited passages, corpus manifest populated
- [x] `.agents/precedent-analyst.yaml` validates against OAS 1.6.0, runs standalone
- [x] `no_applicable_precedent` path and grounding guard both exercised
- [x] `demos/governance.sh grounding` passes fire and reject
- [x] Evals baseline recorded, both halves. Retrieval: `evals/runner.py`,
      `evals/config.yaml`, the fixed-chunker baseline in `evals/results/`, and
      a `--check` in CI. Judgement: `evals/judgement.py`, one live `oa run`
      per case, the deterministic rates read off the typed output and the
      adapter log, and `groundedness_judge` and `divergence_quality` judged at
      the prompts committed in `evals/judges/`
- [x] Measured improvement documented with before and after. Three arms
      recorded, both comparisons run, and the README states what was kept,
      what was rejected and the latency accepted for it
- [x] `investigate.sh` composes three acts with recall in act one, typed precedent entering the board as supporting and never deciding evidence

**Done when:** a board cites precedent by `passage_id`, convergence still blocks on outstanding deciding evidence, and the README carries a results table generated from the records rather than typed. The retrieval half regenerates from the corpus and the dataset; the judgement half is a grid derived from three committed run records, because a live sweep does not reproduce and a promise that it does is one the artefacts cannot keep.

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

Phase 4 is done, both halves. The dataset and the retrieval baseline came
first; the judgement metrics followed and are described after them.

`evals/dataset.yaml` holds 38 cases against the 17-document corpus: 13 where no
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
  the metrics table is a separate LLM-judge check, written since as
  `groundedness_judge` and closing neither gap. It
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
query per case at limit 8, the surface reaches 36 of 60 relevant documents under
heading-aware and 38 under fixed. One query per case where the spec tells the
agent to issue several, so a case probing one axis of a multi-axis incident is
counted as missing what its other axis reaches. That fixed currently edges
heading-aware is worth carrying into Phase 5 rather than explaining away: larger
chunks match more query terms, and whether heading-aware wins on the metrics that
matter is not settled in advance.

The runner turned that observation into a measurement and found the reason. It
reports two hit rates, because the dataset supports two different questions.
Ranking documents with nothing truncating asks which prior records the surface
orders highest; counting what survives inside a fixed eight-passage budget asks
what a caller under that budget gets, and chunk size decides how many distinct
documents fit. That budget is an eval parameter rather than the agent's, which
took Sol's fifth pass to catch: nothing binds the agent to eight, the surface
defaults to five, and the spec deliberately tells the agent to ask for breadth
without naming a number.

**The first version of this paragraph said the ranking was chunker-blind, and
that was wrong.** Both indexes do give identical hits at k = 1, 3, 5 and 8, which
is the grid the baseline reads. They differ at k = 2: heading-aware reaches 25 of
60 pairs against fixed's 24, because `b03`'s `INC-2446` is rank 2 under
heading-aware and rank 3 under fixed. The configured grid steps over the gap that
difference lives in. Grok found the overstatement in review; the k = 2 figure was
then measured rather than argued.

Two things follow. The narrower claim is that the chunkers are indistinguishable
at the k values this baseline reads and distinguishable one rank above the first
of them, so Phase 5 has to report both the ranking and the budget rather than
either alone. And a claim about two indexes cannot live in a table generated from
one: `evals/results/chunker-comparison.md` scores both at every k from 1 to the
deepest rank any relevant document reaches, the k values are found rather than
chosen, and CI regenerates and diffs it. It scores both indexes at the passage
budget as well, which took a second pass to get right: the first fix moved the
ranking comparison into a checked artefact and left `38/60 against 36/60` typed
into three documents, with only the `38/60` half inside anything CI could
falsify, because `latest.md` is the baseline index alone. Sol found that at the
gate. Fixing a cross-index claim for one metric and leaving the metric it is
contrasted with unchecked is the fix stopping one line short.

The tables are generated and CI checks them, so they carry no timestamp and no
latency figure: they are a function of the dataset, the corpus and the config,
and nothing else. The runner refuses to record a baseline when the corpus has
moved off the dataset's pin, when the config's chunker disagrees with the index
it names, or when something is already answering on the port it was told to use,
and it proves the adapter it started is serving the index asked for by resolving
a passage id from it. `--compare` refuses two runs that differ in corpus, ground
truth, relevance floor, passage budget or k list, because each of those deltas
is that input moving rather than retrieval improving.

Judgement mode was designed here and is written, below. What this section got
right is why it had to be separate: `false_precedent_rate`,
`no_precedent_accuracy`, `false_refusal_rate` and `divergence_quality` each need
one live `oa run` per case, an API key and the `patches/` provider patch, and
they score the agent on the queries it issued rather than on the dataset's
canonical probe. Case `a04` is why that distinction matters: its probe is the
reported symptom used whole, which clears the floor zero times, so an agent that
copied it would refuse where the archive held precedent, and that refusal would
be a real false refusal. What this section got wrong is where the queries come
from. They are read from the adapter's log, not from
`search_coverage.queries_issued`, which is the agent's account of its own
conduct. The retrieval table still lists every one of these as unmeasured, with
where it is measured instead, because a table listing only what it measured
reads as a complete one.

Grok's review of the dataset (PR #14) found the first version of that figure
inflated. Relevance had been scoped to what each case was testing rather than to
the incident, so a document a case's probe could not reach was often not listed
and never counted as a miss: four cases probing one incident disagreed about
which documents mattered. Relevance is now a property of (`as_of`, `symptom`,
`evidence`, `missing_evidence`), the judgements are recorded in
`evals/RELEVANCE.md`, and the figure moved from 36/41 to 36/60 across five rounds of review, with no
change to the retriever. The bookkeeping moved, not the retrieval.

`evals/judgement.py` is the other half, and it measures the agent rather than
the surface: one live `oa run` of `recall` per case, the arm's index, the arm's
system prompt. The runs are not regenerable, so no CI job can diff a fresh
sweep against a committed one, and the record carries a timestamp, the spec,
the prompt, the model and the case ids instead. Everything derived from those
records is diffed: the per-arm tables, the Phase 5 grid and the copies of it
injected into the two documents that publish it.

Two kinds of number, never in one table. Deterministic:
`false_precedent_rate`, `no_precedent_accuracy`, `false_refusal_rate`,
`groundedness_log` and `agent_reach`, every one of them a consequence of the
typed output, the adapter's audit log and the ground truth. Judged, by a
different model family with the prompts committed in `evals/judges/`:
`groundedness_judge` and `divergence_quality`. Putting a judged figure beside a
deterministic one makes it read as the same kind of fact.

**How much that matters is now measured.** The same claims scored 38 of 52
under `claude-opus-4-6` at temperature 0 and 17 of 52 under
`cursor-grok-4.6-high`, which cannot be set to a temperature at all and whose
rounds were probed on two routes rather than against every checkout, the
masking of which came afterwards. The first
is what the published figures use, because that transport has no file tools, and the ordering between arms held under both. So the
level of a judged metric belongs to the judge. The ordering has held in every round the records
carry, five under the metered judge and three under the CLI one, which makes it
an ordering nobody has seen flip rather than a property of the arms established
across judges. `divergence_quality` moved by one claim in total across three arms,
because that judge is given the dataset's distinguishing factors and asked
whether the text names one: a closed question ports across families, an open
one does not.

`agent_reach` is the figure neither mode had. Retrieval mode issues one
canonical probe per case, which the eval documents are careful to call a floor
on the surface rather than an estimate of the agent. This counts relevant
documents the archive actually returned across the queries the agent chose, so
the one-query limit does not apply to it, and it is not comparable to
`precedent_hit_rate@k`: no rank truncates it.

**The identity rule was checkable only from the agent's own report, and now is
not.** `queries_must_not_contain` is about what the agent asked the archive,
and the only record of that was `search_coverage.queries_issued`, which is the
agent's account of its own conduct. The archive now logs `args <tool>
<arguments>` beside every call. Caller text, never archive text. On the sweep
below, 182 searches were issued and 182 reported, no entity id in any of them,
and both halves of that are now measurements rather than one measurement and
one assurance.

**The shipped configuration, recorded.** Heading-aware index, the spec's own
prompt, 38 cases, `claude-sonnet-4-6` at temperature 0.2, zero runs rejected or
unparseable. `false_precedent_rate` 0 of 52 claims, `no_precedent_accuracy` 13
of 13, `false_refusal_rate` 0 of 25, `groundedness_log` 138 of 138 cited
passage ids in the set the surface returned, `agent_reach` 54 of 60 pairs, p50
26.9s and p95 52.8s per recall. The full table is
`evals/results/judgement-heading.md`.

Read the two things the deterministic rates cannot say by themselves. Ten of
the 52 claims are offered as `partial` where the truth is `applies`, so the
zero false precedent rate is a partly cautious agent rather than a calibrated
one, and the table says so beside it. And `groundedness_judge` is 73.1%: 38 of
52 claims are supported by the passages they cite, and most of the other 14 are
the same move, an absence asserted from silence. Judged by the other family the same claims scored 17 of
52, which is why that figure is a comparison and not a score. "INC-2411 shows no audit
daemon" is a claim about a document from passages that simply do not mention
one. It is a divergence in the shape the prompt asks for, resting on something
the archive never said. The log check cannot see this at all: every one of
those citations is a passage the surface really returned.

**Two cases cited a draft, and the interesting part is how.** `d01` cited
`DRAFT-2508` and `g01` cited `DRAFT-2601`, both as `applicability: partial`,
`confidence: speculative`, with a `divergence` that says in words that the
document is unsubmitted, cannot be the basis of a precedent claim, and is
surfaced only to flag that it exists. That is an agent trying to be transparent
and having nowhere to put it: `precedents[]` has no entry meaning retrieved and
rejected, so the choice is to drop the draft, which makes the trap invisible,
or to type it as precedent and carry the caveat in prose. Prose is exactly
where this project says a caveat must not live. It is a gap in the output
contract rather than a tuning problem, it is on the board rather than fixed
here, and it was found by measuring, which is the argument for judgement mode
in one line.

Phase 5 is done. Three arms recorded, one live sweep each, 38 cases, nothing
rejected or unparseable in any of them. `--compare` refuses two records that
differ in more than one thing, and says in its own output that one sweep is one
sample of a stochastic system.

**The rule 4 paragraph is kept, and it is the one that mattered.** Replacing it
with a single search carrying the whole reported symptom costs 8 false refusals
in 25 answerable cases, against none, and drops reach from 54 of 60 relevant
pairs to 22. Every case in the composite scenario itself refuses: `a01` to
`a04`, the incident this repo is built around, all four report no applicable
precedent. Median one search per case against five, 43 searches against 182. It
is twice as fast, p95 27.1s against 52.8s. Half the latency for a third of the
reach.

That is the Phase 2 dilution measurement reaching the agent's answers. It was a
property of the surface then, 79 of 82 passages scoring above zero and 0
clearing the floor; it is now a false refusal rate.

**The arm measures the paragraph, not query count, and the first version of
this section claimed the second.** Rule 4 carries two instructions and the
replacement drops both: query more than once, and ask for breadth because the
surface caps how many passages one document contributes. The sweeps show the
second doing real work. The shipped arm passed `limit: 8` on 157 of its 182
searches; the alternative passed no limit at all on 41 of its 43 and took the
surface default of five. So the reach collapse mixes fewer queries with a
smaller passage budget. `--compare` cannot catch this: a system prompt is one
knob to it, and two instructions inside one paragraph are one knob to
`--check-prompts` as well. Grok found it in review of PR #17. Separating them
needs a fourth arm that keeps the breadth instruction and changes only the
repeat instruction; it is not run.

**The three records do not pin the runtime that produced them.** They were made
before the CLI version and the provider module were recorded, so "one install,
one session, one input changed per arm" is an assertion by the author rather
than something the artefact establishes. `--check-records` reports it per arm
and calls for a fresh sweep, which is the only remedy. The provider patch is
evidenced by the runs themselves, because an unpatched install fails the first
tool call and these made 388 successful ones; the CLI version is not.

**The chunker is not choosable off these numbers, and saying so is the result.**
Heading-aware and fixed reach the same 54 of 60 pairs and omit 14 and 13 of the
23 applying documents the archive handed over. The judged half parts by more
than a wobble under one judge and inside it under the other: 38 of 52 against
48 of 56 under Opus, about ten points, and 17 of 52 against 19 of 56 under
Grok, two claims. Heading is below fixed in every judging the records carry.
Each round judged both arms with the same code, prompts and model, so the
ordering rests on every matched comparison the records hold, three metered and
three CLI, plus
four earlier rounds whose transport predates the field and is therefore not
recorded rather than assumed to be either; the rounds are not equivalent to each other, so
neither the two to four claims an arm moves within a family nor the forty
points it moves across families is published as a variance figure. One sweep each, with a judge scoring a
model, is not enough to choose on, which is a different statement from the two
being indistinguishable, and the first version of this section made the second.

`d01` is where they differ deterministically, and not symmetrically. Both
indexes returned the covering procedure. Under heading-aware the agent offered
only the barred draft, as `partial`, and cited the procedure not at all; under
fixed it refused the case outright. Two different failures. Until
`applies_omission_rate` existed, neither appeared in a headline rate: the first
looked like a clean answer and the second like a clean refusal.

Heading-aware stays, for something no metric here scores. Its citations carry
the heading chain, `INC-2411: ... > Resolution`; fixed chunks carry the
document title alone, because there is no heading to carry. That is the part
that makes a citation checkable in five seconds. It is a property, and it is
recorded as a property rather than dressed up as a measured win.

**`groundedness_judge` is higher in both alternatives, and only one of them has
an explanation.** The single-query arm made 22 claims against 52, and the
failure the judge catches is a divergence asserting an absence the passages
never state, so there is more of it where there is more divergence text. The
fixed arm made 56, more than the shipped arm, and still had more supported.
Why is not established. The first version of this section said "they make fewer
claims", which is false for the arm that makes more, and explaining a result
away with a sentence that does not apply to it is worse than leaving it
unexplained.

**A zero false precedent rate was the wrong headline.** Across all three sweeps
the agent offered `partial` 113 times and `superseded` 17 times and `applies`
not once, so the rate could not fire. `applies_omission_rate` is the row that
catches what it cannot: 14 of 23 documents the ground truth says apply here,
returned to the agent by the archive and never offered as precedent at all,
mostly the covering runbook procedures. Nothing overclaimed, and the responder
still does not get the thing that applies. Every other rate is blind to it,
`agent_reach` included, because the archive did return them. Grok found the
instance, `d01`; the class is 14 pairs under heading-aware and 13 under fixed.

**The second experiment is no longer the reranker, and the reason is written
down rather than quietly dropped.** `docs/precedent-analyst.md` named "hybrid
with versus without the reranker", and there is none in this repo to switch
off: the mock ranks by term overlap and the runner refuses a config that
declares one. A local cross-encoder would put a model dependency inside a
directory whose retrieval half deliberately runs on stdlib and PyYAML. The
retrieval guidance is the configuration this project actually decided, on a
measurement, so it is the one worth testing. Its arm's prompt is derived from
the spec with that one paragraph replaced, and CI fails when the spec moves
under it: an override replaces the whole system prompt, so a hand-maintained
one drifts into being a second prompt and the delta then belongs to nothing.

Phase 6 is built. `demos/investigate.sh` recalls in act one at the day-one
bound and composes that typed precedent into the board act two draws, and it
asserts what the precedent did rather than that it arrived. On the board
recorded at the bridge bound before the move: five distinct passages cited six
times across three of four hypotheses, every id resolving through the adapter
log to the document the archive returned it from, no hypothesis above
`plausible`, five blocking items outstanding, convergence blocked, and
`SEC-STD-14` named where the superseded record was used.

The board from act one's recall cites `INC-2411` three times, `INC-2419` three
times and the memory-pressure runbook once, across two of four hypotheses, both
`speculative`, four items outstanding, convergence blocked, every id resolving
through act one's adapter log. It did not come through `oa run` on the day it
was drawn: four `assess` runs in a row died with `Remote end closed connection
without response`, minutes into a request the same call had completed twice
earlier that day, and removing the prompt-caching patch changed nothing. The
same request with streaming enabled returned a complete, contract-valid board in
79 seconds. The model produced it and the contract accepted it; what failed was
the CLI's non-streaming delivery. The third patch in `patches/` streams and the
composed pipeline now draws the board through `oa run`, act two end to end in
one minute forty-eight. It stays a known limit because an unpatched CLI still
has it.

**Recall runs in act one, and it took two goes to land there.** It was built at
the bridge bound on the argument that the board is assembled there and that
`DRAFT-2601` being returned and not cited is the archive's strongest live
moment. The pre-merge gate pointed out what that argument had not weighed:
`SCENARIO.md` fixes recall in act one and is the source of truth every other
document derives from, and the rejection of the working note already has its
own demo in `demos/governance.sh grounding`, which recalls at the bridge bound
for exactly that purpose. Repeating it in the pipeline bought a second showing
of something already shown, at the cost of the property the scenario actually
wants: at D+1 the note does not exist, so the bound puts it out of reach rather
than leaving an agent to decline it. Act one recalls, act two draws the board
from what act one found, and the day-one half of the story is demonstrated
rather than narrated.

Nothing in the corpus falls between the two bounds except the working note, so
a board citing act one's recall cites documents that are all still current at
the bridge. `symptom` is passed empty on that view rather than omitted, because
the runner renders a missing key as literal template text, and the query is
then the signature type off the signals, which is the query the measurements
favour.

**The supporting-not-deciding property is in the contract now, not in the
prompt, and it is narrower than the first wording of this paragraph claimed.**
`precedent_cited` on a hypothesis is the only field on the board a passage id
can appear in; `blocking_evidence` is closed, so the list convergence blocks on
cannot carry one as data; `convergence_allowed` must be false while any item is
`still_outstanding`, which is now a required field; and a hypothesis carrying a
citation cannot be `confirmed`. That closes the typed routes. It does not close
prose: an item whose description asserts a passage settled it, marked not
outstanding, converges, and the gate caught that sentence claiming otherwise.
The board authors the list it is held to and the schema never sees the view
behind it, so what is left is a responder reading the board. The hole is a case
in the invariant suite rather than a caveat in a document.

**Checking that convergence rule against boards that already existed found a
different defect, which is the argument for checking.** Three `assess` runs on
the attribution fixture, before any of this went in, were all rejected on
`next_actions[].reversible`: `'false within incident window if security
control is altered'`, `'depends_on_specific_action'`, `'true'`. Under
convergence pressure the board qualifies reversibility and the field is a
boolean, so `demos/governance.sh attribution` was failing on its main path for
that and nothing else. Fixed in the prompt and in the field's description, in
the shipped prompt and in both stripped ones: a stripped prompt has to differ
from the shipped one only in the control it removes, or the demo asserts the
wrong rejection. Both governance modes pass again.

The acceptance run then failed the same way once more, on an optional string
emitted as `null` where the prompt had said to omit a field it has nothing for
and never said that `null` is not an omission. Same fix and the same three
prompts. Neither defect touches precedent: both are the board hedging a field
whose type does not allow it, and both were only visible from running the
thing.

**Review found the fourth rule resting on an unpinned string, which is the
class the first two defects belong to as well.** `confidence` was a free string
whose scale lived in its description, so `not: {const: confirmed}` closed one
spelling and a cited hypothesis at `Confirmed` would have satisfied the rule
while breaking it. It is an enum now, with `incident_state` and
`next_actions[].intent`, the treatment `brief.audience` already had. The
boolean sentence named the two flags on `next_actions` and missed the two on
the board itself, one of which carries a "false while X" rule, which is exactly
the shape that produced the `reversible` failure; it now names all four. The
other specs are pinned now, and the live run each was going to cost was already
on disk. `precedent-analyst` had been done alongside its own work, leaving
`change-correlator`, `scribe` and `telemetry-analyst` as free strings. Only
`telemetry-analyst` did not already state the scale in its prompt, which is the
`intent` rejection below waiting to happen a second time, so it states it now.
The recorded outputs of the 24 Aug three-act run answer what the live run was
for, and are committed as `docs/samples/confidence-scale-2026-08-24/` so the
count can be recounted: 49 confidence values across those three tasks, every one
in the scale and in the right case, so the enum rejects nothing those agents
actually produced. One run each is not proof they cannot write `Confirmed` under
other conditions. The prompt naming the values is what makes that unlikely; the
enum is what makes it loud instead of silent.

That citation first said 55, which is the count across all five tasks in the
capture rather than the three this touches, and it named a path under `runs/`
that nobody could open. The rule in `.gitignore` is that a cited capture is
committed or the citation goes, and it earned its place: committing the files
made the number countable and the number was wrong.

**The scale is one vocabulary and is checked as one.**
`checks/contract_invariants.py` reads every `confidence` a task output declares
across all six specs and holds each to the commander board's enum, both values
and order, and fails on any form it cannot read through rather than walking past
it. It took two reviews to get that right, and both found the same shape of
defect: a claim about what the check refuses, and a route around it. First a
`$ref` on the confidence field was reported while one on the field's parent was
not, which is the shape a shared finding object in a `$defs` block actually
takes. Then `required: [confidence]` beside an `additionalProperties` schema,
which declares and constrains a confidence with no `properties.confidence` for a
walker to find at all. Each time the scale could drift under a green check and
under a summary line saying they all agree.

What closed it was enumerating the routes instead of the sightings, and it took
two goes to enumerate them, because the first pass reasoned over subschemas and
a schema does not need one. A schema pins the value of a property in exactly two
ways. It applies a subschema to it, in which case the property is either named
under `properties`, which the walker reads, or reached by indirection, by
matching its name, or as one of the ones nobody named: six keywords. Or it
asserts the whole object against an instance literal with `const` or `enum`, no
subschema anywhere, which is how `const: {confidence: high}` pins a scale with
nothing for a walker to find.

Eight keywords, and the closure argument is over JSON Schema's vocabulary rather
than over anything anyone has written. Two are reported only when their literal
holds a mapping at any depth, because a string `enum` is how a scale is declared
and a scalar `const` is how the commander's rules narrow one: report those and
six declarations and nine narrowing rules go red at once. The depth is
unbounded, which took a round of its own: a list of lists of objects is as valid
a literal as a list of objects.

`propertyNames` was in the set for a round and is not one of the eight. It
applies its subschema to property names and never to their values, so it cannot
pin a confidence at all. Rejecting it was conservative and sounded harmless, and
was not: a member nobody can derive turns the case split back into a list, which
is the defect the split exists to prevent. A self-test now asserts it is not
reported, so putting it back costs a red case and an argument.
`additionalProperties: false` is exempt for the same shape of reason, since
forbidding what was not named is the opposite of hiding something in it. A form
a check cannot read is not a form to skip. It is the claim failing.

Four review rounds went into that one sentence, and the round count is the
finding rather than the sentence. Five of the eight findings on this change were
the same defect: a claim that a set was closed, where the set had been assembled
by thinking hard rather than derived from anything a reader could check, so each
round widened the list and the next found a member that was not on it. The two
checklist items that came out of it are 7 and 8 under "Before asking for a
review". Item 8 is the test that would have ended this at round one, in about
ten seconds and without a reviewer: a completeness claim needs a case split, and
if you cannot state the question the set answers, you do not have a closed set.
Item 7 is the cheaper fix nobody tried for four rounds. In every one of those
five findings the code was defensible and the sentence was the blocker, and the
gap can be closed from either end.

The first version of the check held the briefing to the board and nothing else,
which left the four analysts free to drift from the vocabulary their claims are
carried in. What is still not checked, in the current one, is whether an output
carrying a claim declares a confidence at all: that stays the rule in CLAUDE.md with the Comms agent as its one written
exception, and the check says so rather than leaving a reader to assume
otherwise. Its `--self-test` drives the branches no spec reaches while the
scales agree. Every guard is mutation-tested, and every member of those three
tuples separately, which is not the same thing: mutating a tuple wholesale
showed the loop mattered while `$recursiveRef` sat inside it with no case
touching it, so the sentence claiming coverage was true of the loop and false of
the set. That includes the guard that keeps
a `not: {const: confirmed}` rule from being counted as a declaration and
reported as a drift against the very scale it narrows.

**A schema that pins a vocabulary the prompt does not state is a rejection
waiting to happen.** The first live board after the enums went in invented
`guard_evidence_integrity` for `intent`, whose four values had never appeared in
the prompt, and lost the whole board. `confidence` and `incident_state` were
already stated there, which is why they did not fail. All three are stated now,
in the shipped prompt and both stripped ones.

**The rules are checked without a model now.** `checks/contract_invariants.py`
validates twenty-one boards against the contract read out of the spec, asserting
both that each violation is rejected and that its legitimate neighbour is
accepted, and CI runs it. They were previously exercised only when a live board
happened to try one.


### M7: Agent traces

**Done when:** each demo can be run with runner-side traces collected locally, and a check reads them and fails when a stage did something it should not, as a second verdict independent of the driver's.

- [x] CLI moved to OA 1.6.2 (PR #38). Of the four fail-open behaviours this repo documented, 1.6.1 fixed one, a missing contracts extra, which now stops the run with `CONTRACTS_UNAVAILABLE`. The other three remain and their sentences say so. The three provider patches apply unchanged
- [x] Local collection with no vendor in the path (PR #39): `demos/agent_traces_sink.py` receives OTLP over HTTP and keeps span names, status codes and attributes, never events or status messages; `demos/retry.sh` adds `--telemetry` only when a collector is configured
- [x] `checks/agent_traces.py`, a check per stage: no unvalidated output, no undeclared sandbox, a blocked call recorded as prevented, an expected write backed by a successful tool span (`--expect-write`, which act three used until the driver took over the timeline filing), per-mode expectations counted per verdict, and no pass on an empty file. Self-tested and mutation-tested in CI
- [x] `demos/traced.sh` runs either driver with agent traces on and checks them after
- [x] Accepted on a live run, 8 Oct 2026, on OA 1.6.2. `traced.sh all` passed on both verdicts: seven stages, each with the verdict expected of it. The first attempt failed on a rejected API key and showed that 1.6.2 records a provider failure differently from what a reading of the runner suggested; the signature the check now uses is taken from that trace (PR #40), and it tells a failed model call apart from an adapter that was down
- [x] **The Scribe's reply can differ from the timeline it filed.** Found by the same acceptance run: `traced.sh investigate` passed the trace check and failed the driver, because `checks/timeline_filed.py` found the reply's entries and gaps hashing differently from the payload the sink accepted. Two replays from the same board both passed, so it is occasional, one in three runs seen, and the failing run had the longest payload. A task that files with a tool call generates its payload twice, and nothing makes the copies equal. Landed option B: the agent writes, the harness files through `demos/file_timeline.py`, leaving one generated copy; `--expect-write` on `checks/agent_traces.py` has no current caller.
- [x] Somewhere to look at them. `checks/agent_traces_sli.py` computes one record per stage attempt and a set of indicators from the spans, each tagged with its source, and `demos/agent_traces_report.py` renders the page; `demos/traced.sh` writes both beside the spans. Handoff integrity is the stage check's result and content integrity is the driver's, shown side by side rather than recomputed; the committed investigate sample is the run where the two disagreed. A baseline across runs exists as `--aggregate`, and since 9 Oct it is held to `checks/agent_traces_slo.yaml`, the one place a target lives, with `--baseline` rendering each objective met or missed across runs
- [x] Named for what they are. Agent traces are OpenTelemetry spans over OTLP with the GenAI semantic conventions; `docs/agent-traces.md` states the span model from the runner's own module and live files, the README says the local sink is one OTLP destination among any, and the incident telemetry interface keeps the two words apart (PR #45)
- [x] Held to objectives. `checks/agent_traces_slo.yaml` is the only place a target lives: six per-run objectives that are contracts, one rolling budget on the driver's pass rate, and p95 latency ceilings per stage and end to end, set on the eight-run baseline of 9 Oct 2026. The aggregate evaluates against it and `demos/agent_traces_report.py --baseline` renders each objective met or missed across runs with one row per run and a sparkline per stage; `demos/agent_traces_baseline.sh` regenerates `runs/baseline.html` (PR #46)
- [x] A model refusal read as a transport failure. Sonnet 5.5 returns the mitigation directive as `stop_reason: refusal` with no content blocks, and the streaming patch reported that stream as cut: `PROVIDER_ERROR`, an abandoned attempt in the trace, and a signature `demos/retry.sh` would retry once and pay for twice. Found 9 Oct 2026, fixed 10 Oct: the patch returns a refusal whole, with its `stop_reason` and `stop_details`, and the shared post helper fails naming it on both transports, since unstreamed the tool-loop path had been returning the empty reply as a final answer. `checks/stream_probe.py` holds the recorded events and both transports, and reads the retry signature out of `demos/retry.sh` to hold the two apart; `checks/retry_probe.sh` holds the wrapper to one attempt. Observed live through `oa_run` on 10 Oct: exit 1, the refusal named, one attempt, no tool call. The trace signature is unchanged, `PROVIDER_ERROR` with `execution_failed`; the name is on stderr
- [ ] A CI probe for `demos/traced.sh`, so its routing, sink lifecycle and exit statuses are exercised without a live run, and a decision on whether the sink should allowlist attributes rather than keep what OA sends
- [ ] One trace per pipeline rather than per stage, waiting on OA issue #116 (TRACEPARENT)

---

## Definition of done for the demo

Three acts, four minutes, in this order:

1. **Day two.** Recurrence detected in the problem feed, standing condition attached, and the archive asked at the same bound: precedent arrives already bounded, and the working note written later in this incident is out of reach rather than declined. The predictive half.
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
| Brand and org the repo lands under | Resolved 27 Jul 2026: `prime-vector/response-engineering`, beside Open Agent Spec, with Genai Pty Ltd credited as the practice that builds and maintains it. See Where this sits in `README.md`. |
| Whether act one is a separate invocation or the first turn of the pipeline | Resolved during M3: a separate invocation of the Telemetry Analyst against the D+1 view. |
| Whether the mock adapter becomes its own package | The mock exists in-repo. Repackage only if a second consumer appears. |
| Who owns the change registry | Resolved: the Change Correlator, exclusively. The commander consumes the correlator's typed output through its `correlation` input, never raw registry rows, and declares no evidence surface at all. Its only surface is `host` actuation, bound by `mitigate` so the sandbox has something to block. |
| Comms boundary against the commander's `brief` | Resolved 19 Aug 2026. Comms owns outward stakeholder updates; `brief` keeps its three internal audiences, now a real enum: `bridge`, `incident_manager`, `executive_sponsor`. Pulling that thread found `brief` had no prompt of its own and inherited one written for `assess`, so the audience never reached the model and the other placeholders arrived as literal text. Fixed 24 Aug 2026: its own pair, `board` as a real input, `depends_on` removed, and the first run the task has ever had. The line is what the output is derived from rather than who reads it: `brief` renders the hypothesis board, Comms renders impact and never sees the board. An unconfirmed hypothesis reaching people who cannot weigh it, in writing, is the failure this project criticises. Be exact about how much the schema buys: the board is structurally absent, and there is no dedicated cause field in the output, which is a real narrowing. It is not a fence. `impact` and `work_in_progress` carry prose, so a caller who writes a suspicion into an impact line has put one in front of the agent. Same class of control as the attribution guard, not a peer of the sandbox. |

---

## Notes

Commercial objectives, pricing and pipeline are tracked outside this repository and must not be added to it.
