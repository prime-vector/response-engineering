# Precedent Analyst: Build Spec

> An addition to Response Engineering. Read `SCENARIO.md`, `CLAUDE.md` and
> `interfaces/TELEMETRY.md` first: this agent follows the same rules and must not
> introduce new ones. Work through the phases in order; each has acceptance criteria.

---

## 1. What this adds and why

The fifth agent. It owns a retrieval surface over prior incident records, runbook
procedures and postmortems, and hands the Incident Commander typed precedent
alongside the Telemetry Analyst's findings and the Change Correlator's correlation.

The reason it belongs here rather than in a separate project: an investigation layer
that cannot recall what happened last time is reconstructing from memory, which is the
exact failure the repo exists to fix. The precedent is evidence like any other, so it
arrives typed, cited, and carrying its own falsifying test.

**The dangerous failure mode is not a missed precedent. It is a confident wrong one.**
A plausible but inapplicable prior incident anchors the hypothesis board and sends the
investigation down a path that feels evidenced. So the headline metric for this agent is
false precedent rate, not hit rate, and "no applicable precedent" is a first-class,
contract-valid answer rather than a failure to be tuned away.

### Rules inherited from the repo

- No vendor name appears inside the spec. Retrieval lives entirely behind the tool
  surface, exactly as telemetry and change history do.
- This agent reads its own evidence surface and no other agent's.
- Every claim carries `confidence` and `falsifying_test`. A claim cannot shed its
  caveats when it changes hands.
- Nothing is written anywhere. This agent reads and reasons. The Scribe writes.

### Non-goals

- No fine-tuning, no model training.
- No new orchestration. The existing driver composes the acts.
- No second datastore technology beyond what the adapter needs.

---

## 2. Interface first

Write `interfaces/PRECEDENT.md` before any code, in the register of
`interfaces/TELEMETRY.md`. It defines the `precedent_archive` surface,
platform-agnostic, so swapping the backing store changes one endpoint.

Tool calls on the surface:

| Call | Input | Returns |
|---|---|---|
| `precedent.search` | signature terms, symptom text, optional time bound | ranked passages, each with a stable citation and a relevance score |
| `passage.get` | passage id | full passage plus its citation |
| `coverage.describe` | none | what the archive contains: source families, date range, document count |

`coverage.describe` is not decoration. An agent that reports "no applicable precedent"
must be able to say what it searched, or the refusal is unfalsifiable.

**Citation shape.** Every passage returns `source_uri`, `heading_path`, `ordinal` and
`passage_id`. A passage that cannot produce a citation must not be retrievable. This is
the retrieval equivalent of the record being written only through a provable tool call.

---

## 3. The agent spec

`.agents/precedent-analyst.yaml`, validating against OAS 1.6.0.

**Task:** `recall`

**Input:** the incident view (same fixture shape the other agents receive), plus the
Telemetry Analyst's typed findings when the driver composes it live.

**Output contract:**

```yaml
no_applicable_precedent: bool        # true is a valid, complete answer
search_coverage:                     # required, always
  sources_searched: [str]
  date_range: str
  queries_issued: [str]
precedents:                          # empty when no_applicable_precedent
  - incident_ref:
      source_uri: str
      heading_path: str
      passage_id: str
    signature_overlap: str           # what actually matched, in words
    divergence: str                  # required: how this incident differs
    resolution_taken: str
    applicability: enum              # applies | partial | superseded
    confidence: enum                 # matches the commander's vocabulary
    falsifying_test: str             # required
    grounded_in: [str]               # passage_ids, required, non-empty
```

Three contract decisions worth stating explicitly, because they are the point:

- **`grounded_in` is required and non-empty.** A precedent that cannot name the
  passages it rests on cannot exist in the output. This is the grounding guard, and it
  fails closed in the schema, like the falsifying test on the commander's board.
- **`divergence` is required.** Not "how this matches", which the model will always
  find, but how it differs. A precedent offered without a stated difference is the
  anchoring failure in progress.
