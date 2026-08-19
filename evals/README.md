# Evals

Measured retrieval quality for the Precedent Analyst. `docs/precedent-analyst.md`
section 7 specifies it; this directory implements it.

The agent's headline risk is not the missed precedent, it is the confident
wrong one. So the metrics that matter here are the ones that punish a
plausible answer: a precedent offered as applying when the record diverges, and
a refusal issued when the archive held something.

## What is here

| File | What it is |
| --- | --- |
| `dataset.yaml` | 38 cases with ground truth. Hand-authored. |
| `RELEVANCE.md` | How `expect.relevant` is judged, and why it is not scoped to the case. |
| `validate.py` | Asserts every claim in the dataset the corpus can settle. Runs in CI against both indexes. |
| `runner.py` | Measures retrieval against the dataset. Writes a timestamped JSON record and `results/latest.md`. |
| `config.yaml` | The baseline configuration: fixed chunker, no reranker, the k values, the passage budget. |
| `results/` | Timestamped run records, `latest.md` (the baseline table) and `chunker-comparison.md`. |

The judgement metrics are not written. `runner.py --mode judgement` says so and
exits rather than reporting a partial table under a whole name. See **Status**.

## Running it

```bash
python3 evals/validate.py                                   # heading-aware index
python3 evals/validate.py --index corpus/index.fixed.json   # the Phase 4 baseline
python3 evals/validate.py --repin                           # after a corpus change

python3 evals/runner.py --config evals/config.yaml          # record the baseline
python3 evals/runner.py --config evals/config.yaml --check   # CI: has the table drifted
python3 evals/runner.py --config evals/config.yaml --cross-check          # both indexes, every k
python3 evals/runner.py --config evals/config.yaml --cross-check --check  # CI
python3 evals/runner.py --index corpus/index.json --chunker heading --label heading-aware
python3 evals/runner.py --compare evals/results/<a>.json evals/results/<b>.json
```

Needs PyYAML. Neither an API key nor the `patches/` provider patch is required
by either script in retrieval mode: both drive the mock surface directly and
never call a model. That is the point of splitting the modes, and it is what
makes iterating on the dataset affordable.

`runner.py` refuses to run if the corpus fingerprint has moved off the
dataset's pin, and refuses if the config's `chunker` disagrees with the index
it names. Recording a baseline against the wrong index is the one mistake that
would make the Phase 5 comparison meaningless while looking entirely normal.
`--compare` refuses two runs that differ in corpus, ground truth, relevance
floor, passage budget or k list, and refuses a record too old to state one of
them. Each of those produces a plausible delta rather than an error, and the
delta is that input moving rather than retrieval improving.

Only a `--config` run writes `latest.md`. An exploratory `--index` run writes
its JSON and leaves the committed table alone, because it used to overwrite it
silently and the next `--check` reported drift that was the scratch run.

`runner.py` also refuses to measure through an adapter it did not start, and
proves the one it did start is serving the index that was asked for by
resolving a passage id taken from that index file. A passage id carries the
chunker name, so a leftover process serving the other index cannot pass it.

## The dataset

38 cases, against the 17-document corpus in `corpus/`.

| Group | Cases | What it tests |
| --- | --- | --- |
| `composite` | 4 | The scenario itself, at both bounds it is run at |
| `near_miss` | 7 | Records that match on symptom and diverge on what to do |
| `applies` | 8 | Precedent that genuinely transfers |
| `record_status` | 3 | A draft cannot ground a claim, however well it matches |
| `novel` | 10 | No counterpart in the archive; refusal is the correct answer |
| `time_bound` | 4 | An archive that held nothing yet, against one that held nothing relevant |
| `identity` | 2 | The entity id is not a similarity feature |

13 cases have no applicable precedent, against a specified minimum of eight.
Seven are near misses, against a minimum of four. `validate.py` asserts both
minima, so the composition cannot drift below what the spec fixes.

### Ground truth names documents, not passages

`docs/precedent-analyst.md` sketched the dataset with
`expected_passages: [<passage_id>, ...]`. That cannot work here, and the reason
is worth stating because the sketch reads as obviously right.

`corpus/ingest.py` derives a passage id from
`chunker|source_uri|heading_path|ordinal`. The chunker name is inside the key,
so the two indexes share no id at all: 82 passages under heading-aware, 39
under fixed, disjoint id spaces. Phase 4 records its baseline against the fixed
chunker and Phase 5 compares heading-aware against it, so passage-level ground
truth would score zero on whichever index it was not written against, and the
entire Phase 5 improvement would be the id scheme changing rather than
retrieval getting better.

