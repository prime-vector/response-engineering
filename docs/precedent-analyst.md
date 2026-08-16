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
| `search_precedent` | signature terms, symptom text, optional time bound | ranked passages, each with a stable citation and a relevance score |
| `get_passage` | passage id | full passage plus its citation |
| `describe_coverage` | none | what the archive contains: source families, date range, document count |

`describe_coverage` is not decoration. An agent that reports "no applicable precedent"
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

- **Fire.** Input is an incident whose signature superficially resembles the near-miss
  record. Correct behaviour: the precedent is returned with `applicability: partial`, a
  populated `divergence`, and a `falsifying_test` that would distinguish the two. It is
  not offered as cause.
- **Reject.** The same input with `demos/grounding-stripped-system-prompt.txt`, a
  producer instructed to assert the precedent from recall without citing passages. The
  output contract refuses it: `OUTPUT_SCHEMA_ERROR: 'grounded_in' is a required
  property`. A precedent that cannot show its passages cannot exist.

`./demos/governance.sh` with no argument now runs four modes and exits zero only if all
four behave.

---

## 7. Evaluation

New directory `evals/`. This is the part that turns a plausible agent into a measured one.

### Dataset (`evals/dataset.yaml`)

30 to 50 entries against the actual corpus:

```yaml
- id: p001
  incident_signature: "sustained pod evictions following a node pool upgrade"
  expected_passages: ["<passage_id>", "<passage_id>"]
  expected_applicability: applies
  precedent_exists: true

- id: p017
  incident_signature: "<the near-miss signature>"
  expected_applicability: partial
  must_state_divergence: true
  precedent_exists: true

- id: p031
  incident_signature: "<a genuinely novel failure>"
  precedent_exists: false          # correct answer is no_applicable_precedent
```

At least eight entries with `precedent_exists: false`, and at least four near-miss cases.

### Metrics

| Metric | Definition | Why it is here |
|---|---|---|
| `false_precedent_rate` | precedents offered as `applies` where truth is `partial`, `superseded` or none ÷ total | the headline; this is the anchoring failure |
| `no_precedent_accuracy` | correct `no_applicable_precedent` ÷ total novel | refusal is a feature |
| `false_refusal_rate` | refusals where a precedent existed ÷ total answerable | the cost of the above |
| `precedent_hit_rate@k` | expected passage in top-k retrieved | retrieval quality proper |
| `mrr@k` | mean reciprocal rank of first expected passage | |
| `groundedness` | fraction of precedent claims traceable to a cited passage, judged at temperature 0 with the judge prompt committed | |
| `divergence_quality` | near-miss cases where `divergence` names the actual distinguishing factor | the near-miss guard, measured |
| `p50` / `p95_latency_ms`, `cost_per_recall_usd` | per stage and end to end | |

### Runner

```bash
python3 evals/runner.py --config evals/config.yaml
python3 evals/runner.py --compare evals/results/<a>.json evals/results/<b>.json
```

Writes timestamped JSON plus `evals/results/latest.md` as a table ready for the README.

---

## 8. Phases

**Phase 0, Interface.** `interfaces/PRECEDENT.md` written and reviewed against
`interfaces/TELEMETRY.md` for consistency of register and shape.
*Done when:* the surface is fully specified with no implementation named.

**Phase 1, Adapter and corpus.** Postgres with pgvector up, manifest populated,
ingest running with both chunkers, all three tool calls serving fixture-backed results
with citations.
*Done when:* re-ingesting unchanged sources embeds nothing new, and `search_precedent`
returns cited passages for a hand-written query.

**Phase 2, Agent spec.** `.agents/precedent-analyst.yaml` validates against OAS 1.6.0
and runs standalone against the adapter, producing contract-valid output on a fixture.
*Done when:* `oa run --spec .agents/precedent-analyst.yaml --task recall` returns
precedents whose citations resolve back through `get_passage`.

**Phase 3, Refusal and grounding.** Confidence floor wired, `no_applicable_precedent`
path exercised, `demos/governance.sh grounding` passing both paths.
*Done when:* a novel incident produces a coverage-populated refusal, and the
grounding-stripped producer is rejected by the schema.

**Phase 4, Evals baseline.** Dataset written, metrics implemented, baseline recorded
with the fixed-size chunker and no reranker.
*Done when:* `latest.md` holds a complete baseline table.

**Phase 5, Measured improvement.** At least two experiments:
heading-aware versus fixed chunking, and hybrid with versus without the reranker.
*Done when:* `--compare` shows the delta on `false_precedent_rate`,
`precedent_hit_rate@5`, `groundedness` and `p95_latency_ms`, and the README states what
you kept, what you rejected, and what latency you accepted for it.

**Phase 6, Composition.** `demos/investigate.sh` becomes four acts: recall runs
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
- Every number in the README regenerable by the runner.
- No question, passage or answer text in span attributes if tracing is added; correlate
  by id and log separately, so the observability story survives a privacy review.
- Prefer the honest measurement over the impressive one. The method is the artefact.