- **`applicability: superseded`** exists so a precedent whose resolution has since been
  invalidated by a change can be surfaced without being recommended.

**Prompt requirements:** answer only from retrieved passages; never from background
knowledge about the products involved. When coverage does not support a precedent,
return `no_applicable_precedent: true` with populated `search_coverage`, rather than the
nearest-looking match.

---

## 4. Retrieval implementation (adapter side)

All of this lives in `mock/adapter.py --surface precedent_archive` and later in a real
adapter. The agent spec never sees it.

- **Store:** PostgreSQL with `pgvector`. Chosen because it is the database an enterprise
  already runs; state this in `docs/`.
- **Chunking:** heading-aware, never mid-sentence, carrying `heading_path` down. Keep a
  fixed-size chunker alongside it as the baseline for Phase 5.
- **Retrieval:** hybrid. Vector (`hnsw`, cosine) in parallel with Postgres full-text
  (`tsvector`, `ts_rank_cd`), fused with reciprocal rank fusion, then reranked with a
  local cross-encoder. Defaults k=20 each, RRF constant 60, rerank to top 5, all config
  driven.
- **Embeddings and reranker:** local models, so the demo runs without a second API
  dependency and cost stays in the generation stage only.
- **Confidence floor:** if the top reranked score falls below a configured threshold, the
  surface returns an empty result set with coverage populated. The agent then has no
  passages to ground a claim in, and the contract does the rest.

Choose a port that does not collide with the existing surfaces (telemetry 8422,
change_registry 8423, incident_record 8425); check the adapter before picking.

---

## 5. Corpus

`corpus/manifest.yaml` records source, licence and fetch date for everything ingested.

- Public operational documentation only: Kubernetes, Prometheus, PostgreSQL,
  cloud provider runbook and troubleshooting docs.
- Synthetic prior incident records generated by `fixtures/generate.py`, written in the
  shape the Scribe files, so the archive contains the artefacts this system itself
  produces. That closure is worth having: the fifth agent reads what the fourth writes.
- Nothing client, employer or customer derived. Not in the corpus, not in the eval set,
  not in a screenshot.

Include, deliberately, at least one synthetic prior incident that is a **near miss**:
similar signature, different cause, resolution that would be actively wrong to repeat.
The eval set uses it.

---

## 6. Governance demo: grounding

Add a fourth mode to `demos/governance.sh`:

```bash
./demos/governance.sh grounding
```

Assert both paths, in the style of the existing attribution demo.

> Built as two modes rather than one, `grounding` and `refusal`, because they
> are two controls. Grounding fails closed in the schema. Refusal is not a
> schema property at all: it is the surface returning nothing above its
> relevance floor and the agent reporting that as a complete answer, so the
> only way to show it is to run it. A mode that bundled them would exit zero on
> either.

- **Fire.** Input is an incident whose signature superficially resembles the near-miss
  record. Correct behaviour: the precedent is returned with `applicability: partial`, a
  populated `divergence`, and a `falsifying_test` that would distinguish the two. It is
  not offered as cause.
- **Reject.** The same input with `demos/grounding-stripped-system-prompt.txt`, a
  producer instructed to assert the precedent from recall without citing passages. The
  output contract refuses it: `OUTPUT_SCHEMA_ERROR: 'grounded_in' is a required
  property`. A precedent that cannot show its passages cannot exist.

  The stripped prompt has to name the precedent it is asserting, the way the
  guard-stripped prompt names the party. Told only that it need not look things up, the
  model called the archive anyway and refused honestly, which exits zero and
  demonstrates nothing.

Both paths check the agent's citations against the adapter log rather than against the
output, which claims tool use it cannot prove. The archive logs `hit {passage_id}
{source_uri}#{ordinal}` for every passage that leaves the surface, so a `grounded_in` id
the archive never returned fails the demo, and the working note dated inside the
incident's window can be reported as retrieved and uncited rather than assumed to be.