Ground truth is `source_uri`, which both chunkers agree on, and
`precedent_hit_rate@k` is measured over documents.

**What this costs, and it is more than it first looks.** Document-level truth
cannot tell a citation of the right document's `Resolution` section from its
`Gaps` section. Nothing else measures it either:

- Adapter-log groundedness proves only that a cited `passage_id` was in the set
  the surface returned. A precedent citing `Gaps` passes whenever `Gaps` was
  among the hits, which the two-passages-per-document cap makes common.
- The `groundedness` in the metrics table is a different check again, an LLM
  judge at temperature 0. Neither it nor the log check is written yet.

So the section-level gap is **unmeasured, not mitigated**, and it belongs in the
results table as such. An earlier draft of this file claimed groundedness
covered it; that was using the weaker check to wave away the cost.

If section quality has to be measured before Phase 5, the way in is an optional
heading-level expectation scored against the heading-aware index only, never
folded into the cross-chunker `hit_rate` comparison, which is the one number the
fixed baseline has to be able to share.

### Why it is hand-authored

Every other artefact derived from the corpus is generated with a `--check` that
fails on drift, so the instinct is to generate this too. Ground truth is a
judgement about which prior records a responder would want to see, and a
dataset generated from the retriever's output measures only that the retriever
agrees with itself.

The cases are made checkable instead. `validate.py` asserts, per case and per
index:

- the corpus is the one this ground truth was judged against, by a fingerprint
  over every document's sha256. Names existing is not enough: a document can be
  rewritten under the same uri, or a new one added, and every citation still
  resolves while the judgement behind it has gone stale. A corpus change fails
  here on purpose, and `--repin` is what you run after re-reading the affected
  judgements rather than instead of it
- every `source_uri` named still exists in the corpus
- a document claimed unreachable at a bound really is recorded after it
- a document named relevant is not one the bound puts out of reach
- every relevant document carries an applicability truth, so
  `false_precedent_rate` cannot silently skip one
- a filed document barred from grounding a claim argues why, per uri, in
  `must_not_cite_reason`, and a reason cannot outlive the entry it justified
- a case whose failure has a covering procedure in the archive, in reach at its
  bound, either names it or argues the omission in `covering_procedure_waived`
- what `coverage_describe` reports at a case's bound matches `coverage_expect`
- the retrieval figures a case states, per index: how much scored above zero,
  where a named document lands in the returned order, and what an identity
  probe clears
- stated `cleared_floor` and `candidates_considered` figures still hold
- `must_be_retrieved` documents are still returned, so a case about rejecting
  the hindsight trap fails rather than passing vacuously if the trap stops
  being reachable
- a document a case bars from grounding a claim, and which that case's own
  probe returns, is guarded by `must_be_retrieved`. Three cases bar a document
  their probe does not reach, because the agent issues queries this dataset
  does not; `d02` holds the trap's reachability for those, and if it ever stops
  returning it, that fails
- a no-precedent case retrieves nothing it does not explicitly allow, so a
  refusal case cannot decay into a judgement call
- the canonical query obeys the rule the agent is scored against, carrying no
  entity id

Negative-tested: each of those checks was confirmed to fail on a deliberately
broken case before being relied on.

The last three of those exist because figures kept living in prose. A number in
an `intent` paragraph is a comment, and one had already rotted before anyone
noticed: `g01` claimed its identity probe clears the floor seven times, which is
the fixed index's figure, while heading-aware gives nine. Anything a case
asserts about retrieval is a field now.

### What validate.py deliberately does not check

That the documents a case calls `relevant` are the ones the surface returns.
That number is `precedent_hit_rate`, it is what the runner reports, and
asserting it here would let the dataset grade itself: any case the retriever
missed could be "fixed" by editing the ground truth. It is printed as an
observation instead, so a collapse is visible without being enforced.

At limit 8, on a single canonical query, that observation currently reads:

| Index | Relevant documents reached |
| --- | --- |
| heading-aware | 36 / 60 |
| fixed | 38 / 60 |

`runner.py` reports the same two numbers as `precedent_hit_rate@limit`, from
the same probes. Deliberately the same figure in two places rather than two
figures: this one is printed as an observation the dataset must not be edited
to satisfy, and the runner's is the measurement. If they ever disagree, one of
them has changed what it counts.