`./demos/governance.sh` with no argument now runs five modes and exits zero only if all
five behave.

---

## 7. Evaluation

New directory `evals/`. This is the part that turns a plausible agent into a measured one.

### Dataset (`evals/dataset.yaml`)

30 to 50 entries against the actual corpus. Written: 38 cases, with the field
reference and the design notes in `evals/README.md`.

```yaml
- id: b01
  group: near_miss
  as_of: "2026-03-17T19:30:00+00:00"
  symptom: "<what was reported, in the words it was reported in>"
  signature: host.memory.exhaustion:intg-prod-b7   # entity id attached, as the signals carry it
  query: heap resize tuning change swap            # canonical probe, retrieval-only mode
  expect:
    precedent_exists: true
    # The diverging record AND the procedure that covers the failure in view.
    # Both halves, always: omitting the procedure is how a case quietly stops
    # counting a miss its probe cannot reach. See evals/RELEVANCE.md.
    relevant: [corpus://incidents/INC-2411, corpus://runbooks/memory-pressure]
    applicability:
      corpus://incidents/INC-2411: partial
      corpus://runbooks/memory-pressure: applies
    divergence_names: ["the prior incident had a change to revert and this one has none"]
    queries_must_not_contain: ["intg-prod-b7"]
```

At least eight entries with `precedent_exists: false`, and at least four near-miss cases.
The dataset carries 13 and 7, and `evals/validate.py` asserts both minima.

**Ground truth names documents, not passages.** This section previously specified
`expected_passages: [<passage_id>, ...]`, which cannot work. `corpus/ingest.py`
derives a passage id from `chunker|source_uri|heading_path|ordinal`, so the chunker
name is inside the key and the two indexes share no id: 82 passages under
heading-aware, 39 under fixed, disjoint id spaces. Since the baseline is recorded
against the fixed chunker and Phase 5 compares heading-aware against it,
passage-level ground truth would score zero on whichever index it was not written
against, and the measured improvement would be the id scheme changing rather than
retrieval getting better. Ground truth is `source_uri`; the cost is that document-level
truth cannot tell a citation of the right document's `Resolution` from its `Gaps`.
That cost is unmeasured rather than mitigated. Adapter-log groundedness proves only
that a cited passage was in the returned set, so a citation of `Gaps` passes whenever
`Gaps` was a hit, and `groundedness_judge` in the metrics table below is a separate
LLM-judge check. Both are written, and neither closes this gap: the judge is handed
the passages a claim cites and asked whether they support it, which says nothing
about whether a different section was the one to cite. The limit belongs in the
results table and is in it.

The dataset is hand-authored and has no generator, because ground truth generated
from the retriever measures only that the retriever agrees with itself. It is made
checkable instead: `evals/validate.py` asserts every claim the corpus can settle,
against both indexes, in CI.

`expect.relevant` is a property of the incident as a case states it, meaning
(`as_of`, `symptom`, `evidence`, `missing_evidence`), never of what the case is
testing or what its query can reach. Scoping it to the case is the subtle way the
dataset would grade itself: a pair the probe cannot reach goes unlisted and is
never counted as a miss. The judgements are recorded in `evals/RELEVANCE.md`.

### Metrics

| Metric | Definition | Why it is here |
|---|---|---|
| `false_precedent_rate` | precedents offered as `applies` where truth is `partial`, `superseded` or none ÷ total | the anchoring failure, when it is claimed |
| `applies_omission_rate` | documents whose truth is `applies`, which the surface returned to the agent, and on which no precedent was offered ÷ those documents | the anchoring failure's quiet twin, and the reason the rate above cannot be read alone: it can only fire on a claim that was made |
| `no_precedent_accuracy` | correct `no_applicable_precedent` ÷ total novel | refusal is a feature |
| `false_refusal_rate` | refusals where a precedent existed ÷ total answerable | the cost of the above |
| `precedent_hit_rate@k` | expected document in top-k retrieved | retrieval quality proper |
| `mrr@k` | mean reciprocal rank of first expected document | |
| `groundedness_log` | cited `passage_id`s that were in the set the adapter returned, read from the audit log | a citation that was never returned is invented |
| `groundedness_judge` | precedent claims whose cited passages support what the claim says, judged at temperature 0 with the judge prompt committed | the log check cannot ask this |
| `agent_reach` | relevant documents the archive returned across the queries the agent chose | retrieval measured on the agent's queries rather than the canonical probe |
| `divergence_quality` | near-miss cases where `divergence` names the actual distinguishing factor | the near-miss guard, measured |
| `p50` / `p95_latency_ms` | per stage and end to end | |
| `cost_per_recall_usd` | unmeasured: `oa` reports no token usage, so this would be a price list times an estimate. The judge's own usage is recorded, because the API returns it | |

`false_precedent_rate` is scored over claims and can be zero for a reason that
is not calibration: on all three Phase 5 sweeps the agent never used `applies` at
all, offering `partial` or `superseded` on every claim. The judgement tables print
the applicability distribution beside the rate for that reason, and
`applies_omission_rate` is the row that catches what it cannot.

Everything above except `groundedness_judge` and `divergence_quality` is
deterministic: it follows from the typed output, the adapter's audit log and the
ground truth, and anyone can recheck it from the JSON record. Those two are a
model's opinion of a model. They are reported in a separate table, never beside
the deterministic ones, because a judged number in a deterministic table reads as
the same kind of fact.

### Runner

```bash
python3 evals/runner.py --config evals/config.yaml
python3 evals/runner.py --config evals/config.yaml --check
python3 evals/runner.py --compare evals/results/<a>.json evals/results/<b>.json
```

Writes timestamped JSON plus `evals/results/latest.md` as a table ready for the README.
Written, for retrieval. `--check` regenerates the table and fails if it has drifted,
which is why the table carries no timestamp and no latency figure: it is a function
of the dataset, the corpus and the config, and CI treats it like any other generated
artefact. Its table still lists every judgement metric as unmeasured, with where each
one is measured instead, because a table listing only what it measured reads as the
whole result.

Judgement mode is written and lives in `evals/judgement.py`:

```bash
python3 evals/judgement.py --list-arms
python3 evals/judgement.py --dry-run                 # spends nothing
python3 evals/judgement.py --cases a01,b01,e01       # a cheap smoke run
python3 evals/judgement.py --arm judgement-heading   # a full sweep, live
python3 evals/judgement.py --check-prompts           # CI: derived arm prompts
python3 evals/judgement.py --check-records          # is a sweep owed
```

One live `oa run` per case, an API key and the provider patch. Its output is a
record of one run rather than a regenerable artefact, so it carries a
timestamp, the spec, the prompt, the model and the case ids, and nothing in CI
diffs it. The inputs it names can still be checked, and `--check-records` is
the one to run before spending: it compares the spec, prompt, index, corpus,
ground truth and judge a recording names against what is on disk, and says
which of three remedies the arm is owed. A fresh sweep, when an input the runs
depended on has moved. A `--rejudge`, one model call per claim against passages
the record already holds, when the judge or the code that drives it has moved.
Or a free `--rescore`, when only the deterministic scoring has.

`--compare` on two judgement records refuses two arms that differ in more than
one thing, refuses two records of the same arm, and says in the output that
one sweep is one sample of a stochastic system.

**Two hit rates, and the second is not a footnote.** `precedent_hit_rate@k` ranks
documents with nothing truncating, which is a property of the ranking alone.
`precedent_hit_rate@limit` counts what survives inside a fixed passage budget of
eight, where chunk size decides how many distinct documents fit. That budget is an
eval parameter and not the agent's: the surface defaults to five, this spec tells the
agent to ask for breadth without naming a number, and no demo passes one. They differ at
the budget, 38/60 against 36/60, and at k = 2, where heading-aware reaches 25 of 60
pairs against fixed's 24. They are identical at k = 1, 3, 5 and 8, which is the grid
the baseline reads: the one relevant document that moves, `b03`'s `INC-2446`, sits
between grid points. Phase 5 must report both, since either alone answers a question
it was not asked.