**Read the denominator, not the ratio.** These are one query per case against
relevance that is scoped to the incident, so a case probing one axis of a
multi-axis incident is counted as missing the documents its other axis reaches.
`a03` searches the denial-daemon axis and is marked down for not returning the
memory-exhaustion records, which is correct: the spec tells the agent to query
more than once, and this observation deliberately does not.

`a04` is included, and that is deliberate. Its canonical query is the reported
symptom used whole, it reaches none of its five relevant documents, and it was
excluded from this figure on the reasoning that a probe designed to retrieve
nothing should not be mixed with probes designed to retrieve. That was the
fitting move in miniature: five real misses of a real query, uncounted because
the query cannot reach them.

Earlier versions of this file published 36/41, then 36/51, 36/53, 36/54 and
36/55. The denominator moved five times and the retriever never changed once.
Each step was a set of misses the bookkeeping had been hiding: relevance scoped
per case, then a rule applied to one group and not the next, then a case whose
gold set told an agent to refuse, then this exclusion.

That fixed edges heading-aware on this probe is worth noting rather than
explaining away: larger chunks match more query terms. Whether heading-aware
wins on the metrics that matter is Phase 5's question, and it is not settled in
advance.

## Status

Phase 4 is done for retrieval and open for judgement.

- [x] Dataset written, 38 cases, composition asserted
- [x] Integrity check, both indexes, in CI
- [x] Retrieval metrics implemented: `precedent_hit_rate@k`, `mrr@k`, and the
      hit rate at the passage budget the agent is run at
- [x] Runner, `--compare`, `--check`, `results/latest.md`, drift checked in CI
- [x] Baseline recorded against the fixed chunker with no reranker
- [ ] Judgement metrics: `false_precedent_rate`, `no_precedent_accuracy`,
      `false_refusal_rate`, `divergence_quality`
- [ ] `groundedness`, which needs a judge prompt at temperature 0 that is not
      designed yet, and which does not close the section-level gap above

### What the baseline says, and the finding in it

`results/latest.md` has the table. The one result worth carrying forward:

**Two hit rates, because there are two questions.** Ranking documents with
nothing truncating asks which prior records the surface orders highest.
Counting what survives inside the passage budget the agent is actually run at
asks what it is handed, and chunk size decides how many distinct documents fit
in eight passages.

The chunkers differ on both, in different places. At the budget it is 38/60
against 36/60. On the ranking they are identical at k = 1, 3, 5 and 8, and
differ at k = 2, where heading-aware reaches 25 of 60 pairs against fixed's 24:
`b03`'s `INC-2446` is rank 2 under heading-aware and rank 3 under fixed, and
the baseline's grid steps over the gap that lives in.

This file said the ranking was **chunker-blind**, flatly, and that was wrong.
Two failures produced it, and both are worth naming because neither was a
retrieval mistake:

- **A grid was mistaken for every k.** Four k values were chosen for the table,
  the two indexes agreed on all four, and the conclusion drawn was about all k.
- **The claim lived where nothing could falsify it.** It was a hardcoded
  sentence in `runner.py`'s table generator, and `--check` regenerates the
  baseline against one index. Both sides of the diff carried the same sentence
  whatever the other index did, so CI certified it while being structurally
  unable to test it.

The fix for the second is `--cross-check`, which scores both indexes at every k
from 1 to the deepest rank any relevant document reaches, reports the k values
where they part rather than taking a grid, and writes
`results/chunker-comparison.md` with its own `--check` in CI. Grok found the
first in review of PR #16; the k = 2 figure was measured rather than argued
about.

For Phase 5 the consequence is that both numbers get reported. Either alone
answers a question it was not asked.

### Notes for the runner

Two things the dataset already forces.

**Split the modes.** Retrieval metrics (`precedent_hit_rate@k`, `mrr@k`) are
measured from the surface with no model in the loop, from each case's `query`.
The judgement metrics (`false_precedent_rate`, `no_precedent_accuracy`,
`false_refusal_rate`, `groundedness`, `divergence_quality`) need a live
`oa run` per case, which costs an API call and needs the `patches/` provider
patch. Keeping retrieval-only runs free is what makes iterating on the dataset
affordable.

**Score the agent on its own queries, not the canonical one.** `query` exists
so the surface can be measured independently. The agent chooses its own
queries, records them in `search_coverage.queries_issued`, and
`queries_must_not_contain` is checked against those. Case `a04` is the one that
makes this matter: its canonical query is the reported symptom used whole,
which clears the floor zero times on both indexes, so an agent that issues one
verbose query retrieves nothing and refuses. The archive holds precedent, so
that refusal counts as a false refusal.