**A claim about two indexes may not live in a table generated from one.** An earlier
version of this section said the ranking was chunker-blind, and the sentence sat in
the generated baseline table where `--check` regenerated it identically whatever the
other index did. `--cross-check` scores both indexes at every k from 1 to the deepest
rank any relevant document reaches, finds the k values where they part rather than
taking a grid, and writes `evals/results/chunker-comparison.md`, which CI diffs.
It scores both indexes at the passage budget as well: `latest.md` holds that figure
for the baseline index only, so the other half of `38/60 against 36/60` was prose
no check could falsify until the cross-check measured it.

---

## 8. Phases

**Phase 0, Interface.** `interfaces/PRECEDENT.md` written and reviewed against
`interfaces/TELEMETRY.md` for consistency of register and shape.
*Done when:* the surface is fully specified with no implementation named.

**Phase 1, Adapter and corpus.** Postgres with pgvector up, manifest populated,
ingest running with both chunkers, all three tool calls serving fixture-backed results
with citations.
*Done when:* re-ingesting unchanged sources embeds nothing new, and `precedent.search`
returns cited passages for a hand-written query.

**Phase 2, Agent spec.** `.agents/precedent-analyst.yaml` validates against OAS 1.6.0
and runs standalone against the adapter, producing contract-valid output on a fixture.
*Done when:* `oa run --spec .agents/precedent-analyst.yaml --task recall` returns
precedents whose citations resolve back through `passage.get`.

**Phase 3, Refusal and grounding.** Confidence floor wired, `no_applicable_precedent`
path exercised, `demos/governance.sh grounding` passing both paths.
*Done when:* a novel incident produces a coverage-populated refusal, and the
grounding-stripped producer is rejected by the schema. Done, as
`demos/governance.sh grounding` and `demos/governance.sh refusal`, both live.

**Phase 4, Evals baseline.** Dataset written, metrics implemented, baseline recorded
with the fixed-size chunker and no reranker.
*Done when:* `latest.md` holds a complete baseline table.
Done. The dataset, its integrity check, the runner, the retrieval metrics and the
fixed-chunker baseline went in first, with CI failing if the table drifts off the
corpus or the dataset. The judgement metrics followed: `false_precedent_rate`,
`no_precedent_accuracy`, `false_refusal_rate` and `groundedness_log` are read off the
typed output and the adapter's audit log, and `groundedness_judge` and
`divergence_quality` are judged at temperature 0 with the prompts committed in
`evals/judges/`. Neither groundedness check closes the section-level gap, and both
tables say so.

**Phase 5, Measured improvement.** At least two experiments:
heading-aware versus fixed chunking, and the retrieval guidance the spec's rule 4
fixes versus one verbose query.
*Done when:* `--compare` shows the delta on `false_precedent_rate`,
`precedent_hit_rate@5`, groundedness and `p95_latency_ms`, and the README states what
you kept, what you rejected, and what latency you accepted for it.

**The second experiment used to say "hybrid with versus without the reranker", and
there is no reranker in this repo to switch off.** Section 4 describes one for a real
adapter; the mock ranks by term overlap and takes none, and `evals/runner.py` now
refuses a config declaring one rather than recording a configuration nothing produced.
A local cross-encoder would also put a model dependency inside a directory whose
retrieval half deliberately runs on stdlib and PyYAML. The retrieval guidance is the
configuration this project actually decided, on a measurement, so it is the one worth
testing: at the bridge bound the reported symptom used whole scores 79 of 82 passages
above zero and clears the floor 0 times, while the signature type alone scores 54 and
clears 35. The arm is the shipped system prompt with that paragraph replaced by the
instruction someone would plausibly have written without the measurement, derived from
the spec so the two differ in that paragraph and nothing else.

**The paragraph is not one instruction, and the arm measures the paragraph.** Rule 4
says to query more than once *and* to ask for enough breadth, because the surface caps
how many passages a single document contributes. The replacement drops both, and the
records show the second doing real work: the shipped arm passed `limit: 8` on 157 of
its 182 searches, the alternative passed no limit at all on 41 of its 43 and took the
surface default of five. So the delta belongs to the paragraph and not to query count
inside it. Neither `--compare` nor `--check-prompts` can see this: one paragraph is one
knob to both. Separating them needs a fourth arm that keeps the breadth instruction,
and it is not run.

Done. Three arms recorded, both comparisons run, and the README carries what was
kept, what was rejected and the latency accepted for it. The guidance arm is the
decisive one: replacing rule 4 refuses 8 of 25 answerable cases against none and
reaches 22 of 60 relevant pairs against 54, at half the latency. The chunker arm is a
result nobody should choose on rather than a null one: the same reach and the same
order of omissions, a judged half parting at 39 of 52 claims supported against 49
of 56, an ordering that held in all three judgings of the same claims while its
size moved by several points, and still not enough to decide with. Heading-aware is kept for its citations carrying the heading
chain, which is a property and not a measured win.

**The headline rate could not fire, and that is the result the arms share.**
`false_precedent_rate` is 0 in all three, and `applies` appears in none of the 130
claims. `applies_omission_rate` is what catches the failure instead: 14 of 23
documents the ground truth says apply here, returned to the agent and never offered,
mostly the covering runbook procedures. It does not catch the other shape, a barred or
unrelated document offered as `partial`, which is how the anchoring failure actually
presented on `d01` and `g01`. Nothing scores that yet.

Read the deltas across both modes, because neither mode can produce all four numbers.
`precedent_hit_rate@5` is retrieval mode and a property of the surface;
`false_precedent_rate`, both groundedness figures and the agent's `p95` are judgement
mode. `agent_reach` is the bridge between them: retrieval on the queries the agent
chose rather than on the dataset's canonical probe.

**Phase 6, Composition.** `demos/investigate.sh` stays three acts: recall runs
alongside detect, and its typed output enters the commander's input as `precedent`
next to `findings` and `correlation`. The commander's board must be able to cite a
precedent as supporting evidence without it counting as deciding evidence.
*Done when:* one run produces a board whose hypotheses reference precedent by
`passage_id`, and convergence still blocks on outstanding deciding evidence.

**Phase 7, Documentation.** README section, architecture diagram updated to five
agents and three evidence surfaces, results table, design decisions.

---

## 9. README additions

Update the flowchart to add `PRE[("precedent_archive")] --> PA["Precedent Analyst<br/>recall"]`
and `PA -- "typed precedent" --> IC`. Extend the artefact table with the new spec,
interface, adapter surface, dataset and demo.

Add a short section in the register of "The contract that matters":

> **Precedent without anchoring.** Recall is the most seductive failure in incident
> response: a prior incident that resembles this one arrives already believed. The
> Precedent Analyst cannot return a precedent without naming the passages it rests on,
> cannot return one without stating how this incident differs, and returns
> `no_applicable_precedent` with its search coverage rather than the nearest match.
> Measured on the near-miss cases in `evals/`, where the resolution that worked last
> time is the wrong thing to do now.

Then the results table, with the before and after from Phase 5.

---

## 10. Guardrails

- Public documentation and synthetic records only. Never client-derived material.
- Every retrieval number in the README regenerable by the runner, and checked in CI.
  The judgement numbers are not: they are records of one live run, a fresh sweep of the
  same arm gives different figures, and each record carries the timestamp, spec, prompt,
  model and case ids that produced it. `--rescore` recomputes the deterministic half
  from a stored record and prints what moved. A guardrail promising regeneration for
  those would be one the artefacts cannot keep.
- No question, passage or answer text in span attributes if tracing is added; correlate
  by id and log separately, so the observability story survives a privacy review.
- Prefer the honest measurement over the impressive one. The method is the artefact.
